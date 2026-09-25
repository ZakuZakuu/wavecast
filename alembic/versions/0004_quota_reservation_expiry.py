"""expire abandoned dynamic-program quota reservations

Revision ID: 0004_quota_reservation_expiry
Revises: 0003_cloud_library_quota
Create Date: 2026-09-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_quota_reservation_expiry"
down_revision = "0003_cloud_library_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_quota_reservations",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE generation_quota_reservations "
        "SET expires_at = created_at + INTERVAL '15 minutes'"
    )
    op.alter_column("generation_quota_reservations", "expires_at", nullable=False)
    op.create_index(
        "ix_generation_quota_status_expiry",
        "generation_quota_reservations",
        ["status", "expires_at"],
    )
