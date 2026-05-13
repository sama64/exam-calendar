const SUBJECTS = {
  calc: { name: "Cálculo I", color: "var(--calc)" },
  mat: { name: "Materiales", color: "var(--mat)" },
  termo: { name: "Termodinámica", color: "var(--termo)" },
  mec: { name: "Mecánica", color: "var(--mec)" },
};

let events = [];
let apiMeta = null;
let currentMonth = localDate(new Date().getFullYear(), new Date().getMonth() + 1, 1);

const fmtLong = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });
const fmtShort = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const fmtMonth = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });
const fmtStamp = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function today() {
  const now = new Date();
  return localDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
}
function localDate(year, month, day) { return new Date(year, month - 1, day); }
function parseLocalDate(dateString) {
  if (!dateString) return null;
  const [year, month, day] = dateString.split("-").map(Number);
  return localDate(year, month, day);
}
function daysBetween(a, b) {
  const start = localDate(a.getFullYear(), a.getMonth() + 1, a.getDate());
  const end = localDate(b.getFullYear(), b.getMonth() + 1, b.getDate());
  return Math.round((end - start) / 86400000);
}
function eventDate(event) { return parseLocalDate(event.date); }
function byDate(a, b) {
  if (!a.date) return 1;
  if (!b.date) return -1;
  return eventDate(a) - eventDate(b);
}
function timeLabel(event) {
  if (event.startTime && event.endTime) return `${event.startTime}–${event.endTime}`;
  if (event.endTime && event.type === "deadline") return `due ${event.endTime}`;
  if (event.startTime) return event.startTime;
  return "time TBD";
}
function countdownLabel(event) {
  if (!event.date) return "unknown";
  if (event.status === "skipped") return "skipped";
  const diff = daysBetween(today(), eventDate(event));
  if (diff < 0) return "past";
  if (diff === 0) return "today";
  if (diff === 1) return "tomorrow";
  return `${diff} days`;
}
function groupLabel(event) {
  if (!event.date) return "Unknown";
  if (event.status === "skipped" || daysBetween(today(), eventDate(event)) < 0) return "Past / skipped";
  const diff = daysBetween(today(), eventDate(event));
  if (diff <= 7) return "This week";
  if (diff <= 21) return "Next three weeks";
  if (eventDate(event).getMonth() === 5) return "June boss rush";
  return "July cleanup";
}
function subject(event) { return SUBJECTS[event.subject] || { name: event.subjectName || event.subject, color: "var(--muted)" }; }
function statusText(status) {
  return ({ confirmed: "confirmed", recovery: "recuperatorio", skipped: "skipped", due: "deadline", unconfirmed: "unconfirmed" })[status] || status;
}

async function loadEvents({ refresh = false } = {}) {
  setLoadingState(refresh ? "Refreshing Moodle tracker…" : "Loading Moodle tracker dates…");
  const response = await fetch(`/api/events${refresh ? "?refresh=true" : ""}`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || "Could not load events");
  }
  events = payload.events || [];
  apiMeta = payload;
  if (!events.length) throw new Error("Tracker returned no calendar events.");
  render();
}

function setLoadingState(message) {
  document.getElementById("todayStrip").innerHTML = `<span class="pill">${message}</span>`;
  document.getElementById("panicPanel").innerHTML = `<article class="next-card"><div><div class="next-kicker">Tracker</div><div class="next-title">Loading</div><div class="next-subtitle">Asking Moodle what chaos it has prepared.</div></div></article>`;
}

function setErrorState(error) {
  document.getElementById("todayStrip").innerHTML = `<span class="pill">Tracker unavailable</span>`;
  document.getElementById("panicPanel").innerHTML = `
    <article class="next-card">
      <div>
        <div class="next-kicker">Could not load dates</div>
        <div class="next-title">Moodle tracker error</div>
        <div class="next-subtitle">${escapeHtml(error.message)}</div>
      </div>
    </article>
  `;
}

function render() {
  const generated = apiMeta?.generatedAt ? fmtStamp.format(new Date(apiMeta.generatedAt)) : "unknown";
  document.getElementById("todayStrip").innerHTML = `
    <span class="pill">Today: ${fmtLong.format(today())}</span>
    <span class="pill">${upcomingEvents().length} active items left</span>
    <span class="pill">Synced: ${generated}</span>
    ${apiMeta?.errors?.length ? `<span class="pill warning">${apiMeta.errors.length} extraction warning${apiMeta.errors.length > 1 ? "s" : ""}</span>` : ""}
  `;
  renderPanicPanel();
  renderAgenda();
  renderMonth();
  renderSubjects();
}

