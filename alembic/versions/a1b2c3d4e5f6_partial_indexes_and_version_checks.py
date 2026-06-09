"""Add partial indexes and version check constraints

Revision ID: a1b2c3d4e5f6
Revises: fddf3e83bce9
Create Date: 2026-04-17 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fddf3e83bce9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add partial indexes for active-only queries and CHECK constraints for version fields."""

    # ── PARTIAL INDEXES ──────────────────────────────────────────────
    # These replace full-table scans with targeted indexes on active records only.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_active_only ON users(id) WHERE is_active = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_temples_active_only ON temples(id) WHERE is_active = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_temples_active_only ON user_temples(id) WHERE is_active = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_carts_active_only ON carts(id) WHERE is_active = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_addresses_active_only ON addresses(id) WHERE is_active = TRUE"
    )

    # ── VERSION CHECK CONSTRAINTS ────────────────────────────────────
    # Enforce version >= 1 at the database level.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            'ALTER TABLE temples ADD CONSTRAINT ck_temples_version_min CHECK (version >= 1)'
        )
        op.execute(
            'ALTER TABLE employees ADD CONSTRAINT ck_employees_version_min CHECK (version >= 1)'
        )
        op.execute(
            'ALTER TABLE halls ADD CONSTRAINT ck_halls_version_min CHECK (version >= 1)'
        )
        op.execute(
            'ALTER TABLE inventory_items ADD CONSTRAINT ck_inventory_items_version_min CHECK (version >= 1)'
        )


def downgrade() -> None:
    """Remove partial indexes and version constraints."""

    # Drop CHECK constraints
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE inventory_items DROP CONSTRAINT IF EXISTS ck_inventory_items_version_min')
        op.execute('ALTER TABLE halls DROP CONSTRAINT IF EXISTS ck_halls_version_min')
        op.execute('ALTER TABLE employees DROP CONSTRAINT IF EXISTS ck_employees_version_min')
        op.execute('ALTER TABLE temples DROP CONSTRAINT IF EXISTS ck_temples_version_min')

    # Drop partial indexes
    op.execute('DROP INDEX IF EXISTS ix_addresses_active_only')
    op.execute('DROP INDEX IF EXISTS ix_carts_active_only')
    op.execute('DROP INDEX IF EXISTS ix_user_temples_active_only')
    op.execute('DROP INDEX IF EXISTS ix_temples_active_only')
    op.execute('DROP INDEX IF EXISTS ix_users_active_only')
