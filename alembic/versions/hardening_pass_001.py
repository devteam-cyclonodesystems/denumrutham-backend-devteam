"""Hardening Pass - Security and Data Integrity

Revision ID: hardening_pass_001
Revises: fddf3e83bce9
Create Date: 2026-04-23 10:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'hardening_pass_001'
down_revision: Union[str, Sequence[str], None] = '5e097ab473a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. Ensure tables exist (they might be missing from previous migrations)
    # TempleDomainHistory
    op.execute("""
        CREATE TABLE IF NOT EXISTS temple_domain_history (
            id UUID PRIMARY KEY,
            temple_id UUID NOT NULL REFERENCES temples(id) ON DELETE CASCADE,
            old_domain VARCHAR NOT NULL,
            new_domain VARCHAR NOT NULL,
            changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    
    # StaffInvite
    op.execute("""
        CREATE TABLE IF NOT EXISTS staff_invites (
            id UUID PRIMARY KEY,
            temple_id UUID NOT NULL REFERENCES temples(id) ON DELETE CASCADE,
            email VARCHAR NOT NULL,
            token VARCHAR NOT NULL UNIQUE,
            role VARCHAR DEFAULT 'STAFF',
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            created_by UUID REFERENCES users(id)
        )
    """)

    # 1. Invite Token Replay Protection
    op.add_column('staff_invites', sa.Column('is_used', sa.Boolean(), server_default='false', nullable=False))
    op.execute("UPDATE staff_invites SET is_used = TRUE WHERE used_at IS NOT NULL")

    # 2. Soft Delete + Unique Constraint Conflict (Temples)
    # Drop existing unique constraint on domain
    # Name is usually 'temples_domain_key' in Postgres
    op.drop_constraint('temples_domain_key', 'temples', type_='unique')
    
    # Create partial unique index
    op.create_index(
        'unique_active_domain', 
        'temples', 
        ['domain'], 
        unique=True, 
        postgresql_where=sa.text('deleted_at IS NULL')
    )

    # 3. Domain History Lookup Index
    # Ensure it's named idx_domain_history_old_domain as requested
    op.create_index('idx_domain_history_old_domain', 'temple_domain_history', ['old_domain'], unique=False)

    # 4. RLS Enablement (MANDATORY FIX #4)
    tenant_tables = [
        'users', 'user_temples', 'devotees', 'poojas', 'events', 'tickets', 
        'approval_requests', 'notifications', 'temple_profiles', 'temple_images', 
        'temple_services', 'halls', 'employees', 'transactions', 'archana_bookings', 
        'suppliers', 'inventory_invoices', 'inventory_item_requests', 'change_requests', 
        'temple_followers', 'carts', 'roles', 'permissions', 'pooja_slots', 
        'bookings', 'donations', 'inventory_items', 'audit_logs', 'service_bookings', 
        'hall_bookings', 'leaves', 'guest_bookings', 'user_roles', 
        'inventory_movements', 'payments', 'inventory_transactions'
    ]

    for table in tenant_tables:
        # Enable RLS
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # Drop if exists for idempotency
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}")
        # Create Policy: Match temple_id OR is SUPER_ADMIN
        op.execute(f"""
            CREATE POLICY tenant_isolation_policy ON {table}
            USING (
                temple_id::text = current_setting('app.current_temple_id', true) 
                OR current_setting('app.current_role', true) = 'SUPER_ADMIN'
            )
        """)

    # Special case for 'temples' table (id instead of temple_id)
    op.execute("ALTER TABLE temples ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON temples")
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON temples
        USING (
            id::text = current_setting('app.current_temple_id', true) 
            OR current_setting('app.current_role', true) = 'SUPER_ADMIN'
        )
    """)


def downgrade() -> None:
    # 3. Remove Domain History Index
    op.drop_index('idx_domain_history_old_domain', table_name='temple_domain_history')

    # 2. Revert Temple Domain Constraint
    op.drop_index('unique_active_domain', table_name='temples', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_unique_constraint('temples_domain_key', 'temples', ['domain'])

    # 1. Remove is_used from staff_invites
    op.drop_column('staff_invites', 'is_used')
