"""persist durable episode runtime

Revision ID: 0001_episode_runtime
Revises:
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_episode_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "episodes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("listener_id", sa.String(length=128), nullable=False),
        sa.Column("seed_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("listener_id", "seed_id", name="uq_episodes_listener_seed"),
    )


def downgrade() -> None:
    op.drop_table("episodes")
