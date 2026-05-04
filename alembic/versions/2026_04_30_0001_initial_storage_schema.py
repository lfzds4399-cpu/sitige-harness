"""initial storage schema — Run / Stage / Finding / CostEntry / User / AuditLog.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pipeline", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("triggered_by", sa.String(32), nullable=False, server_default="cli"),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_runs_pipeline", "runs", ["pipeline"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_pipeline_status", "runs", ["pipeline", "status"])

    op.create_table(
        "stages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("input", sa.JSON, nullable=True),
        sa.Column("output", sa.JSON, nullable=True),
        sa.Column(
            "findings_count_error", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "findings_count_warn", sa.Integer, nullable=False, server_default="0"
        ),
    )
    op.create_index("ix_stages_run_id", "stages", ["run_id"])

    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stage_id",
            sa.String(36),
            sa.ForeignKey("stages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("validator", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("file", sa.String(255), nullable=True),
        sa.Column("line", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_findings_run_id", "findings", ["run_id"])
    op.create_index("ix_findings_stage_id", "findings", ["stage_id"])
    op.create_index("ix_findings_validator", "findings", ["validator"])
    op.create_index("ix_findings_severity", "findings", ["severity"])

    op.create_table(
        "cost_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stage_id",
            sa.String(36),
            sa.ForeignKey("stages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_cost_entries_run_id", "cost_entries", ["run_id"])
    op.create_index("ix_cost_entries_stage_id", "cost_entries", ["stage_id"])
    op.create_index("ix_cost_entries_occurred_at", "cost_entries", ["occurred_at"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(128), nullable=True),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("occurred_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("cost_entries")
    op.drop_table("findings")
    op.drop_table("stages")
    op.drop_table("runs")
