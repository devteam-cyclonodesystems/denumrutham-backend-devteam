"""fix_rls_superadmin_mismatch

Revision ID: 20c869c223e0
Revises: 6dfc4490a13a
Create Date: 2026-05-03 18:39:24.762425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20c869c223e0'
down_revision: Union[str, Sequence[str], None] = '6dfc4490a13a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation_policy ON {table}
            USING (
                temple_id::text = current_setting('app.current_temple_id', true) 
                OR current_setting('app.current_role', true) IN ('SUPERADMIN', 'SUPER_ADMIN')
            )
        """)

    # Temples table (id instead of temple_id)
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON temples")
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON temples
        USING (
            id::text = current_setting('app.current_temple_id', true) 
            OR current_setting('app.current_role', true) IN ('SUPERADMIN', 'SUPER_ADMIN')
            OR current_setting('app.current_role', true) = 'GUEST'
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
