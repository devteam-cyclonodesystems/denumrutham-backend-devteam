"""Add structured accounts payable and payment ledger

Revision ID: hardening_pass_004_procurement_ledger
Revises: hardening_pass_003_extend_price_approvals
Create Date: 2026-05-30 18:00:00.000000

"""
from typing import Sequence, Union
import re
import uuid
from uuid import UUID
from datetime import datetime
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'hardening_pass_004_procurement_ledger'
down_revision: Union[str, Sequence[str], None] = 'hardening_pass_003_extend_price_approvals'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def column_exists(table_name, column_name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = insp.get_columns(table_name)
    return any(c['name'] == column_name for c in columns)

def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'

    # 1. Create inventory_payment_transactions table
    op.create_table(
        'inventory_payment_transactions',
        sa.Column('id', sa.UUID(), nullable=False, primary_key=True),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('payment_method', sa.String(), nullable=False),
        sa.Column('payment_reference', sa.String(), nullable=True),
        sa.Column('transaction_status', sa.String(), nullable=False, server_default='COMPLETED'),
        sa.Column('payment_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['inventory_invoices.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.CheckConstraint("amount > 0", name="chk_payment_amount_positive"),
        sa.CheckConstraint("payment_method IN ('CASH', 'UPI', 'CARD', 'BANK_TRANSFER', 'CHEQUE')", name="chk_payment_method_enum"),
        sa.CheckConstraint("transaction_status IN ('COMPLETED', 'REVERSED', 'VOIDED')", name="chk_transaction_status_enum")
    )

    # 2. Add columns to inventory_invoices
    if not column_exists('inventory_invoices', 'supplier_id'):
        op.add_column('inventory_invoices', sa.Column('supplier_id', sa.UUID(), nullable=True))
    if not column_exists('inventory_invoices', 'payment_status'):
        op.add_column('inventory_invoices', sa.Column('payment_status', sa.String(), nullable=True))
    if not column_exists('inventory_invoices', 'total_paid_amount'):
        op.add_column('inventory_invoices', sa.Column('total_paid_amount', sa.Numeric(18, 2), nullable=True))
    if not column_exists('inventory_invoices', 'balance_due'):
        op.add_column('inventory_invoices', sa.Column('balance_due', sa.Numeric(18, 2), nullable=True))
    if not column_exists('inventory_invoices', 'last_payment_date'):
        op.add_column('inventory_invoices', sa.Column('last_payment_date', sa.DateTime(timezone=True), nullable=True))
    if not column_exists('inventory_invoices', 'payment_completed_at'):
        op.add_column('inventory_invoices', sa.Column('payment_completed_at', sa.DateTime(timezone=True), nullable=True))
    if not column_exists('inventory_invoices', 'is_deleted'):
        op.add_column('inventory_invoices', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0'))
    if not column_exists('inventory_invoices', 'deleted_at'):
        op.add_column('inventory_invoices', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    if not column_exists('inventory_invoices', 'deleted_by'):
        op.add_column('inventory_invoices', sa.Column('deleted_by', sa.UUID(), nullable=True))
    if not column_exists('inventory_invoices', 'created_by_user_id'):
        op.add_column('inventory_invoices', sa.Column('created_by_user_id', sa.UUID(), nullable=True))

    # Add constraints on non-sqlite databases
    if not is_sqlite:
        op.create_check_constraint("chk_invoice_balance_due_positive", "inventory_invoices", "balance_due >= 0")
        op.create_check_constraint("chk_payment_status_enum", "inventory_invoices", "payment_status IN ('FULL_PAYMENT', 'PARTIAL_PAYMENT', 'PAY_LATER')")
        op.create_foreign_key(
            'fk_inventory_invoices_created_by_user_id_users',
            'inventory_invoices', 'users',
            ['created_by_user_id'], ['id']
        )

    # 3. Data Migration and Backfill
    # Query current invoices
    connection = op.get_bind()
    metadata = sa.MetaData()
    invoices_table = sa.Table('inventory_invoices', metadata, autoload_with=connection)
    suppliers_table = sa.Table('suppliers', metadata, autoload_with=connection)
    payment_txs_table = sa.Table('inventory_payment_transactions', metadata, autoload_with=connection)

    invoices = connection.execute(sa.select(invoices_table)).fetchall()
    suppliers = connection.execute(sa.select(suppliers_table)).fetchall()

    supplier_map = {s.name.upper(): s.id for s in suppliers}

    for inv in invoices:
        # Check if remarks contains legacy payment block
        remarks = inv.remarks or ""
        payment_status = "PAY_LATER"
        total_paid_amount = 0.00
        balance_due = float(inv.amount)
        last_payment_date = None
        payment_completed_at = None

        # Resolve supplier_id
        sup_name = (inv.supplier_name or "").upper()
        sup_id = supplier_map.get(sup_name, None)
        if not sup_id and suppliers:
            # Fallback to first supplier for referential completeness
            sup_id = suppliers[0].id

        block_match = re.search(r'\[Payment:\s*([^|]+)\s*\|\s*Total Paid:\s*₹?\s*([\d.,]+)\s*\|\s*Due:\s*₹?\s*([\d.,]+)[^\]]*\]', remarks)
        if block_match:
            legacy_status = block_match.group(1).strip()
            total_paid_amount = float(block_match.group(2).replace(',', ''))
            balance_due = float(block_match.group(3).replace(',', ''))

            # Map status
            if legacy_status in ("Fully paid", "Fully Paid"):
                payment_status = "FULL_PAYMENT"
                payment_completed_at = inv.created_at or datetime.utcnow()
            elif legacy_status in ("Partially paid", "Partially Paid"):
                payment_status = "PARTIAL_PAYMENT"
            else:
                payment_status = "PAY_LATER"

            # Parse transaction timeline insideremarks block
            # Format: {seq|amount|method|timestamp|note}
            tx_blocks = re.findall(r'\{([^}]+)\}', remarks)
            if tx_blocks:
                for idx, tx_str in enumerate(tx_blocks):
                    parts = tx_str.split('|')
                    if len(parts) >= 4:
                        try:
                            tx_amount = float(parts[1].replace(',', ''))
                            tx_method = parts[2].upper().replace(' ', '_').replace('-', '_')
                            if tx_method not in ('CASH', 'UPI', 'CARD', 'BANK_TRANSFER', 'CHEQUE'):
                                tx_method = 'CASH'
                            
                            tx_time_str = parts[3]
                            # Try parsing timestamp
                            try:
                                tx_time = datetime.fromisoformat(tx_time_str.replace('Z', '+00:00'))
                            except ValueError:
                                tx_time = inv.created_at or datetime.utcnow()

                            tx_note = parts[4] if len(parts) > 4 else "Initial Payment"

                            last_payment_date = tx_time

                            # Insert payment transaction
                            connection.execute(
                                payment_txs_table.insert().values(
                            id=uuid.uuid4(),
                            temple_id=inv.temple_id,
                            invoice_id=inv.id,
                            amount=tx_amount,
                            payment_method=tx_method,
                            payment_reference=None,
                            transaction_status='COMPLETED',
                            payment_date=tx_time,
                            notes=tx_note,
                            created_by_user_id=None,
                            created_at=tx_time,
                            updated_at=tx_time
                                )
                            )
                        except Exception as e:
                            print(f"Skipping malformed transaction inside legacy remarks: {tx_str}. Error: {e}")
            else:
                # No transaction logs but paid amount exists. Insert default transaction to reflect this.
                if total_paid_amount > 0:
                    tx_time = inv.created_at or datetime.utcnow()
                    last_payment_date = tx_time
                    connection.execute(
                        payment_txs_table.insert().values(
                            id=uuid.uuid4(),
                            temple_id=inv.temple_id,
                            invoice_id=inv.id,
                            amount=total_paid_amount,
                            payment_method='CASH',
                            payment_reference=None,
                            transaction_status='COMPLETED',
                            payment_date=tx_time,
                            notes="Initial Legacy Migrated Payment",
                            created_by_user_id=None,
                            created_at=tx_time,
                            updated_at=tx_time
                        )
                    )
        else:
            # Fallback for old direct completed invoices
            if inv.status and inv.status.upper() == "COMPLETED":
                payment_status = "FULL_PAYMENT"
                total_paid_amount = float(inv.amount)
                balance_due = 0.00
                payment_completed_at = inv.created_at or datetime.utcnow()

                if total_paid_amount > 0:
                    tx_time = inv.created_at or datetime.utcnow()
                    last_payment_date = tx_time
                    connection.execute(
                        payment_txs_table.insert().values(
                            id=uuid.uuid4(),
                            temple_id=inv.temple_id,
                            invoice_id=inv.id,
                            amount=total_paid_amount,
                            payment_method='CASH',
                            payment_reference=None,
                            transaction_status='COMPLETED',
                            payment_date=tx_time,
                            notes="Legacy Default Payment",
                            created_by_user_id=None,
                            created_at=tx_time,
                            updated_at=tx_time
                        )
                    )
            else:
                payment_status = "PAY_LATER"
                total_paid_amount = 0.00
                balance_due = float(inv.amount)

        # Update invoice
        connection.execute(
            invoices_table.update()
            .where(invoices_table.c.id == inv.id)
            .values(
                supplier_id=sup_id,
                payment_status=payment_status,
                total_paid_amount=total_paid_amount,
                balance_due=balance_due,
                last_payment_date=last_payment_date,
                payment_completed_at=payment_completed_at
            )
        )

    # 4. Set non-nullable constraints
    op.alter_column('inventory_invoices', 'payment_status', existing_type=sa.String(), nullable=False, server_default='PAY_LATER')
    op.alter_column('inventory_invoices', 'total_paid_amount', existing_type=sa.Numeric(18, 2), nullable=False, server_default='0.00')
    op.alter_column('inventory_invoices', 'balance_due', existing_type=sa.Numeric(18, 2), nullable=False, server_default='0.00')

def downgrade() -> None:
    # Drop payment transactions table
    op.drop_table('inventory_payment_transactions')

    # Drop columns from inventory_invoices
    op.drop_column('inventory_invoices', 'deleted_by')
    op.drop_column('inventory_invoices', 'created_by_user_id')
    op.drop_column('inventory_invoices', 'deleted_at')
    op.drop_column('inventory_invoices', 'is_deleted')
    op.drop_column('inventory_invoices', 'payment_completed_at')
    op.drop_column('inventory_invoices', 'last_payment_date')
    op.drop_column('inventory_invoices', 'balance_due')
    op.drop_column('inventory_invoices', 'total_paid_amount')
    op.drop_column('inventory_invoices', 'payment_status')
    op.drop_column('inventory_invoices', 'supplier_id')
