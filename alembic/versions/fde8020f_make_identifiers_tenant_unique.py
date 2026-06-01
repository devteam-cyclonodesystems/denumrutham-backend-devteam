"""make identifiers tenant unique

Revision ID: fde8020f
Revises: 522c76d941bd
Create Date: 2026-06-01 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fde8020f'
down_revision: Union[str, Sequence[str], None] = '522c76d941bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if not is_sqlite:
        # Drop global unique constraints/indexes
        op.execute("ALTER TABLE offerings DROP CONSTRAINT IF EXISTS offerings_offering_number_key;")
        op.execute("DROP INDEX IF EXISTS ix_store_sales_orders_order_number;")
        op.execute("DROP INDEX IF EXISTS ix_enterprise_archana_bookings_ref_id;")
        op.execute("DROP INDEX IF EXISTS ix_procurement_grns_grn_code;")
        op.execute("DROP INDEX IF EXISTS ix_archana_refunds_ref_id;")
        op.execute("DROP INDEX IF EXISTS ix_store_auctions_auction_code;")

        # Add composite unique constraints
        op.create_unique_constraint('uq_offering_number', 'offerings', ['temple_id', 'offering_number'])
        op.create_unique_constraint('uq_archana_booking_ref_id', 'enterprise_archana_bookings', ['temple_id', 'ref_id'])
        op.create_unique_constraint('uq_archana_refund_ref_id', 'archana_refunds', ['temple_id', 'ref_id'])
        op.create_unique_constraint('uq_procurement_grn_code', 'procurement_grns', ['temple_id', 'grn_code'])
        op.create_unique_constraint('uq_store_sales_order_number', 'store_sales_orders', ['temple_id', 'order_number'])
        op.create_unique_constraint('uq_store_auction_code', 'store_auctions', ['temple_id', 'auction_code'])
    else:
        with op.batch_alter_table('offerings', schema=None) as batch_op:
            batch_op.create_unique_constraint('uq_offering_number', ['temple_id', 'offering_number'])
        with op.batch_alter_table('enterprise_archana_bookings', schema=None) as batch_op:
            batch_op.create_unique_constraint('uq_archana_booking_ref_id', ['temple_id', 'ref_id'])
        with op.batch_alter_table('archana_refunds', schema=None) as batch_op:
            batch_op.create_unique_constraint('uq_archana_refund_ref_id', ['temple_id', 'ref_id'])
        with op.batch_alter_table('procurement_grns', schema=None) as batch_op:
            batch_op.create_unique_constraint('uq_procurement_grn_code', ['temple_id', 'grn_code'])
        with op.batch_alter_table('store_sales_orders', schema=None) as batch_op:
            batch_op.create_unique_constraint('uq_store_sales_order_number', ['temple_id', 'order_number'])
        with op.batch_alter_table('store_auctions', schema=None) as batch_op:
            batch_op.create_unique_constraint('uq_store_auction_code', ['temple_id', 'auction_code'])


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if not is_sqlite:
        op.drop_constraint('uq_offering_number', 'offerings', type_='unique')
        op.drop_constraint('uq_archana_booking_ref_id', 'enterprise_archana_bookings', type_='unique')
        op.drop_constraint('uq_archana_refund_ref_id', 'archana_refunds', type_='unique')
        op.drop_constraint('uq_procurement_grn_code', 'procurement_grns', type_='unique')
        op.drop_constraint('uq_store_sales_order_number', 'store_sales_orders', type_='unique')
        op.drop_constraint('uq_store_auction_code', 'store_auctions', type_='unique')

        op.execute("ALTER TABLE offerings ADD CONSTRAINT offerings_offering_number_key UNIQUE (offering_number);")
        op.execute("CREATE UNIQUE INDEX ix_store_sales_orders_order_number ON store_sales_orders (order_number);")
        op.execute("CREATE UNIQUE INDEX ix_enterprise_archana_bookings_ref_id ON enterprise_archana_bookings (ref_id);")
        op.execute("CREATE UNIQUE INDEX ix_procurement_grns_grn_code ON procurement_grns (grn_code);")
        op.execute("CREATE UNIQUE INDEX ix_archana_refunds_ref_id ON archana_refunds (ref_id);")
        op.execute("CREATE UNIQUE INDEX ix_store_auctions_auction_code ON store_auctions (auction_code);")
    else:
        with op.batch_alter_table('offerings', schema=None) as batch_op:
            batch_op.drop_constraint('uq_offering_number', type_='unique')
        with op.batch_alter_table('enterprise_archana_bookings', schema=None) as batch_op:
            batch_op.drop_constraint('uq_archana_booking_ref_id', type_='unique')
        with op.batch_alter_table('archana_refunds', schema=None) as batch_op:
            batch_op.drop_constraint('uq_archana_refund_ref_id', type_='unique')
        with op.batch_alter_table('procurement_grns', schema=None) as batch_op:
            batch_op.drop_constraint('uq_procurement_grn_code', type_='unique')
        with op.batch_alter_table('store_sales_orders', schema=None) as batch_op:
            batch_op.drop_constraint('uq_store_sales_order_number', type_='unique')
        with op.batch_alter_table('store_auctions', schema=None) as batch_op:
            batch_op.drop_constraint('uq_store_auction_code', type_='unique')
