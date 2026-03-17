"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-17

"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TYPE verdict_status AS ENUM ('unresolved', 'came_true', 'came_false')")
    op.execute("CREATE TYPE job_status AS ENUM ('pending', 'running', 'done', 'failed')")

    op.create_table(
        "collections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("collection_id", sa.Integer, sa.ForeignKey("collections.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("status", sa.Enum("unresolved", "came_true", "came_false", name="verdict_status", create_type=False), nullable=False, server_default="unresolved"),
        sa.Column("summary", sa.Text),
        sa.Column("next_check_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_predictions_status_next_check_at", "predictions", ["status", "next_check_at"])

    op.create_table(
        "investigations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prediction_id", sa.Integer, sa.ForeignKey("predictions.id"), nullable=False),
        sa.Column("verdict", sa.Enum("unresolved", "came_true", "came_false", name="verdict_status", create_type=False), nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("investigated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("investigation_id", sa.Integer, sa.ForeignKey("investigations.id"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("relevance_summary", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prediction_id", sa.Integer, sa.ForeignKey("predictions.id"), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "done", "failed", name="job_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("error_message", sa.Text),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade():
    op.drop_table("jobs")
    op.drop_table("sources")
    op.drop_table("investigations")
    op.drop_table("predictions")
    op.drop_table("collections")
    op.execute("DROP TYPE IF EXISTS verdict_status")
    op.execute("DROP TYPE IF EXISTS job_status")
