from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
CONFIG_DIR = APP_DIR / "config"
CACHE_TTL_SECONDS = int(os.environ.get("EXAM_CALENDAR_CACHE_TTL", "300"))
MOODLE_API_BASE = os.environ.get("MOODLE_TRACKER_API", "http://127.0.0.1:8000").rstrip("/")
CURRENT_YEAR = int(os.environ.get("EXAM_CALENDAR_YEAR", "2026"))
LOCAL_TZ = ZoneInfo(os.environ.get("EXAM_CALENDAR_TZ", "America/Argentina/Buenos_Aires"))
ACADEMIC_STATE_PATH = Path(
    os.environ.get(
        "ACADEMIC_STATE_PATH",
        "/home/sam/projects/academic-record/data/academic-state.yaml",
    )
)

app = FastAPI(title="Exam Calendar", version="1.0.0")

_cache: dict[str, Any] = {"at": 0.0, "payload": None}

SUBJECT_NAMES = {
    "calc": "Cálculo I",
    "mat": "Materiales",
    "termo": "Termodinámica",
    "mec": "Mecánica de los Materiales",
}

SUBJECT_PROFILES = {
    "calculo i": {
        "key": "calc",
        "display_name": "Cálculo I",
        "moodle_aliases": ["calculo i"],
        "extractor": "calculo",
    },
    "mecanica de los materiales": {
        "key": "mec",
        "display_name": "Mecánica de los Materiales",
        "moodle_aliases": ["mecanica de los materiales"],
        "extractor": "mecanica",
    },
}

MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


@dataclass(frozen=True)
class SourceRef:
    item_id: int | None
    title: str
    url: str | None


def api_get(path: str, timeout: int = 20) -> Any:
    url = f"{MOODLE_API_BASE}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def item_text(item: dict[str, Any]) -> str:
    body = item.get("body_text") or ""
    if body.strip():
        return body
    return ""


def get_artifact_text(item_id: int) -> str:
    content = api_get(f"/items/{item_id}/content", timeout=30)
    best_text = ""
    for artifact in content.get("artifacts", []):
        candidate = artifact.get("extracted_text") or ""
        if len(candidate) > len(best_text):
            best_text = candidate
    return best_text


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def iso_date(day: int, month: int, year: int = CURRENT_YEAR) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_slash_date(raw: str) -> str | None:
    match = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", raw)
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    year = int(match.group(3)) if match.group(3) else CURRENT_YEAR
    if year < 100:
        year += 2000
    return iso_date(day, month, year)


def parse_dash_date(raw: str) -> str | None:
    match = re.search(r"(\d{1,2})-(\d{1,2})(?:-(\d{2,4}))?", raw)
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    year = int(match.group(3)) if match.group(3) else CURRENT_YEAR
    if year < 100:
        year += 2000
    return iso_date(day, month, year)


def parse_spanish_date(text: str) -> str | None:
    match = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)", text, re.I)
    if not match:
        return None
    day = int(match.group(1))
    month = MONTHS_ES.get(match.group(2).lower())
    if not month:
        return None
    return iso_date(day, month, CURRENT_YEAR)


def make_event(
    *,
    event_id: str,
    subject: str,
    title: str,
    date: str | None,
    type_: str,
    status: str,
    source: SourceRef | None,
    start_time: str | None = None,
    end_time: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "subject": subject,
        "subjectName": SUBJECT_NAMES[subject],
        "title": title,
        "date": date,
        "startTime": start_time,
        "endTime": end_time,
        "type": type_,
        "status": status,
        "note": note,
        "source": {
            "itemId": source.item_id if source else None,
            "title": source.title if source else "local/manual",
            "url": source.url if source else None,
        },
    }


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def subject_key(subject: dict[str, Any]) -> str:
    profile = SUBJECT_PROFILES.get(normalize_name(subject.get("name") or ""))
    if profile:
        return profile["key"]
    code = normalize_name(str(subject.get("code") or subject.get("id") or "subject"))
    return code.replace(" ", "-")


