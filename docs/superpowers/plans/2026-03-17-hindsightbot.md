# HindsightBot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build HindsightBot — an AI agent system that validates predictions with sourced reports, featuring a polished public UI and barebones admin panel, deployed on Railway.

**Architecture:** Two Railway services (FastAPI web + Python worker) sharing a PostgreSQL database. The worker polls for due investigations, running an Investigator agent (OpenAI gpt-4o + web_search_preview) and a Scheduler agent that sets next re-check intervals. The web service serves a Jinja2/HTMX public UI and a Basic Auth-protected admin panel.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, OpenAI Python SDK (Responses API), HTMX, Jinja2, Tailwind CSS v3 standalone CLI, Railway (2 services + Postgres plugin)

---

## File Map

```
hindsightbot/
├── pyproject.toml                          # uv project + all dependencies
├── alembic.ini                             # Alembic config (url overridden in env.py)
├── tailwind.config.js                      # Tailwind v3 content paths
├── railway.toml                            # Multi-service Railway config
├── .env.example                            # All required env vars with descriptions
├── .gitignore
├── scripts/
│   └── download_tailwind.sh                # Downloads Tailwind linux/amd64 binary to ./tailwindcss
├── db/
│   ├── __init__.py
│   ├── session.py                          # Engine, SessionLocal, get_db() dependency
│   ├── models.py                           # All SQLAlchemy models + enums
│   └── migrations/
│       ├── env.py                          # Alembic env (imports models, reads DATABASE_URL)
│       ├── script.py.mako
│       └── versions/
│           └── 001_initial_schema.py       # Creates all tables + indexes
├── agents/
│   ├── __init__.py
│   ├── investigator.py                     # Two-step: web search → structured extraction
│   └── scheduler.py                        # Reasons about re-check interval
├── worker/
│   ├── __init__.py
│   └── main.py                             # Poll loop: reset stuck → promote next_check_at → claim+run jobs
├── web/
│   ├── __init__.py
│   ├── main.py                             # FastAPI app, all routes (public + admin)
│   ├── auth.py                             # HTTP Basic Auth dependency
│   ├── input.css                           # Tailwind source (@tailwind directives)
│   ├── static/
│   │   └── styles.css                      # Built by Tailwind CLI (gitignored, generated at build)
│   └── templates/
│       ├── base.html                       # Shared layout, nav, CSS link
│       ├── public/
│       │   ├── index.html                  # Tabbed collections, prediction cards
│       │   └── _prediction_detail.html     # HTMX partial: summary, sources, history
│       └── admin/
│           ├── index.html                  # Prediction list + action buttons
│           ├── _investigate_btn.html       # HTMX partial: button → "Queued"
│           ├── _bulk_result.html           # HTMX partial: "N jobs queued"
│           └── _seed_result.html           # HTMX partial: "X added, Y skipped"
└── tests/
    ├── conftest.py                         # DB fixtures (real Postgres test DB)
    ├── test_models.py                      # CRUD for all models
    ├── test_investigator.py                # Mocked OpenAI calls
    ├── test_scheduler.py                   # Mocked OpenAI calls + validation logic
    ├── test_worker.py                      # Poll loop with test DB (Postgres-specific)
    ├── test_web_public.py                  # Public routes via TestClient
    └── test_web_admin.py                   # Admin routes via TestClient (auth + HTMX)
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `db/__init__.py`, `agents/__init__.py`, `worker/__init__.py`, `web/__init__.py`
- Create: `web/static/.gitkeep`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "hindsightbot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg2-binary>=2.9",
    "openai>=1.50",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "httpx>=0.27",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.env.example`**

```
# Database (Railway provides DATABASE_URL automatically)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot

# For tests
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test

# OpenAI
OPENAI_API_KEY=sk-...

# Admin panel (HTTP Basic Auth)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme

# Worker poll interval in seconds (default: 300)
WORKER_POLL_INTERVAL_SECONDS=300
```

- [ ] **Step 3: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
.env
.venv/
tailwindcss
web/static/styles.css
*.egg-info/
.pytest_cache/
```

- [ ] **Step 4: Create empty `__init__.py` files and directory structure**

```bash
mkdir -p db/migrations/versions agents worker web/templates/public web/templates/admin web/static scripts tests
touch db/__init__.py agents/__init__.py worker/__init__.py web/__init__.py tests/__init__.py
touch web/static/.gitkeep
```

- [ ] **Step 5: Install dependencies**

```bash
uv sync
```

Expected: Lockfile created, `.venv/` directory created.

- [ ] **Step 6: Verify Python import works**

```bash
uv run python -c "import fastapi, sqlalchemy, openai; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .env.example .gitignore db/ agents/ worker/ web/ tests/ scripts/
git commit -m "feat: project scaffolding with uv, FastAPI, SQLAlchemy, OpenAI"
```

---

## Task 2: Database Models

**Files:**
- Create: `db/session.py`
- Create: `db/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write `db/session.py`**

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    """FastAPI dependency: yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: Write `db/models.py`**

```python
import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Enum as SAEnum, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class VerdictStatus(str, enum.Enum):
    UNRESOLVED = "unresolved"
    CAME_TRUE = "came_true"
    CAME_FALSE = "came_false"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    predictions = relationship("Prediction", back_populates="collection")


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_predictions_status_next_check_at", "status", "next_check_at"),
    )

    id = Column(Integer, primary_key=True)
    collection_id = Column(Integer, ForeignKey("collections.id"), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(
        SAEnum(VerdictStatus, name="verdict_status"),
        default=VerdictStatus.UNRESOLVED,
        nullable=False,
    )
    summary = Column(Text)
    next_check_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    collection = relationship("Collection", back_populates="predictions")
    investigations = relationship("Investigation", back_populates="prediction", order_by="Investigation.investigated_at.desc()")
    jobs = relationship("Job", back_populates="prediction")


class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), nullable=False)
    verdict = Column(SAEnum(VerdictStatus, name="verdict_status"), nullable=False)
    summary = Column(Text)
    investigated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    prediction = relationship("Prediction", back_populates="investigations")
    sources = relationship("Source", back_populates="investigation")


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    url = Column(Text, nullable=False)
    title = Column(String(500))
    relevance_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    investigation = relationship("Investigation", back_populates="sources")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), nullable=False)
    status = Column(
        SAEnum(JobStatus, name="job_status"),
        default=JobStatus.PENDING,
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)

    prediction = relationship("Prediction", back_populates="jobs")
```

- [ ] **Step 3: Write `tests/conftest.py`**

Requires a running Postgres instance. Set `TEST_DATABASE_URL` in your environment before running tests.

```python
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/hindsightbot_test",
)


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(test_engine):
    """Yields a session that rolls back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

