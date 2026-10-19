"""published programmes and their listeners

Revision ID: 0009_published_programmes
Revises: 0008_avoid_artists
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_published_programmes"
down_revision = "0008_avoid_artists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "published_programmes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False, unique=True),
        sa.Column("source_episode_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("owner_listener_id", sa.String(length=128), nullable=False),
        sa.Column("owner_user_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("programme", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("asset_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("audio_seconds", sa.Float(), nullable=False),
        sa.Column("plan_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_published_programmes_owner_user", "published_programmes", ["owner_user_id"])
    op.create_index(
        "ix_published_programmes_owner_listener", "published_programmes", ["owner_listener_id"],
    )
    op.create_index(
        "ix_published_programmes_status_visibility",
        "published_programmes",
        ["status", "visibility", "published_at"],
    )
    op.create_table(
        "programme_listens",
        sa.Column(
            "publication_id", sa.String(length=64),
            sa.ForeignKey("published_programmes.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("listener_key", sa.String(length=160), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("programme_listens")
    op.drop_index("ix_published_programmes_status_visibility", table_name="published_programmes")
    op.drop_index("ix_published_programmes_owner_listener", table_name="published_programmes")
    op.drop_index("ix_published_programmes_owner_user", table_name="published_programmes")
    op.drop_table("published_programmes")
