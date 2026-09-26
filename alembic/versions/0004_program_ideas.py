"""persist personalized program ideas

Revision ID: 0004_program_ideas
Revises: 0003_user_context
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_program_ideas"
down_revision = "0003_user_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_ideas",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index(
        "ix_program_ideas_user_id_created_at",
        "program_ideas",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_program_ideas_user_id_created_at", table_name="program_ideas")
    op.drop_table("program_ideas")