- [ ] **Step 4: Write failing tests in `tests/test_models.py`**

```python
from datetime import datetime, timedelta
from db.models import Collection, Prediction, Investigation, Source, Job, VerdictStatus, JobStatus


def test_create_collection(db):
    col = Collection(name="AI Daily Brief 2026", description="50 predictions")
    db.add(col)
    db.flush()
    assert col.id is not None
    assert col.created_at is not None


def test_create_prediction(db):
    col = Collection(name="Test Collection")
    db.add(col)
    db.flush()

    pred = Prediction(collection_id=col.id, text="AI will do X by 2026")
    db.add(pred)
    db.flush()

    assert pred.id is not None
    assert pred.status == VerdictStatus.UNRESOLVED
    assert pred.summary is None
    assert pred.next_check_at is None


def test_create_investigation_with_sources(db):
    col = Collection(name="Test")
    db.add(col)
    db.flush()

    pred = Prediction(collection_id=col.id, text="Some prediction")
    db.add(pred)
    db.flush()

    inv = Investigation(
        prediction_id=pred.id,
        verdict=VerdictStatus.CAME_TRUE,
        summary="Evidence shows this came true.",
    )
    db.add(inv)
    db.flush()

    source = Source(
        investigation_id=inv.id,
        url="https://example.com/article",
        title="Example Article",
        relevance_summary="Directly confirms the prediction.",
    )
    db.add(source)
    db.flush()

    assert len(inv.sources) == 1
    assert inv.sources[0].url == "https://example.com/article"


def test_create_job(db):
    col = Collection(name="Test")
    db.add(col)
    db.flush()

    pred = Prediction(collection_id=col.id, text="Some prediction")
    db.add(pred)
    db.flush()

    job = Job(prediction_id=pred.id)
    db.add(job)
    db.flush()

    assert job.status == JobStatus.PENDING
    assert job.started_at is None
    assert job.error_message is None


def test_prediction_status_update(db):
    col = Collection(name="Test")
    db.add(col)
    db.flush()

    pred = Prediction(collection_id=col.id, text="Some prediction")
    db.add(pred)
    db.flush()

    pred.status = VerdictStatus.CAME_TRUE
    pred.summary = "It came true."
    db.flush()

    db.refresh(pred)
    assert pred.status == VerdictStatus.CAME_TRUE
```

- [ ] **Step 5: Run tests — expect them to fail (no DB yet)**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_models.py -v
```

Expected: FAIL with connection error (DB doesn't exist yet) or import error.

- [ ] **Step 6: Create the test database**

```bash
createdb hindsightbot_test
```

- [ ] **Step 7: Run tests again — expect PASS**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_models.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add db/session.py db/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: SQLAlchemy models for all entities with indexes"
```

---

## Task 3: Alembic Migrations

**Files:**
- Create: `alembic.ini`
- Create: `db/migrations/env.py`
- Create: `db/migrations/script.py.mako`
- Create: `db/migrations/versions/001_initial_schema.py`

- [ ] **Step 1: Initialize Alembic**

```bash
uv run alembic init db/migrations
```

This creates `alembic.ini` and `db/migrations/`. We'll customize both.

- [ ] **Step 2: Update `alembic.ini`**

Change the `script_location` line:
```ini
script_location = db/migrations
```

Leave `sqlalchemy.url` blank — we override it in `env.py` from the environment.

- [ ] **Step 3: Replace `db/migrations/env.py`**

```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    return os.environ["DATABASE_URL"]


def run_migrations_offline():
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Generate initial migration**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run alembic revision --autogenerate -m "initial_schema"
```

Expected: Creates `db/migrations/versions/<hash>_initial_schema.py` with all tables.

- [ ] **Step 5: Rename the migration file for clarity**

