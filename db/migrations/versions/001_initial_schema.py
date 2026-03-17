"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

verdict_status = ENUM("unresolved", "came_true", "came_false", name="verdict_status", create_type=False)
job_status = ENUM("pending", "running", "done", "failed", name="job_status", create_type=False)


def upgrade():
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE verdict_status AS ENUM ('unresolved', 'came_true', 'came_false');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE job_status AS ENUM ('pending', 'running', 'done', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id SERIAL PRIMARY KEY,
            collection_id INTEGER NOT NULL REFERENCES collections(id),
            text TEXT NOT NULL,
            status verdict_status NOT NULL DEFAULT 'unresolved',
            summary TEXT,
            next_check_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_predictions_status_next_check_at ON predictions (status, next_check_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS investigations (
            id SERIAL PRIMARY KEY,
            prediction_id INTEGER NOT NULL REFERENCES predictions(id),
            verdict verdict_status NOT NULL,
            summary TEXT,
            investigated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id SERIAL PRIMARY KEY,
            investigation_id INTEGER NOT NULL REFERENCES investigations(id),
            url TEXT NOT NULL,
            title VARCHAR(500),
            relevance_summary TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            prediction_id INTEGER NOT NULL REFERENCES predictions(id),
            status job_status NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status)")


def downgrade():
    op.drop_table("jobs")
    op.drop_table("sources")
    op.drop_table("investigations")
    op.drop_table("predictions")
    op.drop_table("collections")
    op.execute("DROP TYPE IF EXISTS verdict_status")
    op.execute("DROP TYPE IF EXISTS job_status")
