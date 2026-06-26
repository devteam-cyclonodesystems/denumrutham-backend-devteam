"""add ACKNOWLEDGED to queuestatus enum

Revision ID: f1a2b3c4d5e6
Revises: 30e7e1a9f69a
Create Date: 2026-06-26 13:25:00.000000

Root Cause Fix:
    The queuestatus PostgreSQL enum was missing the ACKNOWLEDGED value,
    causing InvalidTextRepresentationError on all /archana-bookings/queue
    and /archana-bookings API calls (500 DATABASE_ERROR).

    The Python QueueStatus enum has ACKNOWLEDGED but it was never added
    to the DB enum via a migration.
"""
from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '30e7e1a9f69a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ACKNOWLEDGED to the queuestatus enum (idempotent)."""
    # PostgreSQL ALTER TYPE ... ADD VALUE is idempotent with IF NOT EXISTS (PG 9.6+)
    op.execute("ALTER TYPE queuestatus ADD VALUE IF NOT EXISTS 'ACKNOWLEDGED' AFTER 'WAITING'")


def downgrade() -> None:
    """
    PostgreSQL does not support removing enum values without recreating the type.
    A no-op downgrade is acceptable here.
    """
    pass
