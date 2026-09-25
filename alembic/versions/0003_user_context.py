"""persist user preferences and product events

Revision ID: 0003_user_context
Revises: 0002_program_proposals
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_user_context"
down_revision = "0002_program_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(length=128), primary_key=True),
        sa.Column("genres", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artists", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("moods", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contexts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("discovery_level", sa.String(length=32), nullable=False),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_events",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("program_id", sa.String(length=128), nullable=True),
        sa.Column("episode_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_user_events_user_id_occurred_at",
        "user_events",
        ["user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_events_user_id_occurred_at", table_name="user_events")
    op.drop_table("user_events")
    op.drop_table("user_preferences")
