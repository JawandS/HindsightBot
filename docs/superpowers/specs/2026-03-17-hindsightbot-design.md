# HindsightBot Design Spec

**Date:** 2026-03-17
**Status:** Approved

---

## Overview

HindsightBot is an AI agent system that validates whether predictions came true. It maintains a sourced, historical record for each prediction — verdict, summary, sources, and investigation history. The first dataset is the AI Daily Brief's 50 predictions for 2026. The system is designed as a modular framework to support additional prediction collections (tabs) in the future.

---

## Architecture

Two Railway services sharing one PostgreSQL database:

### Web Service (FastAPI + HTMX)
- **Public UI:** Polished, elegant interface for browsing prediction collections
- **Admin UI:** Barebones, functional interface at `/admin` for managing predictions and triggering investigations
- Serves Tailwind-built CSS as a static file (no CDN)

### Worker Service (Python)
- Polls on a configurable interval (`WORKER_POLL_INTERVAL_SECONDS`, default: 300)
- On each poll cycle:
  1. Resets stuck jobs (`status = running`, `started_at` older than 30 minutes) back to `pending`
  2. Converts elapsed `next_check_at` predictions (status = `unresolved`, `next_check_at <= now`, no existing `pending`/`running` job) into new `pending` job rows
  3. Claims and processes `pending` jobs using `SELECT ... FOR UPDATE SKIP LOCKED`
- Claims jobs atomically to be safe across multiple worker instances
- Runs as a persistent Railway service alongside the web server

### Shared
- PostgreSQL on Railway (single instance, shared by both services)
- `agents/` and `db/` packages used by both services
- Single `pyproject.toml` managed by `uv`
- SQLAlchemy connection pool defaults are sufficient for this scale (single worker + low-traffic web service)

---

## Enums

All enum values stored in the database use lowercase snake_case strings:

| Enum | Values |
|------|--------|
| `predictions.status` | `unresolved`, `came_true`, `came_false` |
| `investigations.verdict` | `unresolved`, `came_true`, `came_false` |
| `jobs.status` | `pending`, `running`, `done`, `failed` |

---

## Data Model

```sql
collections
  id, name, description, created_at

predictions
  id, collection_id, text            -- collection_id FK → collections.id
  status           -- enum: unresolved | came_true | came_false  (default: unresolved)
  summary          -- denormalized from latest completed investigation
  next_check_at    -- timestamp set by Scheduler; null until first investigation completes
  created_at, updated_at

investigations
  id, prediction_id, verdict         -- verdict enum: unresolved | came_true | came_false
  summary, investigated_at           -- investigated_at is a full timestamp (serves as created_at)

sources                              -- one investigation has N source rows (3-5)
  id, investigation_id, url, title, relevance_summary, created_at

jobs
  id, prediction_id
  status           -- enum: pending | running | done | failed
  created_at, started_at, completed_at, error_message
```

**Notes:**
- `sources` are scoped to a specific `investigation` — one investigation inserts 3–5 source rows, all sharing the same `investigation_id`
- `jobs` is a lightweight Postgres-based queue — no Redis or message broker needed
- `predictions.summary` and `predictions.status` are updated in the same DB transaction as the investigation insert — latest investigation always wins (no conditional promotion logic)
- When a verdict of `came_true` or `came_false` is returned, `next_check_at` is left as-is; it becomes irrelevant because the worker's job-creation query filters on `status = unresolved`
- Failed investigations (job status = `failed`) do not produce an `investigations` row — errors are captured only in `jobs.error_message`
- The worker retrieves collection context for the Investigator by JOINing `predictions → collections` on `predictions.collection_id`
- Recommended DB indexes: `predictions(status, next_check_at)` and `jobs(status)` for worker polling queries

---

## Agent Pipeline

### 1. Investigator Agent
**Input:** prediction text + collection name/description (retrieved via JOIN from `collections`)

**Model:** `gpt-4o` via the OpenAI Responses API with the `web_search_preview` built-in tool

**Process:**
1. Uses OpenAI web search to find current evidence for or against the prediction
2. Selects 3–5 sources: title, URL, 1-2 sentence relevance summary

**Output:** `verdict` (`unresolved` | `came_true` | `came_false`), `summary` (1-2 sentences), `sources[]`

**Writes to DB (single transaction):**
1. Inserts `investigations` row with verdict and summary
2. Inserts N `sources` rows linked to that investigation
3. Updates `predictions.status`, `predictions.summary`, `predictions.updated_at`

**Failure handling:**
- On OpenAI API error or malformed/invalid response: retry up to 3 times with exponential backoff
- After 3 failures: mark job as `failed`, store error in `jobs.error_message`; do not update prediction status or insert investigation/source rows
- A `failed` job does not block future investigations — admin can re-trigger manually

### 2. Scheduler Agent
**Triggered:** After every `unresolved` investigation result (called within the same worker task, immediately after the Investigator completes)

**Input:** prediction text + investigation summary

**Model:** `gpt-4o`

**Process:** Reasons about prediction context to determine the right re-check window (e.g., "this is about a Q3 event — revisit in 3 months")

**Output:** Structured interval: `{value: int, unit: "days" | "weeks" | "months"}`

**Validation:** `value` must be between 1 and 365. `unit` must be one of the three allowed values. If the LLM returns out-of-range or malformed output, default to `{value: 30, unit: "days"}` and log a warning.