Rename the generated file to `db/migrations/versions/001_initial_schema.py`. Update the `Revision ID` and `down_revision` at the top if needed (they're auto-set; just rename the file).

- [ ] **Step 6: Apply migration to test DB**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run alembic upgrade head
```

Expected: `Running upgrade  -> <hash>, initial_schema`

- [ ] **Step 7: Verify tables exist**

```bash
psql hindsightbot_test -c "\dt"
```

Expected: `collections`, `predictions`, `investigations`, `sources`, `jobs`, `alembic_version` tables.

- [ ] **Step 8: Create dev database and apply migration**

```bash
createdb hindsightbot
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot uv run alembic upgrade head
```

- [ ] **Step 9: Commit**

```bash
git add alembic.ini db/migrations/
git commit -m "feat: Alembic migration setup with initial schema"
```

---

## Task 4: Investigator Agent

**Files:**
- Create: `agents/investigator.py`
- Create: `tests/test_investigator.py`

The Investigator uses a two-step approach:
1. **Step A (OpenAI Responses API + web_search_preview):** gather evidence as free text
2. **Step B (Chat Completions + JSON mode):** extract structured verdict/summary/sources from the research text

This makes each step independently testable by mocking.

- [ ] **Step 1: Write failing tests in `tests/test_investigator.py`**

```python
from unittest.mock import patch, MagicMock
from agents.investigator import investigate, InvestigationResult


FAKE_RESEARCH = """
Based on web search results, OpenAI released GPT-5 in January 2026.
Source 1: https://openai.com/blog/gpt5 - "GPT-5 launched"
Source 2: https://techcrunch.com/gpt5 - "OpenAI's newest model"
"""

FAKE_EXTRACTION = {
    "verdict": "came_true",
    "summary": "GPT-5 was released in January 2026 as confirmed by multiple sources.",
    "sources": [
        {
            "url": "https://openai.com/blog/gpt5",
            "title": "GPT-5 launched",
            "relevance_summary": "Official OpenAI announcement confirming the release.",
        },
        {
            "url": "https://techcrunch.com/gpt5",
            "title": "OpenAI's newest model",
            "relevance_summary": "Independent coverage of the GPT-5 launch.",
        },
    ],
}


def test_investigate_returns_result():
    with patch("agents.investigator._search_web", return_value=FAKE_RESEARCH), \
         patch("agents.investigator._extract_structured", return_value=FAKE_EXTRACTION):
        result = investigate(
            prediction_text="OpenAI will release GPT-5 by mid-2026",
            collection_name="AI Daily Brief 2026",
        )

    assert isinstance(result, InvestigationResult)
    assert result.verdict == "came_true"
    assert len(result.sources) == 2
    assert result.sources[0]["url"] == "https://openai.com/blog/gpt5"


def test_investigate_validates_verdict():
    bad_extraction = {**FAKE_EXTRACTION, "verdict": "definitely_true"}  # invalid
    with patch("agents.investigator._search_web", return_value=FAKE_RESEARCH), \
         patch("agents.investigator._extract_structured", return_value=bad_extraction):
        result = investigate(
            prediction_text="Some prediction",
            collection_name="AI Daily Brief 2026",
        )
    assert result.verdict == "unresolved"  # fallback on invalid verdict


def test_investigate_caps_sources():
    many_sources = FAKE_EXTRACTION.copy()
    many_sources["sources"] = [
        {"url": f"https://example.com/{i}", "title": f"Article {i}", "relevance_summary": "Relevant."}
        for i in range(10)
    ]
    with patch("agents.investigator._search_web", return_value=FAKE_RESEARCH), \
         patch("agents.investigator._extract_structured", return_value=many_sources):
        result = investigate(
            prediction_text="Some prediction",
            collection_name="Test",
        )
    assert len(result.sources) <= 5
```

- [ ] **Step 2: Run tests — expect FAIL (module not found)**

```bash
uv run pytest tests/test_investigator.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.investigator'`

- [ ] **Step 3: Write `agents/investigator.py`**

```python
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

VALID_VERDICTS = {"unresolved", "came_true", "came_false"}
MAX_SOURCES = 5
MAX_RETRIES = 3

client = OpenAI()


@dataclass
class InvestigationResult:
    verdict: str
    summary: str
    sources: list[dict[str, str]] = field(default_factory=list)


def investigate(prediction_text: str, collection_name: str) -> InvestigationResult:
    """Run the full investigation pipeline with retries."""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            research = _search_web(prediction_text, collection_name)
            extraction = _extract_structured(prediction_text, research)
            return _build_result(extraction)
        except Exception as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning("Investigator attempt %d failed: %s — retrying in %ds", attempt + 1, exc, wait)
            time.sleep(wait)

    raise RuntimeError(f"Investigator failed after {MAX_RETRIES} attempts") from last_error


def _search_web(prediction_text: str, collection_name: str) -> str:
    """Use OpenAI Responses API with web_search_preview to gather evidence."""
    prompt = (
        f"You are fact-checking a prediction from '{collection_name}'.\n\n"
        f"PREDICTION: <<< {prediction_text} >>>\n\n"
        "Search the web to find current evidence for or against this prediction. "
        "Gather information from 3-5 reliable sources. "
        "Report what you find, including source URLs and titles."
    )

    response = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=[{"role": "user", "content": prompt}],
    )

    # Extract the text output from the response
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text":
                    return content.text

    raise ValueError("No text output from web search response")


def _extract_structured(prediction_text: str, research_text: str) -> dict[str, Any]:
    """Use Chat Completions with JSON mode to extract structured verdict from research."""
    system = (
        "You extract structured fact-check results from research text. "
        "Return valid JSON with exactly these fields:\n"
        '- "verdict": one of "came_true", "came_false", "unresolved"\n'
        '- "summary": 1-2 sentence explanation of your verdict\n'
        '- "sources": array of up to 5 objects, each with "url", "title", "relevance_summary" (1-2 sentences)\n\n'
        "Only return JSON, no other text."
    )
    user = (
        f"PREDICTION: <<< {prediction_text} >>>\n\n"
        f"RESEARCH FINDINGS:\n{research_text}\n\n"
        "Extract the structured verdict."
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    return json.loads(response.choices[0].message.content)


def _build_result(extraction: dict[str, Any]) -> InvestigationResult:
    """Validate and build InvestigationResult from extracted dict."""
    verdict = extraction.get("verdict", "unresolved")
    if verdict not in VALID_VERDICTS:
        logger.warning("Invalid verdict '%s' from extraction — defaulting to unresolved", verdict)
        verdict = "unresolved"

    summary = extraction.get("summary", "No summary available.")
    sources = extraction.get("sources", [])[:MAX_SOURCES]

    return InvestigationResult(verdict=verdict, summary=summary, sources=sources)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_investigator.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/investigator.py tests/test_investigator.py
git commit -m "feat: Investigator agent with two-step web search + structured extraction"
```

---

## Task 5: Scheduler Agent

**Files:**
- Create: `agents/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests in `tests/test_scheduler.py`**

```python
from unittest.mock import patch
from datetime import datetime, timedelta
from agents.scheduler import schedule_next_check, ScheduleResult


def make_mock_response(content: str):
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.choices[0].message.content = content
    return mock


def test_schedule_returns_result():
    mock_resp = make_mock_response('{"value": 2, "unit": "months"}')
    with patch("agents.scheduler.client.chat.completions.create", return_value=mock_resp):
        result = schedule_next_check(
            prediction_text="AI will surpass human performance in 2026",
            investigation_summary="Still unresolved as of March 2026.",
        )
    assert isinstance(result, ScheduleResult)
    assert result.value == 2
    assert result.unit == "months"
    # next_check_at should be ~2 months from now
    assert result.next_check_at > datetime.utcnow() + timedelta(days=55)


def test_schedule_defaults_on_invalid_unit():
    mock_resp = make_mock_response('{"value": 5, "unit": "years"}')
    with patch("agents.scheduler.client.chat.completions.create", return_value=mock_resp):
        result = schedule_next_check("Some prediction", "Some summary")
    assert result.value == 30
    assert result.unit == "days"


def test_schedule_defaults_on_out_of_range_value():
    mock_resp = make_mock_response('{"value": 500, "unit": "days"}')
    with patch("agents.scheduler.client.chat.completions.create", return_value=mock_resp):
        result = schedule_next_check("Some prediction", "Some summary")
    assert result.value == 30
    assert result.unit == "days"


def test_schedule_defaults_on_malformed_json():
    mock_resp = make_mock_response("not json at all")
    with patch("agents.scheduler.client.chat.completions.create", return_value=mock_resp):
        result = schedule_next_check("Some prediction", "Some summary")
    assert result.value == 30
    assert result.unit == "days"


def test_schedule_retries_on_api_error():
    from openai import APIError
    import httpx
    # Fail twice, succeed on third attempt
    mock_resp = make_mock_response('{"value": 7, "unit": "days"}')
    api_error = APIError("rate limit", request=MagicMock(), body=None)

    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise api_error
        return mock_resp

    with patch("agents.scheduler.client.chat.completions.create", side_effect=side_effect), \
         patch("agents.scheduler.time.sleep"):  # don't actually sleep in tests
        result = schedule_next_check("Some prediction", "Some summary")

    assert result.value == 7
    assert call_count == 3
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.scheduler'`

- [ ] **Step 3: Write `agents/scheduler.py`**

```python
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from openai import OpenAI

logger = logging.getLogger(__name__)

VALID_UNITS = {"days", "weeks", "months"}
DEFAULT_INTERVAL = {"value": 30, "unit": "days"}
MAX_VALUE = 365
MIN_VALUE = 1
MAX_RETRIES = 3

client = OpenAI()


@dataclass
class ScheduleResult:
    value: int
    unit: str
    next_check_at: datetime


def schedule_next_check(prediction_text: str, investigation_summary: str) -> ScheduleResult:
    """Ask the LLM when to next re-investigate an unresolved prediction."""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            raw = _call_llm(prediction_text, investigation_summary)
            return _parse_and_validate(raw)
        except Exception as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning("Scheduler attempt %d failed: %s — retrying in %ds", attempt + 1, exc, wait)
            time.sleep(wait)

    logger.warning("Scheduler failed after %d attempts — using default interval. Error: %s", MAX_RETRIES, last_error)
    return _build_result(DEFAULT_INTERVAL)


def _call_llm(prediction_text: str, investigation_summary: str) -> str:
    system = (
        "You decide when to re-investigate unresolved predictions. "
        "Return JSON with exactly two fields:\n"
        '- "value": integer between 1 and 365\n'
        '- "unit": one of "days", "weeks", "months"\n\n'
        "Consider: when is the predicted event supposed to occur? "
        "How much time needs to pass before new evidence is likely? "
        "Only return JSON."
    )
    user = (
        f"PREDICTION: {prediction_text}\n\n"
        f"LATEST INVESTIGATION: {investigation_summary}\n\n"
        "When should we check again?"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content


def _parse_and_validate(raw: str) -> ScheduleResult:
    try:
        data = json.loads(raw)
        value = int(data.get("value", 0))
        unit = str(data.get("unit", ""))
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("Scheduler returned malformed JSON — using default")
        return _build_result(DEFAULT_INTERVAL)

    if unit not in VALID_UNITS or not (MIN_VALUE <= value <= MAX_VALUE):
        logger.warning("Scheduler returned invalid interval %d %s — using default", value, unit)
        return _build_result(DEFAULT_INTERVAL)

    return _build_result({"value": value, "unit": unit})


def _build_result(interval: dict) -> ScheduleResult:
    value, unit = interval["value"], interval["unit"]
    if unit == "days":
        delta = timedelta(days=value)
    elif unit == "weeks":
        delta = timedelta(weeks=value)
    else:  # months — approximate
        delta = timedelta(days=value * 30)
    return ScheduleResult(value=value, unit=unit, next_check_at=datetime.utcnow() + delta)
```

- [ ] **Step 4: Fix the missing `MagicMock` import in the test file**

Add to the top of `tests/test_scheduler.py`:
```python
from unittest.mock import patch, MagicMock
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/scheduler.py tests/test_scheduler.py
git commit -m "feat: Scheduler agent with validation and fallback defaults"
```

---

## Task 6: Worker Poll Loop

**Files:**
- Create: `worker/main.py`
- Create: `tests/test_worker.py`

The worker's poll cycle:
1. Reset stuck jobs (running > 30 min → pending)
2. Convert elapsed `next_check_at` unresolved predictions → new pending jobs
3. Claim and process pending jobs (atomic SELECT FOR UPDATE SKIP LOCKED)

- [ ] **Step 1: Write failing tests in `tests/test_worker.py`**

```python
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytest
from db.models import Collection, Prediction, Job, JobStatus, VerdictStatus
from worker.main import (
    reset_stuck_jobs,
    promote_due_predictions,
    claim_next_job,
    process_job,
)


@pytest.fixture
def collection(db):
    col = Collection(name="Test", description="")
    db.add(col)
    db.flush()
    return col


@pytest.fixture
def prediction(db, collection):
    pred = Prediction(collection_id=collection.id, text="AI will do X")
    db.add(pred)
    db.flush()
    return pred


def test_reset_stuck_jobs(db, prediction):
    job = Job(
        prediction_id=prediction.id,
        status=JobStatus.RUNNING,
        started_at=datetime.utcnow() - timedelta(minutes=35),
    )
    db.add(job)
    db.flush()

    reset_count = reset_stuck_jobs(db)

    db.refresh(job)
    assert job.status == JobStatus.PENDING
    assert reset_count == 1


def test_reset_does_not_affect_recent_running_jobs(db, prediction):
    job = Job(
        prediction_id=prediction.id,
        status=JobStatus.RUNNING,
        started_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db.add(job)
    db.flush()

    reset_count = reset_stuck_jobs(db)

    db.refresh(job)
    assert job.status == JobStatus.RUNNING
    assert reset_count == 0


def test_promote_due_predictions(db, prediction):
    prediction.status = VerdictStatus.UNRESOLVED
    prediction.next_check_at = datetime.utcnow() - timedelta(hours=1)
    db.flush()

    count = promote_due_predictions(db)

    assert count == 1
    job = db.query(Job).filter_by(prediction_id=prediction.id).one()
    assert job.status == JobStatus.PENDING


def test_promote_skips_already_queued(db, prediction):
    prediction.status = VerdictStatus.UNRESOLVED
    prediction.next_check_at = datetime.utcnow() - timedelta(hours=1)
    db.add(Job(prediction_id=prediction.id, status=JobStatus.PENDING))
    db.flush()

    count = promote_due_predictions(db)

    assert count == 0
    jobs = db.query(Job).filter_by(prediction_id=prediction.id).all()
    assert len(jobs) == 1  # no duplicate created


def test_promote_skips_future_predictions(db, prediction):
    prediction.status = VerdictStatus.UNRESOLVED
    prediction.next_check_at = datetime.utcnow() + timedelta(days=7)
    db.flush()

    count = promote_due_predictions(db)

    assert count == 0


def test_process_job_success(db, collection, prediction):
    job = Job(prediction_id=prediction.id)
    db.add(job)
    db.flush()

    mock_result = MagicMock()
    mock_result.verdict = "came_true"
    mock_result.summary = "It came true."
    mock_result.sources = [{"url": "https://a.com", "title": "A", "relevance_summary": "Confirms it."}]

    mock_schedule = MagicMock()
    mock_schedule.next_check_at = datetime.utcnow() + timedelta(days=30)

    with patch("worker.main.investigate", return_value=mock_result), \
         patch("worker.main.schedule_next_check", return_value=mock_schedule):
        process_job(db, job)

    db.refresh(job)
    db.refresh(prediction)

    assert job.status == JobStatus.DONE
    assert prediction.status == VerdictStatus.CAME_TRUE
    assert prediction.summary == "It came true."


def test_process_job_failure(db, prediction):
    job = Job(prediction_id=prediction.id)
    db.add(job)
    db.flush()

    with patch("worker.main.investigate", side_effect=RuntimeError("API down")):
        process_job(db, job)

    db.refresh(job)
    db.refresh(prediction)

    assert job.status == JobStatus.FAILED
    assert "API down" in job.error_message
    assert prediction.status == VerdictStatus.UNRESOLVED  # not changed
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_worker.py -v
```

Expected: `ModuleNotFoundError: No module named 'worker.main'`

- [ ] **Step 3: Write `worker/main.py`**

```python
import logging
import os
import time
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, not_, exists, select
from sqlalchemy.orm import Session

from agents.investigator import investigate
from agents.scheduler import schedule_next_check
from db.models import (
    Collection, Prediction, Investigation, Source, Job,
    VerdictStatus, JobStatus,
)
from db.session import SessionLocal

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

STUCK_JOB_THRESHOLD_MINUTES = 30
POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "300"))


# --- Poll cycle steps ---

def reset_stuck_jobs(db: Session) -> int:
    """Reset running jobs that started more than STUCK_JOB_THRESHOLD_MINUTES ago."""
    cutoff = datetime.utcnow() - timedelta(minutes=STUCK_JOB_THRESHOLD_MINUTES)
    stuck = (
        db.query(Job)
        .filter(Job.status == JobStatus.RUNNING, Job.started_at < cutoff)
        .all()
    )
    for job in stuck:
        job.status = JobStatus.PENDING
        job.started_at = None
    db.commit()
    if stuck:
        logger.info("Reset %d stuck jobs", len(stuck))
    return len(stuck)


def promote_due_predictions(db: Session) -> int:
    """Create pending jobs for unresolved predictions whose next_check_at has elapsed."""
    now = datetime.utcnow()

    # Subquery: predictions that already have a pending or running job
    already_queued = (
        db.query(Job.prediction_id)
        .filter(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .subquery()
    )

    due = (
        db.query(Prediction)
        .filter(
            Prediction.status == VerdictStatus.UNRESOLVED,
            Prediction.next_check_at <= now,
            ~Prediction.id.in_(already_queued),
        )
        .all()
    )

    for pred in due:
        db.add(Job(prediction_id=pred.id))
    db.commit()

    if due:
        logger.info("Promoted %d predictions to pending jobs", len(due))
    return len(due)


def claim_next_job(db: Session) -> Job | None:
    """Atomically claim the next pending job using SELECT FOR UPDATE SKIP LOCKED."""
    job = (
        db.query(Job)
        .filter(Job.status == JobStatus.PENDING)
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return None

    job.status = JobStatus.RUNNING
    job.started_at = datetime.utcnow()
    db.commit()
    return job


def process_job(db: Session, job: Job) -> None:
    """Run investigation + scheduling for a job. Updates DB on success or failure."""
    pred = db.query(Prediction).join(Collection).filter(Prediction.id == job.prediction_id).one()
    collection = pred.collection

    try:
        result = investigate(
            prediction_text=pred.text,
            collection_name=collection.name,
        )

        # Write investigation + sources + update prediction — all in one transaction
        inv = Investigation(
            prediction_id=pred.id,
            verdict=VerdictStatus(result.verdict),
            summary=result.summary,
        )
        db.add(inv)
        db.flush()  # get inv.id

        for src in result.sources:
            db.add(Source(
                investigation_id=inv.id,
                url=src.get("url", ""),
                title=src.get("title", ""),
                relevance_summary=src.get("relevance_summary", ""),
            ))

        pred.status = VerdictStatus(result.verdict)
        pred.summary = result.summary
        pred.updated_at = datetime.utcnow()

        job.status = JobStatus.DONE
        job.completed_at = datetime.utcnow()

        db.commit()
        logger.info("Job %d: prediction %d → %s", job.id, pred.id, result.verdict)

        # Schedule next check if still unresolved
        if result.verdict == "unresolved":
            schedule_result = schedule_next_check(
                prediction_text=pred.text,
                investigation_summary=result.summary,
            )
            pred.next_check_at = schedule_result.next_check_at
            db.commit()
            logger.info(
                "Job %d: next check in %d %s at %s",
                job.id, schedule_result.value, schedule_result.unit, schedule_result.next_check_at,
            )

    except Exception as exc:
        db.rollback()
        job.status = JobStatus.FAILED
        job.completed_at = datetime.utcnow()
        job.error_message = str(exc)
        db.commit()
        logger.error("Job %d failed: %s", job.id, exc)


# --- Main poll loop ---

def run_poll_cycle(db: Session) -> None:
    reset_stuck_jobs(db)
    promote_due_predictions(db)

    while True:
        job = claim_next_job(db)
        if job is None:
            break
        process_job(db, job)


def main():
    logger.info("Worker starting, poll interval=%ds", POLL_INTERVAL)
    while True:
        with SessionLocal() as db:
            try:
                run_poll_cycle(db)
            except Exception as exc:
                logger.error("Poll cycle error: %s", exc)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Fix `SessionLocal` to support context manager**

Update `db/session.py` to use `sessionmaker` with `autocommit=False`:

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_worker.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add worker/main.py db/session.py tests/test_worker.py
git commit -m "feat: worker poll loop with stuck-job reset, promotion, and atomic job claiming"
```

---

## Task 7: Web — Public Routes

**Files:**
- Create: `web/main.py` (public routes only)
- Create: `web/templates/base.html`
- Create: `web/templates/public/index.html`
- Create: `web/templates/public/_prediction_detail.html`
- Create: `tests/test_web_public.py`

- [ ] **Step 1: Write failing tests in `tests/test_web_public.py`**

```python
import pytest
from fastapi.testclient import TestClient
from db.models import Collection, Prediction, Investigation, Source, VerdictStatus
from web.main import app


@pytest.fixture
def client(db, monkeypatch):
    """TestClient with DB session overridden to use test DB."""
    from web.main import app
    from db.session import get_db

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.fixture
def seeded_data(db):
    col = Collection(name="AI Daily Brief 2026", description="50 predictions")
    db.add(col)
    db.flush()

    pred1 = Prediction(
        collection_id=col.id,
        text="AI will achieve AGI by 2026",
        status=VerdictStatus.UNRESOLVED,
    )
    pred2 = Prediction(
        collection_id=col.id,
        text="GPT-5 will be released",
        status=VerdictStatus.CAME_TRUE,
        summary="GPT-5 was released in early 2026.",
    )
    db.add_all([pred1, pred2])
    db.flush()

    inv = Investigation(
        prediction_id=pred2.id,
        verdict=VerdictStatus.CAME_TRUE,
        summary="GPT-5 was released in early 2026.",
    )
    db.add(inv)
    db.flush()

    src = Source(
        investigation_id=inv.id,
        url="https://openai.com/gpt5",
        title="GPT-5 Launch",
        relevance_summary="Official announcement.",
    )
    db.add(src)
    db.commit()
    return col, pred1, pred2


def test_index_returns_200(client, seeded_data):
    response = client.get("/")
    assert response.status_code == 200


def test_index_shows_collection_name(client, seeded_data):
    response = client.get("/")
    assert "AI Daily Brief 2026" in response.text


def test_index_shows_predictions(client, seeded_data):
    response = client.get("/")
    assert "GPT-5 will be released" in response.text


def test_prediction_detail_htmx_partial(client, seeded_data):
    _, _, pred2 = seeded_data
    response = client.get(f"/predictions/{pred2.id}/detail")
    assert response.status_code == 200
    assert "GPT-5 was released in early 2026" in response.text
    assert "https://openai.com/gpt5" in response.text


def test_prediction_detail_404_for_unknown(client, seeded_data):
    response = client.get("/predictions/99999/detail")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_web_public.py -v
```

Expected: `ModuleNotFoundError: No module named 'web.main'`

- [ ] **Step 3: Write `web/main.py` (public routes)**

```python
import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from db.models import Collection, Prediction, Investigation
from db.session import get_db

app = FastAPI(title="HindsightBot")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    collections = db.query(Collection).order_by(Collection.created_at).all()
    return templates.TemplateResponse(
        "public/index.html",
        {"request": request, "collections": collections},
    )


@app.get("/predictions/{prediction_id}/detail", response_class=HTMLResponse)
def prediction_detail(prediction_id: int, request: Request, db: Session = Depends(get_db)):
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if pred is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return templates.TemplateResponse(
        "public/_prediction_detail.html",
        {"request": request, "prediction": pred},
    )
```

- [ ] **Step 4: Write `web/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}HindsightBot{% endblock %}</title>
    <link rel="stylesheet" href="/static/styles.css">
    <script src="https://unpkg.com/htmx.org@1.9.12" defer></script>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen">
    {% block content %}{% endblock %}
</body>
</html>
```

**Note:** HTMX itself is loaded from CDN (this is JS only, not CSS — acceptable). Tailwind CSS is served locally.

- [ ] **Step 5: Write `web/templates/public/index.html`**

```html
{% extends "base.html" %}
{% block title %}HindsightBot — Predictions{% endblock %}
{% block content %}
<header class="bg-white border-b border-gray-200 px-6 py-5">
    <h1 class="text-2xl font-bold tracking-tight">HindsightBot</h1>
    <p class="text-sm text-gray-500 mt-1">Tracking whether AI predictions came true.</p>
</header>

<main class="max-w-4xl mx-auto px-4 py-8">
    {% for collection in collections %}
    <section class="mb-12">
        <h2 class="text-xl font-semibold mb-1">{{ collection.name }}</h2>
        {% if collection.description %}
        <p class="text-sm text-gray-500 mb-4">{{ collection.description }}</p>
        {% endif %}

        <div class="space-y-3">
            {% for pred in collection.predictions %}
            <div class="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
                <div
                    class="flex items-start justify-between gap-4 p-4 cursor-pointer hover:bg-gray-50 transition-colors"
                    hx-get="/predictions/{{ pred.id }}/detail"
                    hx-target="#detail-{{ pred.id }}"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                >
                    <p class="text-sm font-medium text-gray-800 flex-1">{{ pred.text }}</p>
                    <span class="shrink-0 text-xs font-semibold px-2.5 py-1 rounded-full
                        {% if pred.status.value == 'came_true' %}bg-green-100 text-green-700
                        {% elif pred.status.value == 'came_false' %}bg-red-100 text-red-700
                        {% else %}bg-yellow-100 text-yellow-700{% endif %}">
                        {% if pred.status.value == 'came_true' %}Came True
                        {% elif pred.status.value == 'came_false' %}Came False
                        {% else %}Unresolved{% endif %}
                    </span>
                </div>
                <div id="detail-{{ pred.id }}"></div>
            </div>
            {% endfor %}
        </div>
    </section>
    {% endfor %}
</main>
{% endblock %}
```

- [ ] **Step 6: Write `web/templates/public/_prediction_detail.html`**

```html
<div class="border-t border-gray-100 px-4 py-4 bg-gray-50 text-sm space-y-4">
    {% if prediction.summary %}
    <p class="text-gray-700">{{ prediction.summary }}</p>
    {% endif %}

    {% if prediction.investigations %}
    {% set latest = prediction.investigations[0] %}
    {% if latest.sources %}
    <div>
        <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Sources</h4>
        <ul class="space-y-2">
            {% for source in latest.sources %}
            <li class="flex flex-col">
                <a href="{{ source.url }}" target="_blank" rel="noopener"
                   class="text-blue-600 hover:underline font-medium text-sm">{{ source.title or source.url }}</a>
                <span class="text-gray-500 text-xs mt-0.5">{{ source.relevance_summary }}</span>
            </li>
            {% endfor %}
        </ul>
    </div>
    {% endif %}

    <div>
        <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Investigation History</h4>
        <ul class="space-y-1">
            {% for inv in prediction.investigations %}
            <li class="flex items-center gap-2 text-xs text-gray-600">
                <span class="font-medium
                    {% if inv.verdict.value == 'came_true' %}text-green-600
                    {% elif inv.verdict.value == 'came_false' %}text-red-600
                    {% else %}text-yellow-600{% endif %}">
                    {% if inv.verdict.value == 'came_true' %}Came True
                    {% elif inv.verdict.value == 'came_false' %}Came False
                    {% else %}Unresolved{% endif %}
                </span>
                <span class="text-gray-400">·</span>
                <span>{{ inv.investigated_at.strftime('%b %d, %Y') }}</span>
            </li>
            {% endfor %}
        </ul>
    </div>
    {% endif %}

    {% if prediction.status.value == 'unresolved' and prediction.next_check_at %}
    <p class="text-xs text-gray-400">Next check: ~{{ prediction.next_check_at.strftime('%b %d, %Y') }}</p>
    {% endif %}
</div>
```

- [ ] **Step 7: Create placeholder `web/static/styles.css` for tests**

```bash
touch web/static/styles.css
```

- [ ] **Step 8: Run tests — expect PASS**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_web_public.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add web/main.py web/templates/ web/static/.gitkeep tests/test_web_public.py
git commit -m "feat: public web routes with HTMX prediction detail expand"
```

---

## Task 8: Web — Admin Routes

**Files:**
- Create: `web/auth.py`
- Modify: `web/main.py` (add admin routes)
- Create: `web/templates/admin/index.html`
- Create: `web/templates/admin/_investigate_btn.html`
- Create: `web/templates/admin/_bulk_result.html`
- Create: `web/templates/admin/_seed_result.html`
- Create: `tests/test_web_admin.py`

- [ ] **Step 1: Write failing tests in `tests/test_web_admin.py`**

```python
import base64
import pytest
from fastapi.testclient import TestClient
from db.models import Collection, Prediction, Job, JobStatus, VerdictStatus
from web.main import app
from db.session import get_db


ADMIN_USER = "admin"
ADMIN_PASS = "testpass"


def auth_headers():
    creds = base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASS}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture(autouse=True)