function upcomingEvents() {
  return events.filter(e => e.date && e.status !== "skipped" && daysBetween(today(), eventDate(e)) >= 0).sort(byDate);
}

function renderPanicPanel() {
  const next = upcomingEvents()[0];
  if (!next) {
    document.getElementById("panicPanel").innerHTML = `
      <article class="next-card">
        <div>
          <div class="next-kicker">Next up</div>
          <div class="next-title">Nothing active</div>
          <div class="next-subtitle">No upcoming confirmed items. Suspiciously peaceful.</div>
        </div>
      </article>
    `;
    return;
  }
  const rushWindow = events.filter(e => e.date && eventDate(e) >= localDate(2026,6,23) && eventDate(e) <= localDate(2026,6,27));
  document.getElementById("panicPanel").innerHTML = `
    <article class="next-card" style="--accent:${subject(next).color}">
      <div>
        <div class="next-kicker">Next up</div>
        <div class="next-title">${escapeHtml(subject(next).name)} · ${escapeHtml(next.title)}</div>
        <div class="next-subtitle">${fmtShort.format(eventDate(next))} · ${timeLabel(next)}</div>
      </div>
      <div class="countdown-big"><div><span>${daysBetween(today(), eventDate(next))}</span><small>days</small></div></div>
    </article>
    <article class="stress-card">
      <div class="stress-title">⚠ Heavy week ahead</div>
      <p class="stress-copy">${rushWindow.length} events between <b>Jun 23–27</b>. That's the danger zone. Not impossible — just not something to "future you" into oblivion.</p>
    </article>
  `;
}

function eventCard(event) {
  const s = subject(event);
  const date = eventDate(event);
  const sourceTitle = event.source?.title ? escapeHtml(event.source.title) : "local/manual";
  const sourceUrl = event.source?.url;
  return `
    <article class="event-card ${event.type} ${event.status}" style="--accent:${s.color}">
      <div class="subject-line">
        <span class="subject-name">${escapeHtml(s.name)}</span>
        <span class="badge ${event.status}">${statusText(event.status)}</span>
      </div>
      <h3 class="event-title">${escapeHtml(event.title)}</h3>
      <div class="event-meta">
        <span class="badge">${date ? fmtShort.format(date) : "date TBD"}</span>
        <span class="badge">${event.date ? timeLabel(event) : "not posted"}</span>
        <span class="badge countdown">${countdownLabel(event)}</span>
      </div>
      ${event.note ? `<p class="event-note">${escapeHtml(event.note)}</p>` : ""}
      <details class="source-details">
        <summary>Source</summary>
        ${sourceUrl ? `<a href="${sourceUrl}" target="_blank" rel="noreferrer">${sourceTitle}</a>` : `<span>${sourceTitle}</span>`}
      </details>
    </article>
  `;
}

function groupedCards(list) {
  let lastGroup = "";
  return list.map(event => {
    const group = groupLabel(event);
    const header = group !== lastGroup ? `<div class="group-label">${group}</div>` : "";
    lastGroup = group;
    return header + eventCard(event);
  }).join("");
}

function renderAgenda() {
  const active = events.filter(e => e.date && e.status !== "skipped" && daysBetween(today(), eventDate(e)) >= 0).sort(byDate);
  const past = events.filter(e => e.status === "skipped" || (e.date && daysBetween(today(), eventDate(e)) < 0)).sort(byDate);
  document.getElementById("agendaList").innerHTML = groupedCards(active);
  document.getElementById("pastList").innerHTML = `<div class="group-label">Past / skipped</div>${past.map(eventCard).join("")}`;
}