def active_academic_subjects() -> tuple[str | None, list[dict[str, Any]]]:
    """Load the active roster and period from the canonical academic record."""
    import yaml

    state = yaml.safe_load(ACADEMIC_STATE_PATH.read_text(encoding="utf-8")) or {}
    active: list[dict[str, Any]] = []
    periods: list[str] = []
    for raw in state.get("subjects", []):
        if raw.get("status") != "in_course":
            continue
        events = raw.get("events") or []
        subject_periods = [
            str(event["academic_period"])
            for event in events
            if event.get("type") == "En curso" and event.get("academic_period")
        ]
        period = subject_periods[-1] if subject_periods else None
        if period:
            periods.append(period)
        key = subject_key(raw)
        profile = SUBJECT_PROFILES.get(normalize_name(raw.get("name") or ""), {})
        name = profile.get("display_name") or raw.get("name") or key
        SUBJECT_NAMES[key] = name
        active.append(
            {
                "key": key,
                "name": name,
                "code": str(raw.get("code") or ""),
                "academicPeriod": period,
                "extractor": profile.get("extractor"),
                "moodleAliases": profile.get("moodle_aliases") or [normalize_name(name)],
            }
        )
    current_period = max(periods) if periods else None
    return current_period, active


def period_tokens(period: str | None) -> list[str]:
    match = re.fullmatch(r"(\d{4})-(\d)C", period or "")
    if not match:
        return []
    year, number = match.groups()
    ordinal = {"1": "1er", "2": "2do"}.get(number, number)
    return [normalize_name(period or ""), normalize_name(f"{ordinal} Cuat. de {year}"), normalize_name(f"{number} cuatrimestre {year}")]


def discover_courses(
    courses: list[dict[str, Any]],
    active_subjects: list[dict[str, Any]],
    current_period: str | None,
) -> dict[str, int]:
    """Match active subjects to Moodle, preferring the current-period shell."""
    mapping: dict[str, int] = {}
    tokens = period_tokens(current_period)
    for subject in active_subjects:
        candidates: list[tuple[int, int]] = []
        aliases = [normalize_name(alias) for alias in subject.get("moodleAliases", [])]
        for course in courses:
            name = normalize_name(course.get("display_name") or "")
            if not any(alias and alias in name for alias in aliases):
                continue
            current_bonus = 100 if any(token and token in name for token in tokens) else 0
            candidates.append((current_bonus + int(course.get("id") or 0), int(course["id"])))
        if candidates:
            mapping[subject["key"]] = max(candidates)[1]
    return mapping


def schedule_candidates(snapshot: dict[str, Any], *needles: str) -> list[dict[str, Any]]:
    candidates = []
    for item in snapshot.get("items", []):
        title = item.get("title") or ""
        haystack = title.lower()
        if all(needle.lower() in haystack for needle in needles):
            candidates.append(item)
    candidates.sort(key=lambda i: i.get("updated_at") or "", reverse=True)
    return candidates


def select_schedule_item(snapshot: dict[str, Any], *needles: str) -> dict[str, Any] | None:
    candidates = schedule_candidates(snapshot, *needles)
    return candidates[0] if candidates else None


def source_for(item: dict[str, Any]) -> SourceRef:
    return SourceRef(item.get("id"), item.get("title") or "Untitled", item.get("primary_url"))


def extract_calculo_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    item = select_schedule_item(snapshot, "cronograma", "calculo") or select_schedule_item(snapshot, "cronograma", "cálculo")
    if not item:
        return []
    text = item_text(item)
    if not text.strip():
        text = get_artifact_text(item["id"])
    source = source_for(item)
    events: list[dict[str, Any]] = []
    patterns = [
        (r"(\d{1,2}/\d{1,2})\s+Primer\s+Parcial", "Primer Parcial", "exam", "confirmed"),
        (r"(\d{1,2}/\d{1,2})\s+Segundo\s+Parcial", "Segundo Parcial", "exam", "confirmed"),
        (r"(\d{1,2}/\d{1,2})\s+1er\s+Rec\.\s+1er\s+Parcial", "1er Recuperatorio · 1er Parcial", "recovery", "recovery"),
        (r"(\d{1,2}/\d{1,2})\s+1er\s+Rec\.\s+2do\s+Parcial", "1er Recuperatorio · 2do Parcial", "recovery", "recovery"),
        (r"(\d{1,2}/\d{1,2})\s+2do\s+Rec\.\s+1er\s+Parcial", "2do Recuperatorio · 1er Parcial", "recovery", "recovery"),
        (r"(\d{1,2}/\d{1,2})\s+2do\s+Rec\.\s+2do\s+Parcial", "2do Recuperatorio · 2do Parcial", "recovery", "recovery"),
    ]
    for pattern, title, type_, status in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        date = parse_slash_date(match.group(1))
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        events.append(make_event(event_id=f"calc-{date}-{slug}", subject="calc", title=title, date=date, type_=type_, status=status, source=source))
    return events


