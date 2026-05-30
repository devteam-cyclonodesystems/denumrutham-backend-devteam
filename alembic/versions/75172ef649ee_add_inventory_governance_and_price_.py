"""add_inventory_governance_and_price_approvals

Revision ID: 75172ef649ee
Revises: e43742f91090
Create Date: 2026-05-30 11:35:49.485973

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75172ef649ee'
down_revision: Union[str, Sequence[str], None] = 'e43742f91090'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name, column_name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = insp.get_columns(table_name)
    return any(c['name'] == column_name for c in columns)


def table_exists(table_name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    # 1. Check & Add columns in kalavara_inventory_items
    if not column_exists('kalavara_inventory_items', 'created_from_supplier'):
        op.add_column('kalavara_inventory_items', sa.Column('created_from_supplier', sa.Boolean(), server_default='false', nullable=True))
    if not column_exists('kalavara_inventory_items', 'min_stock_source'):
        op.add_column('kalavara_inventory_items', sa.Column('min_stock_source', sa.String(), server_default='MANUAL', nullable=True))

    # 2. Check & Add columns in supplier_price_history
    if not column_exists('supplier_price_history', 'supplier_name'):
        op.add_column('supplier_price_history', sa.Column('supplier_name', sa.String(), server_default='', nullable=True))
    if not column_exists('supplier_price_history', 'price_difference'):
        op.add_column('supplier_price_history', sa.Column('price_difference', sa.Float(), server_default='0.0', nullable=True))
    if not column_exists('supplier_price_history', 'percentage_change'):
        op.add_column('supplier_price_history', sa.Column('percentage_change', sa.Float(), server_default='0.0', nullable=True))
    if not column_exists('supplier_price_history', 'modified_by_id'):
        op.add_column('supplier_price_history', sa.Column('modified_by_id', sa.String(), server_default='', nullable=True))
    if not column_exists('supplier_price_history', 'modified_by_name'):
        op.add_column('supplier_price_history', sa.Column('modified_by_name', sa.String(), server_default='', nullable=True))
    if not column_exists('supplier_price_history', 'reason'):
        op.add_column('supplier_price_history', sa.Column('reason', sa.String(), server_default='', nullable=True))
    if not column_exists('supplier_price_history', 'source'):
        op.add_column('supplier_price_history', sa.Column('source', sa.String(), server_default='Supplier Update', nullable=True))

    # 3. Create price_approval_requests table if missing
    if not table_exists('price_approval_requests'):
        op.create_table(
            'price_approval_requests',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('temple_id', sa.UUID(), nullable=False),
            sa.Column('supplier_id', sa.UUID(), nullable=True),
            sa.Column('inventory_item_id', sa.UUID(), nullable=False),
            sa.Column('old_price', sa.Float(), nullable=True),
            sa.Column('new_price', sa.Float(), nullable=False),
            sa.Column('change_percentage', sa.Float(), nullable=False),
            sa.Column('requested_by', sa.String(), server_default='Admin', nullable=True),
            sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('status', sa.String(), server_default='PENDING_APPROVAL', nullable=True),
            sa.Column('approved_by', sa.String(), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('reason', sa.String(), nullable=True),
            sa.Column('approval_type', sa.String(), server_default='WARNING', nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['temple_id'], ['temples.id']),
            sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
            sa.ForeignKeyConstraint(['inventory_item_id'], ['kalavara_inventory_items.id'])
        )
        op.create_index('ix_price_approval_requests_temple_id', 'price_approval_requests', ['temple_id'], unique=False)
        op.create_index('ix_price_approval_requests_supplier_id', 'price_approval_requests', ['supplier_id'], unique=False)
        op.create_index('ix_price_approval_requests_inventory_item_id', 'price_approval_requests', ['inventory_item_id'], unique=False)


def downgrade() -> None:
    if table_exists('price_approval_requests'):
        op.drop_index('ix_price_approval_requests_inventory_item_id', table_name='price_approval_requests')
        op.drop_index('ix_price_approval_requests_supplier_id', table_name='price_approval_requests')
        op.drop_index('ix_price_approval_requests_temple_id', table_name='price_approval_requests')
        op.drop_table('price_approval_requests')

    if column_exists('kalavara_inventory_items', 'min_stock_source'):
        op.drop_column('kalavara_inventory_items', 'min_stock_source')
    if column_exists('kalavara_inventory_items', 'created_from_supplier'):
        op.drop_column('kalavara_inventory_items', 'created_from_supplier')
