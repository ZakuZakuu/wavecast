"""persist generated program proposals

Revision ID: 0002_program_proposals
Revises: 0001_episode_runtime
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_program_proposals"
down_revision = "0001_episode_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_proposals",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("owner_listener_id", sa.String(length=128), nullable=True),
        sa.Column("owner_user_id", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_program_proposals_owner_listener_id",
        "program_proposals",
        ["owner_listener_id"],
    )
    op.create_index(
        "ix_program_proposals_owner_user_id", "program_proposals", ["owner_user_id"]
    )
    op.create_index("ix_program_proposals_created_at", "program_proposals", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_program_proposals_created_at", table_name="program_proposals")
    op.drop_index("ix_program_proposals_owner_user_id", table_name="program_proposals")
    op.drop_index("ix_program_proposals_owner_listener_id", table_name="program_proposals")
    op.drop_table("program_proposals")