def set_admin_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def seeded(db):
    col = Collection(name="Test Collection", description="")
    db.add(col)
    db.flush()
    pred = Prediction(collection_id=col.id, text="Some prediction", status=VerdictStatus.UNRESOLVED)
    db.add(pred)
    db.commit()
    return col, pred


def test_admin_requires_auth(client):
    response = client.get("/admin")
    assert response.status_code == 401


def test_admin_accessible_with_auth(client, seeded):
    response = client.get("/admin", headers=auth_headers())
    assert response.status_code == 200


def test_investigate_now_creates_job(client, db, seeded):
    col, pred = seeded
    response = client.post(
        f"/admin/predictions/{pred.id}/investigate",
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert "Queued" in response.text

    job = db.query(Job).filter_by(prediction_id=pred.id).one()
    assert job.status == JobStatus.PENDING


def test_investigate_now_noop_if_already_queued(client, db, seeded):
    col, pred = seeded
    db.add(Job(prediction_id=pred.id, status=JobStatus.PENDING))
    db.commit()

    response = client.post(
        f"/admin/predictions/{pred.id}/investigate",
        headers=auth_headers(),
    )
    assert response.status_code == 200
    jobs = db.query(Job).filter_by(prediction_id=pred.id).all()
    assert len(jobs) == 1  # no duplicate


def test_investigate_all_unresolved(client, db, seeded):
    col, pred = seeded
    response = client.post("/admin/investigate-all", headers=auth_headers())
    assert response.status_code == 200
    assert "1 job" in response.text

    job = db.query(Job).filter_by(prediction_id=pred.id).one()
    assert job.status == JobStatus.PENDING


def test_seed_predictions(client, db, seeded):
    col, _ = seeded
    response = client.post(
        "/admin/seed",
        data={
            "collection_id": str(col.id),
            "predictions_text": "First new prediction\nSecond new prediction\nThird new prediction",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert "3 added" in response.text

    preds = db.query(Prediction).filter_by(collection_id=col.id).all()
    assert len(preds) == 4  # 1 original + 3 new


def test_seed_deduplicates(client, db, seeded):
    col, pred = seeded
    response = client.post(
        "/admin/seed",
        data={
            "collection_id": str(col.id),
            "predictions_text": "Some prediction\nBrand new prediction",
        },
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert "1 added" in response.text
    assert "1 skipped" in response.text
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_web_admin.py -v
```

Expected: FAIL (no admin routes yet)

- [ ] **Step 3: Write `web/auth.py`**

```python
import os
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "")

    correct_user = secrets.compare_digest(credentials.username.encode(), username.encode())
    correct_pass = secrets.compare_digest(credentials.password.encode(), password.encode())

    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
```

- [ ] **Step 4: Add admin routes to `web/main.py`**

Replace the import block at the top of `web/main.py` with the full updated version, then append the admin route functions below the existing public routes:

```python
# --- Top of web/main.py (full import block) ---
import os
import unicodedata
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from db.models import Collection, Prediction, Investigation, Job, VerdictStatus, JobStatus
from db.session import get_db
from web.auth import require_admin
```

Then append the admin route functions after the existing public routes:


def _normalize_text(text: str) -> str:
    """Lowercase, strip, and collapse whitespace for dedup comparison."""
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


@app.get("/admin", response_class=HTMLResponse)
def admin_index(
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    collections = db.query(Collection).order_by(Collection.created_at).all()
    predictions = db.query(Prediction).order_by(Prediction.collection_id, Prediction.id).all()
    return templates.TemplateResponse(
        "admin/index.html",
        {"request": request, "collections": collections, "predictions": predictions},
    )


@app.post("/admin/predictions/{prediction_id}/investigate", response_class=HTMLResponse)
def admin_investigate_now(
    prediction_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if pred is None:
        raise HTTPException(status_code=404)

    existing = (
        db.query(Job)
        .filter(
            Job.prediction_id == prediction_id,
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .first()
    )
    if existing is None:
        db.add(Job(prediction_id=prediction_id))
        db.commit()

    return templates.TemplateResponse(
        "admin/_investigate_btn.html",
        {"request": request, "prediction_id": prediction_id, "queued": True},
    )


@app.post("/admin/investigate-all", response_class=HTMLResponse)
def admin_investigate_all(
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    already_queued_ids = (
        db.query(Job.prediction_id)
        .filter(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .subquery()
    )
    due = (
        db.query(Prediction)
        .filter(
            Prediction.status == VerdictStatus.UNRESOLVED,
            ~Prediction.id.in_(already_queued_ids),
        )
        .all()
    )
    for pred in due:
        db.add(Job(prediction_id=pred.id))
    db.commit()

    return templates.TemplateResponse(
        "admin/_bulk_result.html",
        {"request": request, "count": len(due)},
    )


@app.post("/admin/seed", response_class=HTMLResponse)
def admin_seed(
    request: Request,
    collection_id: int = Form(...),
    predictions_text: str = Form(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if collection is None:
        raise HTTPException(status_code=404)

    # Existing predictions in this collection (normalized for dedup)
    existing_normalized = {
        _normalize_text(p.text)
        for p in db.query(Prediction).filter(Prediction.collection_id == collection_id).all()
    }

    lines = [line.strip() for line in predictions_text.splitlines() if line.strip()]
    added, skipped = 0, 0

    for line in lines:
        if _normalize_text(line) in existing_normalized:
            skipped += 1
        else:
            db.add(Prediction(collection_id=collection_id, text=line))
            existing_normalized.add(_normalize_text(line))
            added += 1

    db.commit()

    return templates.TemplateResponse(
        "admin/_seed_result.html",
        {"request": request, "added": added, "skipped": skipped},
    )


@app.post("/admin/collections", response_class=HTMLResponse)
def admin_create_collection(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    db.add(Collection(name=name.strip(), description=description.strip() or None))
    db.commit()
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin", status_code=303)
```

- [ ] **Step 5: Write admin templates**

`web/templates/admin/index.html`:
```html
{% extends "base.html" %}
{% block title %}Admin — HindsightBot{% endblock %}
{% block content %}
<div style="padding: 1rem; font-family: monospace;">
    <h1>HindsightBot Admin</h1>
    <hr>

    <h2>New Collection</h2>
    <form method="post" action="/admin/collections">
        <input type="text" name="name" placeholder="Collection name" required>
        <input type="text" name="description" placeholder="Description (optional)">
        <button type="submit">Create Collection</button>
    </form>

    <hr>
    <h2>Seed Predictions</h2>
    <form hx-post="/admin/seed" hx-target="#seed-result" hx-swap="innerHTML">
        <label>Collection:
            <select name="collection_id">
                {% for col in collections %}
                <option value="{{ col.id }}">{{ col.name }}</option>
                {% endfor %}
            </select>
        </label>
        <br><br>
        <label>Predictions (one per line):<br>
            <textarea name="predictions_text" rows="8" cols="60"></textarea>
        </label>
        <br>
        <button type="submit">Seed</button>
        <span id="seed-result"></span>
    </form>

    <hr>
    <h2>Investigations</h2>
    <button hx-post="/admin/investigate-all" hx-target="#bulk-result" hx-swap="innerHTML">
        Investigate All Unresolved
    </button>
    <span id="bulk-result"></span>
    <br><br>

    <table border="1" cellpadding="4">
        <thead>
            <tr>
                <th>ID</th><th>Collection</th><th>Text</th><th>Status</th>
                <th>Next Check</th><th>Action</th>
            </tr>
        </thead>
        <tbody>
            {% for pred in predictions %}
            <tr>
                <td>{{ pred.id }}</td>
                <td>{{ pred.collection.name }}</td>
                <td style="max-width:300px">{{ pred.text[:80] }}{% if pred.text|length > 80 %}…{% endif %}</td>
                <td>{{ pred.status.value }}</td>
                <td>{{ pred.next_check_at.strftime('%Y-%m-%d') if pred.next_check_at else '—' }}</td>
                <td>
                    <span id="btn-{{ pred.id }}">
                        <button hx-post="/admin/predictions/{{ pred.id }}/investigate"
                                hx-target="#btn-{{ pred.id }}"
                                hx-swap="innerHTML">
                            Investigate Now
                        </button>
                    </span>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

`web/templates/admin/_investigate_btn.html`:
```html
<button disabled>Queued</button>
```

`web/templates/admin/_bulk_result.html`:
```html
<span>{{ count }} job{% if count != 1 %}s{% endif %} queued.</span>
```

`web/templates/admin/_seed_result.html`:
```html
<span>{{ added }} added, {{ skipped }} skipped as duplicates.</span>
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest tests/test_web_admin.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 7: Run full test suite**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest -v
```

Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add web/auth.py web/main.py web/templates/admin/ tests/test_web_admin.py
git commit -m "feat: admin routes with Basic Auth, investigate triggers, and prediction seeder"
```

---

## Task 9: Tailwind CSS Build

**Files:**
- Create: `web/input.css`
- Create: `tailwind.config.js`
- Create: `scripts/download_tailwind.sh`
- Modify: `web/static/styles.css` (generated, not committed)

- [ ] **Step 1: Write `web/input.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 2: Write `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./web/templates/**/*.html",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

- [ ] **Step 3: Write `scripts/download_tailwind.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

VERSION="v3.4.1"
BINARY_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/tailwindcss-linux-x64"
OUTPUT="./tailwindcss"

echo "Downloading Tailwind CSS ${VERSION} (linux/amd64)..."
curl -fsSL "$BINARY_URL" -o "$OUTPUT"
chmod +x "$OUTPUT"
echo "Tailwind CSS downloaded to $OUTPUT"
```

- [ ] **Step 4: Download the binary locally (for development)**

```bash
bash scripts/download_tailwind.sh
```

Expected: `./tailwindcss` binary appears in project root.

- [ ] **Step 5: Build CSS**

```bash
./tailwindcss -i web/input.css -o web/static/styles.css --minify
```

Expected: `web/static/styles.css` created with minified Tailwind output.

- [ ] **Step 6: Verify `styles.css` is non-empty**

```bash
wc -c web/static/styles.css
```

Expected: Several kilobytes (Tailwind base + utilities used in templates).

- [ ] **Step 7: Update `.gitignore` to exclude the generated CSS but keep `.gitkeep`**

Verify `.gitignore` already contains `web/static/styles.css`. It should from Task 1.

- [ ] **Step 8: Start the dev server and visually verify the public UI**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot \
ADMIN_USERNAME=admin \
ADMIN_PASSWORD=admin \
uv run uvicorn web.main:app --reload
```

Open `http://localhost:8000` and verify the public page looks styled.

- [ ] **Step 9: Commit**

```bash
git add web/input.css tailwind.config.js scripts/download_tailwind.sh
git commit -m "feat: Tailwind CSS v3 standalone build pipeline"
```

---

## Task 10: Railway Deployment Config

**Files:**
- Create: `railway.toml`

- [ ] **Step 1: Write `railway.toml`**

```toml
[build]
builder = "nixpacks"

[[services]]
name = "web"

[services.build]
buildCommand = "uv sync && bash scripts/download_tailwind.sh && ./tailwindcss -i web/input.css -o web/static/styles.css --minify"
releaseCommand = "uv run alembic upgrade head"

[services.deploy]
startCommand = "uvicorn web.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/"
healthcheckTimeout = 30

[[services]]
name = "worker"

[services.build]
buildCommand = "uv sync"

[services.deploy]
startCommand = "python worker/main.py"
```

- [ ] **Step 2: Verify `railway.toml` is valid TOML**

```bash
python3 -c "import tomllib; tomllib.loads(open('railway.toml').read()); print('Valid TOML')"
```

Expected: `Valid TOML`

- [ ] **Step 3: Add health check endpoint to `web/main.py`**

```python
@app.get("/health")
def health():
    return {"status": "ok"}
```

Update `railway.toml` to use `/health` as the healthcheck path:
```toml
healthcheckPath = "/health"
```

- [ ] **Step 4: Final full test run**

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hindsightbot_test uv run pytest -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add railway.toml web/main.py
git commit -m "feat: Railway multi-service deployment config with health check"
```

---

## Deployment Checklist

After pushing to GitHub and connecting to Railway:

- [ ] Create Railway project, add Postgres plugin
- [ ] Set env vars on both services: `OPENAI_API_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`
- [ ] Deploy — Railway auto-sets `DATABASE_URL` from the Postgres plugin
- [ ] Navigate to `/admin`, create "AI Daily Brief — 50 Predictions for 2026" collection
- [ ] Paste the 50 predictions from the YouTube video transcripts into the seeder form
- [ ] Click "Investigate All Unresolved" to begin the first investigation run
- [ ] Monitor worker logs in Railway dashboard