function renderMonth() {
  document.getElementById("monthTitle").textContent = fmtMonth.format(currentMonth);
  const grid = document.getElementById("monthGrid");
  const first = localDate(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
  const firstDayIndex = (first.getDay() + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - firstDayIndex);
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    const key = isoDate(day);
    const dayEvents = events.filter(e => e.date === key);
    const classes = ["day-cell"];
    if (day.getMonth() !== currentMonth.getMonth()) classes.push("outside");
    if (sameDay(day, today())) classes.push("today");
    if (dayEvents.length) classes.push("has-events");
    const dots = dayEvents.slice(0,4).map(e => `<span class="dot" style="--accent:${subject(e).color}"></span>`).join("");
    const itemCount = dayEvents.length;
    const ariaLabel = `${fmtLong.format(day)}${itemCount ? `, ${itemCount} item${itemCount > 1 ? "s" : ""}` : ", no items"}`;
    cells.push(`<button class="${classes.join(" ")}" data-date="${key}" aria-label="${ariaLabel}"><span class="day-num">${day.getDate()}</span><span class="dots">${dots}</span></button>`);
  }
  grid.innerHTML = cells.join("");
  grid.querySelectorAll(".day-cell").forEach(btn => btn.addEventListener("click", () => showSelectedDay(btn.dataset.date)));
}

function showSelectedDay(dateString) {
  const list = events.filter(e => e.date === dateString);
  const box = document.getElementById("selectedDay");
  if (!list.length) {
    box.className = "selected-day empty-state";
    box.textContent = "Nothing posted for this date. A tiny miracle.";
    return;
  }
  box.className = "selected-day";
  box.innerHTML = `<div class="group-label">${fmtLong.format(parseLocalDate(dateString))}</div>${list.map(eventCard).join("")}`;
}

function renderSubjects() {
  const keys = Object.keys(SUBJECTS);
  document.getElementById("subjectCards").innerHTML = keys.map(key => {
    const subjectEvents = events.filter(e => e.subject === key);
    const upcoming = subjectEvents.filter(e => e.date && e.status !== "skipped" && daysBetween(today(), eventDate(e)) >= 0).sort(byDate);
    const unknown = subjectEvents.filter(e => e.status === "unconfirmed");
    const next = upcoming[0];
    return `
      <article class="subject-card" style="--accent:${SUBJECTS[key].color}">
        <h3>${SUBJECTS[key].name}</h3>
        <div class="subject-stats">
          <span class="badge">${upcoming.length} upcoming</span>
          ${unknown.length ? `<span class="badge unconfirmed">dates missing</span>` : ""}
        </div>
        <ul>
          ${next ? `<li>Next: ${escapeHtml(next.title)} · ${fmtShort.format(eventDate(next))}</li>` : ""}
          ${unknown.map(e => `<li>${escapeHtml(e.title)}: ${escapeHtml(e.note || "No date posted.")}</li>`).join("")}
          ${!next && !unknown.length ? `<li>No active confirmed dates.</li>` : ""}
        </ul>
      </article>
    `;
  }).join("");
}

function isoDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
function sameDay(a, b) { return isoDate(a) === isoDate(b); }
function resetSelectedDay() {
  const box = document.getElementById("selectedDay");
  box.className = "selected-day empty-state";
  box.textContent = "Tap a marked day to inspect it.";
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function bindUI() {
  document.querySelectorAll(".segment").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".segment").forEach(b => {
        b.classList.toggle("active", b === button);
        b.setAttribute("aria-pressed", b === button ? "true" : "false");
      });
      document.querySelectorAll(".view").forEach(v => v.classList.remove("active-view"));
      document.getElementById(`${button.dataset.view}View`).classList.add("active-view");
    });
  });
  document.getElementById("togglePast").addEventListener("click", (event) => {
    const past = document.getElementById("pastList");
    past.classList.toggle("hidden");
    event.target.textContent = past.classList.contains("hidden") ? "Show skipped" : "Hide skipped";
  });
  document.getElementById("refreshEvents").addEventListener("click", async () => {
    try {
      await loadEvents({ refresh: true });
    } catch (error) {
      setErrorState(error);
    }
  });
  document.getElementById("prevMonth").addEventListener("click", () => {
    currentMonth = localDate(currentMonth.getFullYear(), currentMonth.getMonth(), 1);
    resetSelectedDay();
    renderMonth();
  });
  document.getElementById("nextMonth").addEventListener("click", () => {
    currentMonth = localDate(currentMonth.getFullYear(), currentMonth.getMonth() + 2, 1);
    resetSelectedDay();
    renderMonth();
  });
}

bindUI();
loadEvents().catch(setErrorState);