**Failure handling:** Retry up to 3 times with exponential backoff. If all retries fail, default to `{value: 30, unit: "days"}` and log a warning — `next_check_at` must always be set after an unresolved investigation.

**Writes to DB:** Sets `next_check_at = now + interval` on the prediction.

---

## UI

### Public View (polished)
- Tabbed by collection (data-driven from the `collections` table — no code changes needed to add tabs)
- Predictions displayed as cards/table: text, status badge, last checked date
- Clicking a prediction expands inline (HTMX) to show:
  - 1-2 sentence summary
  - Sources: title, URL, 1-2 sentence relevance blurb
  - Investigation history: past verdicts + timestamps
- Unresolved predictions show estimated next check date
- Served over HTTPS only (Railway provides TLS termination)

### Admin View (barebones, `/admin`)
- Protected by HTTP Basic Auth (`ADMIN_USERNAME` + `ADMIN_PASSWORD` env vars)
- Must only be served over HTTPS — Railway TLS handles this in production
- Features:
  - List all predictions with status, `next_check_at`, and job status
  - "Investigate Now" button per prediction: server-side enforced — checks for existing `pending`/`running` job before inserting; no-ops if one already exists; returns HTMX partial updating the button to show "Queued"
  - "Investigate All Unresolved" button: enqueues one `pending` job per unresolved prediction, skipping any that already have a `pending` or `running` job; returns HTMX partial showing count of newly enqueued jobs (e.g., "12 jobs queued"); executes asynchronously (worker picks up on next poll)
  - **Seeder form:** select collection (or create new), paste newline-separated prediction texts → bulk insert; deduplicates by case-insensitive, whitespace-normalized text match within the collection; returns HTMX partial showing "X added, Y skipped as duplicates"
  - Prediction text from the seeder form is treated as untrusted input; the Investigator prompt wraps it with explicit delimiters to limit prompt injection risk
  - Add new collection form (name + description)

---

## Project Structure

```
hindsightbot/
├── web/
│   ├── main.py                 # FastAPI app, routes
│   ├── templates/
│   │   ├── base.html
│   │   ├── public/             # Polished public templates
│   │   └── admin/              # Barebones admin templates
│   ├── static/
│   │   └── styles.css          # Built by Tailwind CLI at build time
│   └── input.css               # Tailwind source
├── worker/
│   └── main.py                 # Poll loop entrypoint
├── agents/
│   ├── investigator.py
│   └── scheduler.py
├── db/
│   ├── models.py               # SQLAlchemy models
│   └── migrations/             # Alembic migrations
├── pyproject.toml              # uv project config (shared)
├── scripts/
│   └── download_tailwind.sh    # Downloads Tailwind standalone binary at build time (linux/amd64)
├── railway.toml                # Multi-service config
└── .env.example
```

---

## Deployment

### Railway Services
| Service | Build Command | Start Command |
|---------|--------------|---------------|
| `web` | `uv sync && bash scripts/download_tailwind.sh && ./tailwindcss -i web/input.css -o web/static/styles.css --minify` | `uvicorn web.main:app --host 0.0.0.0 --port $PORT` |
| `worker` | `uv sync` | `python worker/main.py` |

**Tailwind binary:** `scripts/download_tailwind.sh` downloads the Tailwind standalone CLI binary for `linux/amd64` (Railway's build platform) from the official GitHub release and places it at `./tailwindcss` in the project root (matching the build command reference). The binary is not committed to the repo and is re-downloaded on each build.

**Database migrations:** Alembic migrations run as a Railway release command on the `web` service: `uv run alembic upgrade head`. This runs after build and before the new container starts serving traffic. If the migration fails, Railway aborts the deploy and keeps the previous container running — no rollback script is needed.

**`railway.toml`:** Configures the two services using Railway's multi-service format (see [Railway docs](https://docs.railway.com/reference/config-as-code)). Defines `[services.web]` and `[services.worker]` with their respective build/start/release commands.

### Environment Variables
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Postgres connection string (Railway-provided) |
| `OPENAI_API_KEY` | OpenAI API key |
| `ADMIN_USERNAME` | HTTP Basic Auth username for `/admin` |
| `ADMIN_PASSWORD` | HTTP Basic Auth password for `/admin` |
| `WORKER_POLL_INTERVAL_SECONDS` | Worker poll frequency in seconds (default: `300`) |

### Security
- Admin routes protected by HTTP Basic Auth at the FastAPI middleware level
- Both `ADMIN_USERNAME` and `ADMIN_PASSWORD` only in Railway environment variables, never committed
- No admin endpoints exposed through public routing
- All traffic served over HTTPS via Railway TLS termination

---

## Initial Data Setup

The 50 AI Daily Brief 2026 predictions are seeded via the admin UI seeder form after first deployment:
1. Deploy to Railway
2. Navigate to `/admin`
3. Create collection: "AI Daily Brief — 50 Predictions for 2026"
4. Paste the newline-separated list of predictions into the seeder form and submit
5. Trigger "Investigate All Unresolved" to kick off the initial investigation run

---

## Extensibility

The framework is designed for future prediction collections:
- New collections are added via the admin seeder form — no code changes needed
- Additional tabs in the public UI are data-driven from the `collections` table
- Worker and agents are collection-agnostic — they operate on predictions regardless of source
- Future source-type metadata (e.g., YouTube channel, newsletter) can be added as a `collections.source_type` column when needed; deferred for now
