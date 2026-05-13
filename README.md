# Exam Calendar

A mobile-first, localhost-only academic calendar for Santiago's Moodle dates.

The app is now a small FastAPI service. The frontend does **not** hardcode exam dates: it calls `/api/events`, and the backend derives events from the local Moodle tracker at `http://127.0.0.1:8000`.

## What gets pulled

- `/deadlines/upcoming` for quiz/deadline items.
- Course snapshots for schedule PDFs/docs.
- Stored Moodle artifacts from the tracker when extraction failed, e.g. DOCX cronogramas in R2/S3.
- Local `config/manual-overrides.json` only for user-specific context, like marking the skipped Cálculo I first parcial as skipped.

## Safe local run

Bind to localhost only:

```bash
cd /home/sam/projects/exam-calendar
uvicorn server:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

Do **not** bind to `0.0.0.0` unless you intentionally want LAN exposure.

## API

```text
GET /api/health
GET /api/events
GET /api/events?refresh=true
```

The frontend refresh button calls `GET /api/events?refresh=true`.

## Autostart

A systemd user service is installed as:

```text
~/.config/systemd/user/exam-calendar.service
```

Useful commands:

```bash
systemctl --user status exam-calendar.service
systemctl --user restart exam-calendar.service
journalctl --user -u exam-calendar.service -f
```

## Configuration

Environment variables used by `server.py`:

- `MOODLE_TRACKER_API` default: `http://127.0.0.1:8000`
- `MOODLE_TRACKER_DIR` default: `/home/sam/projects/moodle-tracker`
- `EXAM_CALENDAR_CACHE_TTL` default: `300`
- `EXAM_CALENDAR_YEAR` default: `2026`
- `EXAM_CALENDAR_TZ` default: `America/Argentina/Buenos_Aires`

Manual overrides live in:

```text
config/manual-overrides.json
```
