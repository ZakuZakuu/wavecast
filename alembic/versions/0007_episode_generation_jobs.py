"""durable episode generation jobs for buffered streaming runtime v2

Revision ID: 0007_episode_generation_jobs
Revises: 0006_quota_reservation_expiry
Create Date: 2026-09-27
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_episode_generation_jobs"
down_revision = "0006_quota_reservation_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "episode_generation_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("episode_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("request_version", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_episode_generation_jobs_ready",
        "episode_generation_jobs",
        ["status", "available_at", "requested_at"],
    )
    op.create_index(
        "ix_episode_generation_jobs_lease",
        "episode_generation_jobs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_episode_generation_jobs_lease",
        table_name="episode_generation_jobs",
    )
    op.drop_index(
        "ix_episode_generation_jobs_ready",
        table_name="episode_generation_jobs",
    )
    op.drop_table("episode_generation_jobs")
