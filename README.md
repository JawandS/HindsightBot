# HindsightBot

A prediction validation agent that automatically checks whether predictions came true using OpenAI web search.

## How It Works

1. Add predictions via the `/admin` panel
2. A background worker periodically investigates each prediction using OpenAI's Responses API with web search
3. Predictions are marked `came_true`, `came_false`, or remain `unresolved` until enough evidence exists
4. Results are displayed on the public-facing feed

## Stack

- **Backend**: Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL
- **Frontend**: HTMX, Jinja2, Tailwind CSS
- **AI**: OpenAI Responses API + `web_search_preview`
- **Infrastructure**: Two Railway services — `web` (FastAPI) + `worker` (poll loop), shared Postgres

## Setup

### Prerequisites

- Python 3.12+, [uv](https://github.com/astral-sh/uv)
- PostgreSQL
- OpenAI API key

### Local Development

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL, OPENAI_API_KEY, ADMIN_USERNAME, ADMIN_PASSWORD

# Run migrations
uv run alembic upgrade head

# Start the web server
uv run uvicorn web.app:app --reload

# In a separate terminal, start the worker
uv run python -m agents.worker
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | required |
| `OPENAI_API_KEY` | OpenAI API key | required |
| `ADMIN_USERNAME` | HTTP Basic Auth username for `/admin` | required |
| `ADMIN_PASSWORD` | HTTP Basic Auth password for `/admin` | required |
| `WORKER_POLL_INTERVAL_SECONDS` | How often the worker polls for jobs | `300` |

## Deployment (Railway)

1. Push to GitHub and connect to Railway
2. Add a Postgres plugin to the project
3. Create two services: one for `web`, one for `worker`
4. Set the env vars on both services
5. Visit `/admin` to create a collection and seed predictions

## Admin Panel

`/admin` — protected by HTTP Basic Auth

- Create prediction collections
- Paste newline-separated predictions (deduplicated case-insensitively)
- "Investigate Now" — enqueue a single job
- "Investigate All Unresolved" — bulk enqueue

## License

MIT