def extract_mecanica_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract source-backed current-period Mecánica assessments."""
    events: list[dict[str, Any]] = []
    for item in snapshot.get("items", []):
        title = normalize_spaces(item.get("title") or "")
        match = re.fullmatch(r"1[º°]?\s*Parcial\s+(\d{1,2}/\d{1,2})", title, re.I)
        if not match:
            continue
        event_date = parse_slash_date(match.group(1))
        events.append(
            make_event(
                event_id=f"mec-{event_date}-primer-parcial",
                subject="mec",
                title="Primer Parcial",
                date=event_date,
                type_="exam",
                status="unconfirmed",
                source=source_for(item),
                note="Date appears in the current 2C gradebook title; awaiting a cronograma or professor announcement.",
            )
        )
    return events


def extract_termo_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    item = select_schedule_item(snapshot, "cronograma", "termodinamica") or select_schedule_item(snapshot, "cronograma", "termodinámica")
    if not item:
        return []
    text = normalize_spaces(item_text(item))
    source = source_for(item)
    specs = [
        (r"(\d{1,2}/\d{1,2}/\d{4})\s+PRIMER\s+PARCIAL\s*\((\d{1,2}:\d{2})\s*a\s*(\d{1,2}:\d{2})", "Primer Parcial práctico", "exam", "confirmed"),
        (r"(\d{1,2}/\d{1,2}/\d{4})\s+SEGUNDO\s+PARCIAL\s*\((\d{1,2}:\d{2})\s*a\s*(\d{1,2}:\d{2})", "Segundo Parcial práctico", "exam", "confirmed"),
        (r"(\d{1,2}/\d{1,2}/\d{4})\s+1er\s+RECUPERATORIO\s+1er\s+y\s+2do\s+PARCIAL\s*\(de\s*(\d{1,2}:\d{2})\s*a\s*(\d{1,2}:\d{2})", "1er Recuperatorio · 1er y 2do Parcial", "recovery", "recovery"),
        (r"(\d{1,2}/\d{1,2}/\d{4})\s+2do\s+RECUPERATORIO\s+1er\s+y\s+2do\s+PARCIAL\s*\(de\s*(\d{1,2}:\d{2})\s*a\s*(\d{1,2}:\d{2})", "2do Recuperatorio · 1er y 2do Parcial", "recovery", "recovery"),
    ]
    events: list[dict[str, Any]] = []
    for pattern, title, type_, status in specs:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        date = parse_slash_date(match.group(1))
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        events.append(make_event(event_id=f"termo-{date}-{slug}", subject="termo", title=title, date=date, start_time=match.group(2), end_time=match.group(3), type_=type_, status=status, source=source))
    return events


def extract_materiales_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = schedule_candidates(snapshot, "cronograma", "ciencia") or schedule_candidates(snapshot, "cronograma", "materiales")
    general_candidates = [item for item in candidates if "laboratorio" not in (item.get("title") or "").lower()]
    item = (general_candidates or candidates or [None])[0]
    if not item:
        return []
    text = item_text(item)
    if not text.strip():
        text = get_artifact_text(item["id"])
    events = extract_materiales_events_from_text(text, source_for(item))
    if events:
        return events
    return [make_event(event_id="mat-dates-unconfirmed", subject="mat", title="Parciales — latest cronogram could not be parsed", date=None, type_="unknown", status="unconfirmed", source=source_for(item), note="The latest Moodle cronogram exists, but the calendar could not extract exam dates from it. Do not rely on older cronogram versions silently.")]


def extract_materiales_events_from_text(text: str, source: SourceRef) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(date: str | None, number: str) -> None:
        if not date:
            return
        key = (date, number)
        if key in seen:
            return
        seen.add(key)
        title = f"Parcial {number}"
        events.append(make_event(event_id=f"mat-{date}-parcial-{number}", subject="mat", title=title, date=date, type_="exam", status="confirmed", source=source))

    normalized = normalize_spaces(text)
    for match in re.finditer(r"(?:\(\s*)?(\d{1,2}-\d{1,2})(?:\s*\))?\s+PARCIAL\s+(\d+)", normalized, re.I):
        add(parse_dash_date(match.group(1)), match.group(2))

    # Fallback for table extraction that preserves one cell per line:
    # date line -> PARCIAL N line.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    current_date: str | None = None
    for line in lines:
        date = parse_dash_date(line) if re.search(r"\d{1,2}-\d{1,2}", line) else None
        if date:
            current_date = date
        match = re.fullmatch(r"PARCIAL\s+(\d+)", line, re.I)
        if current_date and match:
            add(current_date, match.group(1))
    return events


def extract_deadline_events(upcoming: list[dict[str, Any]], courses_by_id: dict[int, str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in upcoming:
        title = item.get("title") or ""
        due_at = item.get("due_at")
        subject = courses_by_id.get(item.get("course_id"))
        if not due_at or not subject:
            continue
        if not re.search(r"cuestionario|quiz|tarea|trabajo|tp|laboratorio|entrega", title, re.I):
            continue
        dt = datetime.fromisoformat(due_at.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        date = dt.date().isoformat()
        end_time = dt.strftime("%H:%M")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        events.append(make_event(event_id=f"{subject}-{date}-{slug}", subject=subject, title=title.replace("PARA RESPONDER", "").strip(), date=date, end_time=end_time, type_="deadline", status="due", source=source_for(item), note="Pulled from /deadlines/upcoming."))
    return events


def apply_manual_overrides(
    events: list[dict[str, Any]], current_period: str | None
) -> list[dict[str, Any]]:
    path = CONFIG_DIR / "manual-overrides.json"
    if not path.exists():
        return events
    data = json.loads(path.read_text())
    # Overrides are period-scoped. A forgotten old file becomes inert instead
    # of leaking last cuatrimestre's exceptions into the new calendar.
    if data.get("academicPeriod") != current_period:
        return events
    ignored_subjects = set(data.get("ignoredSubjects", []))
    if ignored_subjects:
        events = [event for event in events if event.get("subject") not in ignored_subjects]
    by_id = {event["id"]: event for event in events}
    for override in data.get("overrides", []):
        target = by_id.get(override.get("id"))
        if not target:
            continue
        for key in ["status", "note", "type"]:
            if key in override:
                target[key] = override[key]
    for extra in data.get("extraEvents", []):
        extra.setdefault("source", {"itemId": None, "title": "local/manual", "url": None})
        events.append(extra)
    return events


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for event in events:
        key = event["id"]
        deduped[key] = event
    return sorted(deduped.values(), key=lambda e: (e.get("date") or "9999-99-99", e.get("subject") or "", e.get("title") or ""))


def build_events_payload() -> dict[str, Any]:
    health = api_get("/health", timeout=10)
    courses = api_get("/courses", timeout=20)
    current_period, active_subjects = active_academic_subjects()
    course_map = discover_courses(courses, active_subjects, current_period)
    courses_by_id = {course_id: subject for subject, course_id in course_map.items()}
    events: list[dict[str, Any]] = []
    extraction_errors: list[dict[str, str]] = []
    extractor_registry = {
        "calculo": extract_calculo_events,
        "mecanica": extract_mecanica_events,
    }

    for subject in active_subjects:
        key = subject["key"]
        course_id = course_map.get(key)
        subject["courseId"] = course_id
        subject["moodleMatched"] = course_id is not None
        if not course_id:
            extraction_errors.append({"subject": key, "error": "active subject has no current Moodle course match"})
            continue
        extractor = extractor_registry.get(subject.get("extractor"))
        if not extractor:
            # Generic deadlines still work for new subjects. A specialized
            # parser is only needed for dates buried in cátedra documents.
            continue
        try:
            snapshot = api_get(f"/courses/{course_id}/snapshot", timeout=30)
            events.extend(extractor(snapshot))
        except Exception as exc:  # keep the app useful even if one course fails
            extraction_errors.append({"subject": key, "error": str(exc)})

    try:
        events.extend(extract_deadline_events(api_get("/deadlines/upcoming", timeout=20), courses_by_id))
    except Exception as exc:
        extraction_errors.append({"subject": "deadlines", "error": str(exc)})

    events = apply_manual_overrides(dedupe_events(events), current_period)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "generatedAt": generated_at,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
        "academicPeriod": current_period,
        "subjects": active_subjects,
        "tracker": {"baseUrl": MOODLE_API_BASE, "health": health},
        "events": events,
        "errors": extraction_errors,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "tracker": MOODLE_API_BASE, "cacheAgeSeconds": max(0, int(time.time() - _cache.get("at", 0)))}


@app.get("/api/events")
def events_api(refresh: bool = Query(False)) -> JSONResponse:
    now = time.time()
    if refresh or not _cache["payload"] or now - _cache["at"] > CACHE_TTL_SECONDS:
        try:
            _cache["payload"] = build_events_payload()
            _cache["at"] = now
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return JSONResponse(status_code=502, content={"error": "Could not reach Moodle tracker", "detail": str(exc), "events": []})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": "Could not build calendar events", "detail": str(exc), "events": []})
    return JSONResponse(_cache["payload"])


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
