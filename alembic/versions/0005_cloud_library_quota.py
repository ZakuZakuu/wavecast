"""account library, durable ownership, and generation quota reservations

Revision ID: 0005_cloud_library_quota
Revises: 0004_program_ideas
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_cloud_library_quota"
down_revision = "0004_program_ideas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("owner_user_id", sa.String(length=128), nullable=True))
    op.create_index("ix_episodes_owner_user_id", "episodes", ["owner_user_id"])
    op.create_index(
        "uq_episodes_owner_user_seed", "episodes", ["owner_user_id", "seed_id"],
        unique=True, postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_table(
        "user_library_entries",
        sa.Column("user_id", sa.String(length=128), primary_key=True),
        sa.Column("kind", sa.String(length=16), primary_key=True),
        sa.Column("resource_id", sa.String(length=128), primary_key=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_library_user_kind_updated", "user_library_entries", ["user_id", "kind", "updated_at"])
    op.create_table(
        "generation_quota_reservations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("listener_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("program_id", sa.String(length=128), nullable=True, unique=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_generation_quota_guest", "generation_quota_reservations", ["listener_id", "status"])
    op.create_index("ix_generation_quota_user_day", "generation_quota_reservations", ["user_id", "created_at", "status"])
    op.create_index("ix_generation_quota_global_day", "generation_quota_reservations", ["created_at", "status"])


def downgrade() -> None:
    op.drop_index("ix_generation_quota_global_day", table_name="generation_quota_reservations")
    op.drop_index("ix_generation_quota_user_day", table_name="generation_quota_reservations")
    op.drop_index("ix_generation_quota_guest", table_name="generation_quota_reservations")
    op.drop_table("generation_quota_reservations")
    op.drop_index("ix_user_library_user_kind_updated", table_name="user_library_entries")
    op.drop_table("user_library_entries")
    op.drop_index("uq_episodes_owner_user_seed", table_name="episodes")
    op.drop_index("ix_episodes_owner_user_id", table_name="episodes")
    op.drop_column("episodes", "owner_user_id")
