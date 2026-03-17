# HindsightBot

Prediction validation agent. Checks if predictions came true using OpenAI web search.

## Stack
- Python + uv, FastAPI + HTMX + Jinja2, SQLAlchemy + Alembic, PostgreSQL, OpenAI API
- Two Railway services: `web` (FastAPI) + `worker` (poll loop), shared Postgres

## Key Architecture
- Worker polls DB for due jobs (`jobs` table is the queue — no Redis)
- `SELECT FOR UPDATE SKIP LOCKED` for atomic job claiming
- Investigator: two-step — Responses API + web_search_preview → Chat Completions JSON extraction
- Scheduler: sets `next_check_at` after every unresolved investigation
- `db/session.py` and `agents/` use lazy init (no env vars required at import time)

## DB Enums
`verdict_status`: `unresolved | came_true | came_false`
`job_status`: `pending | running | done | failed`

## Admin
- `/admin` — HTTP Basic Auth via `ADMIN_USERNAME` + `ADMIN_PASSWORD` env vars
- Seed predictions via textarea (newline-separated), deduplicated case-insensitively
- "Investigate Now" = enqueue job; "Investigate All Unresolved" = bulk enqueue

## Env Vars
`DATABASE_URL`, `OPENAI_API_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `WORKER_POLL_INTERVAL_SECONDS` (default 300)

## First Deploy
1. Push to GitHub, connect Railway, add Postgres plugin
2. Set env vars on both services
3. `/admin` → create collection → paste 50 predictions → Investigate All Unresolved
