"""Add AI invocation audit and artifact tables

Revision ID: 003
Revises: 04122962d333
Create Date: 2026-04-12

Tables:
  - ai_invocations: audit log for every Gemini call
  - ai_artifacts: normalized AI outputs with optional GCS URI
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str = "04122962d333"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("ai_invocations"):
        op.create_table(
            "ai_invocations",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("request_id", sa.String(24), nullable=False),
            sa.Column("purpose", sa.String(64), nullable=False),
            sa.Column("model", sa.String(64), nullable=False),
            sa.Column("prompt_hash", sa.String(64), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("store_id", sa.UUID(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_ai_invocations_request_id"),
            "ai_invocations",
            ["request_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_ai_invocations_store_id"),
            "ai_invocations",
            ["store_id"],
            unique=False,
        )

    if not inspector.has_table("ai_artifacts"):
        op.create_table(
            "ai_artifacts",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("invocation_id", sa.UUID(), nullable=True),
            sa.Column("store_id", sa.UUID(), nullable=True),
            sa.Column("artifact_type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="completed"),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("gcs_uri", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_ai_artifacts_artifact_type"),
            "ai_artifacts",
            ["artifact_type"],
            unique=False,
        )
        op.create_index(
            op.f("ix_ai_artifacts_invocation_id"),
            "ai_artifacts",
            ["invocation_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_ai_artifacts_store_id"),
            "ai_artifacts",
            ["store_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("ai_artifacts"):
        op.drop_index(op.f("ix_ai_artifacts_store_id"), table_name="ai_artifacts")
        op.drop_index(op.f("ix_ai_artifacts_invocation_id"), table_name="ai_artifacts")
        op.drop_index(op.f("ix_ai_artifacts_artifact_type"), table_name="ai_artifacts")
        op.drop_table("ai_artifacts")

    if inspector.has_table("ai_invocations"):
        op.drop_index(op.f("ix_ai_invocations_store_id"), table_name="ai_invocations")
        op.drop_index(op.f("ix_ai_invocations_request_id"), table_name="ai_invocations")
        op.drop_table("ai_invocations")
