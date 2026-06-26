"""rename enterprise_archana_bookings to archana_bookings

Revision ID: a9f1e2d3c4b5
Revises: baef2bfd7714
Create Date: 2026-06-25 19:32:00.000000

Drops the legacy enterprise_ prefix from the primary archana booking table.
The canonical model class is now ArchanaBooking; EnterpriseArchanaBooking is a
backward-compat alias and will be removed in a future cleanup pass.
"""
from alembic import op

revision = 'a9f1e2d3c4b5'
down_revision = 'baef2bfd7714'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0. Drop the legacy empty table if it exists
    op.execute("DROP TABLE IF EXISTS archana_bookings CASCADE")

    # 1. Rename the primary table
    op.rename_table('enterprise_archana_bookings', 'archana_bookings')

    # 2. Rename indexes (PostgreSQL keeps old table name in generated index names)
    for old, new in [
        ('ix_enterprise_archana_bookings_idempotency_key', 'ix_archana_bookings_idempotency_key'),
        ('ix_enterprise_archana_bookings_ref_id',          'ix_archana_bookings_ref_id'),
        ('ix_enterprise_archana_bookings_temple_id',       'ix_archana_bookings_temple_id'),
    ]:
        op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")

    # 3. Rename FK constraints on child tables so they match the new parent name
    #    (PostgreSQL does NOT automatically rename FK constraints on RENAME TABLE)
    fk_renames = [
        ('archana_booking_members',   'archana_booking_members_booking_id_fkey'),
        ('archana_booking_payments',  'archana_booking_payments_booking_id_fkey'),
        ('ritual_queue',              'ritual_queue_booking_id_fkey'),
        ('archana_booking_audit',     'archana_booking_audit_booking_id_fkey'),
        ('archana_refunds',           'archana_refunds_booking_id_fkey'),
        ('online_settlement_ledger',  'online_settlement_ledger_booking_id_fkey'),
    ]
    for table, old_fk in fk_renames:
        new_fk = old_fk.replace('enterprise_', '')
        if old_fk != new_fk:
            op.execute(
                f"DO $$ BEGIN "
                f"  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{old_fk}') THEN "
                f"    ALTER TABLE {table} RENAME CONSTRAINT {old_fk} TO {new_fk}; "
                f"  END IF; "
                f"END $$;"
            )


def downgrade() -> None:
    op.rename_table('archana_bookings', 'enterprise_archana_bookings')

    for old, new in [
        ('ix_archana_bookings_idempotency_key', 'ix_enterprise_archana_bookings_idempotency_key'),
        ('ix_archana_bookings_ref_id',          'ix_enterprise_archana_bookings_ref_id'),
        ('ix_archana_bookings_temple_id',       'ix_enterprise_archana_bookings_temple_id'),
    ]:
        op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")
