# Exam Calendar

A mobile-first, localhost-only academic calendar for Moodle dates.

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

## Docker / subdomain deployment

The Docker setup keeps the service private to localhost for Caddy to reverse-proxy:

```bash
cd /home/sam/projects/exam-calendar
docker compose up -d --build
curl http://127.0.0.1:8765/api/health
```

Security defaults in `docker-compose.yml`:

- binds only to `127.0.0.1`, not the public interface
- joins only the existing `moodle-tracker_default` Docker network and calls the tracker at `http://api:8000`
- does **not** mount the Moodle tracker `.env` or S3/Moodle credentials
- runs as a non-root user in a read-only container filesystem
- drops Linux capabilities and enables `no-new-privileges`
- adds small CPU/memory/pid/log limits

Example Caddy reverse proxy:

```caddyfile
calendar.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

If port 8765 is still occupied by the old systemd service, either stop it or run Docker on another localhost port:

```bash
EXAM_CALENDAR_PORT=8766 docker compose up -d --build
```

## Autostart

Legacy systemd user service files still exist under `deploy/`, but Docker Compose is the safer path for subdomain exposure.

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
