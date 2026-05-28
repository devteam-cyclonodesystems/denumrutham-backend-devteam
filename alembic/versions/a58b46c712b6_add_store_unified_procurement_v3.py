"""add_store_unified_procurement_v3

Revision ID: a58b46c712b6
Revises: 6b72be601154
Create Date: 2026-05-23 05:55:15.001216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a58b46c712b6'
down_revision: Union[str, Sequence[str], None] = '6b72be601154'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename inventory_items to kalavara_inventory_items
    op.rename_table('inventory_items', 'kalavara_inventory_items')
    
    # Rename index
    op.execute("ALTER INDEX IF EXISTS ix_inventory_items_temple_id RENAME TO ix_kalavara_inventory_items_temple_id")

    # Add new columns to kalavara_inventory_items
    op.add_column('kalavara_inventory_items', sa.Column('base_unit', sa.String(), nullable=True))
    op.add_column('kalavara_inventory_items', sa.Column('purchase_unit', sa.String(), nullable=True))
    op.add_column('kalavara_inventory_items', sa.Column('conversion_ratio', sa.Float(), nullable=True))
    op.add_column('kalavara_inventory_items', sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('kalavara_inventory_items', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('kalavara_inventory_items', sa.Column('archived_by', sa.UUID(), nullable=True))
    
    # Create new index and FK constraint on kalavara_inventory_items
    op.create_index(op.f('ix_kalavara_inventory_items_is_archived'), 'kalavara_inventory_items', ['is_archived'], unique=False)
    op.create_foreign_key(op.f('kalavara_inventory_items_archived_by_fkey'), 'kalavara_inventory_items', 'users', ['archived_by'], ['id'])

    # Create store_sales_orders
    op.create_table('store_sales_orders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('order_number', sa.String(), nullable=False),
    sa.Column('customer_name', sa.String(), nullable=True),
    sa.Column('customer_phone', sa.String(), nullable=True),
    sa.Column('total_amount', sa.Float(), nullable=False),
    sa.Column('payment_mode', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('idempotency_key', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index(op.f('ix_store_sales_orders_order_number'), 'store_sales_orders', ['order_number'], unique=True)
    op.create_index(op.f('ix_store_sales_orders_temple_id'), 'store_sales_orders', ['temple_id'], unique=False)

    # Create store_products
    op.create_table('store_products',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('category', sa.String(), nullable=True),
    sa.Column('unit', sa.String(), nullable=True),
    sa.Column('unit_price', sa.Float(), nullable=True),
    sa.Column('supplier_id', sa.UUID(), nullable=True),
    sa.Column('barcode', sa.String(), nullable=True),
    sa.Column('sku', sa.String(), nullable=True),
    sa.Column('qr_code', sa.String(), nullable=True),
    sa.Column('rating', sa.Float(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('base_unit', sa.String(), nullable=True),
    sa.Column('purchase_unit', sa.String(), nullable=True),
    sa.Column('conversion_ratio', sa.Float(), nullable=True),
    sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='false'),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['archived_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_store_products_barcode'), 'store_products', ['barcode'], unique=False)
    op.create_index(op.f('ix_store_products_is_archived'), 'store_products', ['is_archived'], unique=False)
    op.create_index(op.f('ix_store_products_sku'), 'store_products', ['sku'], unique=False)
    op.create_index(op.f('ix_store_products_temple_id'), 'store_products', ['temple_id'], unique=False)

    # Create inventory_daily_snapshots
    op.create_table('inventory_daily_snapshots',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('domain_type', sa.String(), nullable=False),
    sa.Column('store_product_id', sa.UUID(), nullable=True),
    sa.Column('kalavara_item_id', sa.UUID(), nullable=True),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('inventory_value', sa.Float(), nullable=False),
    sa.Column('average_procurement_cost', sa.Float(), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('location_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(domain_type = 'STORE' AND store_product_id IS NOT NULL AND kalavara_item_id IS NULL) OR (domain_type = 'KALAVARA' AND kalavara_item_id IS NOT NULL AND store_product_id IS NULL)", name='chk_snapshot_polymorphic'),
    sa.ForeignKeyConstraint(['kalavara_item_id'], ['kalavara_inventory_items.id'], ),
    sa.ForeignKeyConstraint(['location_id'], ['inventory_locations.id'], ),
    sa.ForeignKeyConstraint(['store_product_id'], ['store_products.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inventory_daily_snapshots_snapshot_date'), 'inventory_daily_snapshots', ['snapshot_date'], unique=False)
    op.create_index(op.f('ix_inventory_daily_snapshots_temple_id'), 'inventory_daily_snapshots', ['temple_id'], unique=False)

    # Create kalavara_stock
    op.create_table('kalavara_stock',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('item_id', sa.UUID(), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('location_id', sa.UUID(), nullable=True),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['kalavara_inventory_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['location_id'], ['inventory_locations.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kalavara_stock_item_id'), 'kalavara_stock', ['item_id'], unique=False)
    op.create_index(op.f('ix_kalavara_stock_temple_id'), 'kalavara_stock', ['temple_id'], unique=False)

    # Create procurement_cost_history
    op.create_table('procurement_cost_history',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('domain_type', sa.String(), nullable=False),
    sa.Column('store_product_id', sa.UUID(), nullable=True),
    sa.Column('kalavara_item_id', sa.UUID(), nullable=True),
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('procurement_invoice_id', sa.UUID(), nullable=False),
    sa.Column('unit_cost', sa.Float(), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('total_cost', sa.Float(), nullable=False),
    sa.Column('location_id', sa.UUID(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(domain_type = 'STORE' AND store_product_id IS NOT NULL AND kalavara_item_id IS NULL) OR (domain_type = 'KALAVARA' AND kalavara_item_id IS NOT NULL AND store_product_id IS NULL)", name='chk_cost_history_polymorphic'),
    sa.ForeignKeyConstraint(['kalavara_item_id'], ['kalavara_inventory_items.id'], ),
    sa.ForeignKeyConstraint(['location_id'], ['inventory_locations.id'], ),
    sa.ForeignKeyConstraint(['procurement_invoice_id'], ['inventory_invoices.id'], ),
    sa.ForeignKeyConstraint(['store_product_id'], ['store_products.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_procurement_cost_history_temple_id'), 'procurement_cost_history', ['temple_id'], unique=False)

    # Create store_auctions
    op.create_table('store_auctions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('auction_code', sa.String(), nullable=True),
    sa.Column('idempotency_key', sa.String(), nullable=True),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('start_price', sa.Float(), nullable=True),
    sa.Column('current_bid', sa.Float(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='false'),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['archived_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['store_products.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index(op.f('ix_store_auctions_auction_code'), 'store_auctions', ['auction_code'], unique=True)
    op.create_index(op.f('ix_store_auctions_is_archived'), 'store_auctions', ['is_archived'], unique=False)
    op.create_index(op.f('ix_store_auctions_temple_id'), 'store_auctions', ['temple_id'], unique=False)

    # Create store_sales_order_items
    op.create_table('store_sales_order_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('unit_price', sa.Float(), nullable=False),
    sa.Column('total_price', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['store_sales_orders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['store_products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # Create store_stock
    op.create_table('store_stock',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('location_id', sa.UUID(), nullable=True),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['location_id'], ['inventory_locations.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['store_products.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_store_stock_product_id'), 'store_stock', ['product_id'], unique=False)
    op.create_index(op.f('ix_store_stock_temple_id'), 'store_stock', ['temple_id'], unique=False)

    # Create store_stock_reservations
    op.create_table('store_stock_reservations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('quantity_reserved', sa.Float(), nullable=False),
    sa.Column('reservation_status', sa.String(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reference_type', sa.String(), nullable=True),
    sa.Column('reference_id', sa.String(), nullable=True),
    sa.Column('location_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['location_id'], ['inventory_locations.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['store_products.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_store_stock_reservations_temple_id'), 'store_stock_reservations', ['temple_id'], unique=False)

    # Modify referencing foreign keys of other tables to point to kalavara_inventory_items
    op.drop_constraint('donation_inventory_mapping_item_id_fkey', 'donation_inventory_mapping', type_='foreignkey')
    op.create_foreign_key(None, 'donation_inventory_mapping', 'kalavara_inventory_items', ['item_id'], ['id'])
    
    op.drop_constraint('inventory_movements_item_id_fkey', 'inventory_movements', type_='foreignkey')
    op.create_foreign_key(None, 'inventory_movements', 'kalavara_inventory_items', ['item_id'], ['id'])
    
    op.drop_constraint('inventory_reconciliations_item_id_fkey', 'inventory_reconciliations', type_='foreignkey')
    op.create_foreign_key(None, 'inventory_reconciliations', 'kalavara_inventory_items', ['item_id'], ['id'])
    
    op.drop_constraint('inventory_transactions_item_id_fkey', 'inventory_transactions', type_='foreignkey')
    op.create_foreign_key(None, 'inventory_transactions', 'kalavara_inventory_items', ['item_id'], ['id'])
    
    op.drop_constraint('ritual_template_items_item_id_fkey', 'ritual_template_items', type_='foreignkey')
    op.create_foreign_key(None, 'ritual_template_items', 'kalavara_inventory_items', ['item_id'], ['id'])

    # Add columns and indices for inventory_invoices
    op.add_column('inventory_invoices', sa.Column('target_domain', sa.String(), nullable=False, server_default='KALAVARA'))
    op.add_column('inventory_invoices', sa.Column('due_date', sa.Date(), nullable=True))
    op.add_column('inventory_invoices', sa.Column('paid_amount', sa.Float(), nullable=False, server_default='0.0'))
    op.add_column('inventory_invoices', sa.Column('outstanding_amount', sa.Float(), nullable=False, server_default='0.0'))
    op.add_column('inventory_invoices', sa.Column('payment_state', sa.String(), nullable=True, server_default='UNPAID'))
    op.add_column('inventory_invoices', sa.Column('idempotency_key', sa.String(), nullable=True))
    op.add_column('inventory_invoices', sa.Column('location_id', sa.UUID(), nullable=True))
    op.add_column('inventory_invoices', sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('inventory_invoices', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('inventory_invoices', sa.Column('archived_by', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_inventory_invoices_is_archived'), 'inventory_invoices', ['is_archived'], unique=False)
    op.create_unique_constraint(None, 'inventory_invoices', ['idempotency_key'])
    op.create_foreign_key(None, 'inventory_invoices', 'users', ['archived_by'], ['id'])
    op.create_foreign_key(None, 'inventory_invoices', 'inventory_locations', ['location_id'], ['id'])

    # Add columns and indices for inventory_stock_ledger
    op.add_column('inventory_stock_ledger', sa.Column('idempotency_key', sa.String(), nullable=True))
    op.add_column('inventory_stock_ledger', sa.Column('domain_type', sa.String(), nullable=False, server_default='KALAVARA'))
    op.add_column('inventory_stock_ledger', sa.Column('store_product_id', sa.UUID(), nullable=True))
    op.add_column('inventory_stock_ledger', sa.Column('kalavara_item_id', sa.UUID(), nullable=True))
    op.add_column('inventory_stock_ledger', sa.Column('item_name', sa.String(), nullable=False, server_default=''))
    
    # Backfill ledger mapping for existing records: set kalavara_item_id = item_id, item_name = (from inventory_items)
    op.execute("UPDATE inventory_stock_ledger SET kalavara_item_id = item_id")
    op.execute("UPDATE inventory_stock_ledger SET item_name = (SELECT name FROM kalavara_inventory_items WHERE kalavara_inventory_items.id = inventory_stock_ledger.kalavara_item_id) WHERE item_name = ''")
    
    op.create_unique_constraint(None, 'inventory_stock_ledger', ['idempotency_key'])
    op.drop_constraint('inventory_stock_ledger_item_id_fkey', 'inventory_stock_ledger', type_='foreignkey')
    op.create_foreign_key(None, 'inventory_stock_ledger', 'store_products', ['store_product_id'], ['id'])
    op.create_foreign_key(None, 'inventory_stock_ledger', 'kalavara_inventory_items', ['kalavara_item_id'], ['id'])
    op.drop_column('inventory_stock_ledger', 'item_id')

    # Add idempotency_key to payments
    op.add_column('payments', sa.Column('idempotency_key', sa.String(), nullable=True))
    op.create_unique_constraint(None, 'payments', ['idempotency_key'])

    # Add columns and indices for procurement_grns
    op.add_column('procurement_grns', sa.Column('target_domain', sa.String(), nullable=False, server_default='KALAVARA'))
    op.add_column('procurement_grns', sa.Column('location_id', sa.UUID(), nullable=True))
    op.add_column('procurement_grns', sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('procurement_grns', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('procurement_grns', sa.Column('archived_by', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_procurement_grns_is_archived'), 'procurement_grns', ['is_archived'], unique=False)
    op.create_foreign_key(None, 'procurement_grns', 'inventory_locations', ['location_id'], ['id'])
    op.create_foreign_key(None, 'procurement_grns', 'users', ['archived_by'], ['id'])

    # Add columns and indices for suppliers
    op.add_column('suppliers', sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('suppliers', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('suppliers', sa.Column('archived_by', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_suppliers_is_archived'), 'suppliers', ['is_archived'], unique=False)
    op.create_foreign_key(None, 'suppliers', 'users', ['archived_by'], ['id'])


def downgrade() -> None:
    pass
