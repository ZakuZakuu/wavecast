"""artists the listener asked to hear less of

Revision ID: 0008_avoid_artists
Revises: 0007_episode_generation_jobs
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_avoid_artists"
down_revision = "0007_episode_generation_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "avoid_artists",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "avoid_artists")
