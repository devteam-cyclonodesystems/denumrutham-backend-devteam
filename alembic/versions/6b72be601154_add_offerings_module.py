"""add offerings module

Revision ID: 6b72be601154
Revises: 317851668047
Create Date: 2026-05-21 04:20:32.992894

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6b72be601154'
down_revision: Union[str, Sequence[str], None] = '317851668047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create offering_categories
    op.create_table('offering_categories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('category_name', sa.String(), nullable=False),
    sa.Column('category_code', sa.String(), nullable=False),
    sa.Column('color_code', sa.String(), nullable=True),
    sa.Column('icon', sa.String(), nullable=True),
    sa.Column('receipt_prefix', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offering_categories_temple_id'), 'offering_categories', ['temple_id'], unique=False)

    # 2. Create offerings without receipt foreign key constraint first
    op.create_table('offerings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('offering_number', sa.String(), nullable=False),
    sa.Column('donor_name', sa.String(), nullable=False),
    sa.Column('donor_phone', sa.String(), nullable=True),
    sa.Column('donor_address', sa.Text(), nullable=True),
    sa.Column('category_id', sa.UUID(), nullable=True),
    sa.Column('total_amount', sa.Float(), nullable=False),
    sa.Column('paid_amount', sa.Float(), nullable=True),
    sa.Column('balance_amount', sa.Float(), nullable=True),
    sa.Column('payment_status', sa.String(), nullable=True),
    sa.Column('payment_method', sa.String(), nullable=True),
    sa.Column('booking_mode', sa.String(), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('offering_status', sa.String(), nullable=True),
    sa.Column('receipt_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('verified_by', sa.String(), nullable=True),
    sa.Column('approved_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('local_uuid', sa.String(), nullable=True),
    sa.Column('sync_status', sa.String(), nullable=True),
    sa.Column('sync_version', sa.Integer(), nullable=True),
    sa.Column('source_device_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['category_id'], ['offering_categories.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('offering_number')
    )
    op.create_index('idx_offering_number', 'offerings', ['offering_number'], unique=False)
    op.create_index('idx_offering_status', 'offerings', ['temple_id', 'payment_status'], unique=False)
    op.create_index('idx_offering_temple', 'offerings', ['temple_id'], unique=False)
    op.create_index(op.f('ix_offerings_temple_id'), 'offerings', ['temple_id'], unique=False)

    # 3. Create offering_receipts referencing offerings
    op.create_table('offering_receipts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('offering_id', sa.UUID(), nullable=True),
    sa.Column('receipt_number', sa.String(), nullable=False),
    sa.Column('receipt_type', sa.String(), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('generated_by', sa.String(), nullable=True),
    sa.Column('pdf_path', sa.String(), nullable=True),
    sa.Column('qr_code', sa.String(), nullable=True),
    sa.Column('print_count', sa.Integer(), nullable=True),
    sa.Column('whatsapp_shared', sa.Boolean(), nullable=True),
    sa.Column('email_shared', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['offering_id'], ['offerings.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offering_receipts_temple_id'), 'offering_receipts', ['temple_id'], unique=False)

    # 4. Create the foreign key from offerings to offering_receipts
    op.create_foreign_key(
        'offerings_receipt_id_fkey', 'offerings', 'offering_receipts',
        ['receipt_id'], ['id']
    )

    # 5. Create other dependent tables
    op.create_table('offering_audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('offering_id', sa.UUID(), nullable=True),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('action_type', sa.String(), nullable=False),
    sa.Column('old_value', sa.JSON(), nullable=True),
    sa.Column('new_value', sa.JSON(), nullable=True),
    sa.Column('changed_by', sa.String(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', sa.String(), nullable=True),
    sa.Column('device_info', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['offering_id'], ['offerings.id'], ),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offering_audit_logs_temple_id'), 'offering_audit_logs', ['temple_id'], unique=False)

    op.create_table('offering_inventory_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('offering_id', sa.UUID(), nullable=False),
    sa.Column('metal_type', sa.String(), nullable=False),
    sa.Column('purity', sa.String(), nullable=True),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('estimated_value', sa.Float(), nullable=False),
    sa.Column('locker_reference', sa.String(), nullable=True),
    sa.Column('photo_path', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['offering_id'], ['offerings.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('offering_payments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('offering_id', sa.UUID(), nullable=False),
    sa.Column('transaction_number', sa.String(), nullable=False),
    sa.Column('payment_method', sa.String(), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('gateway_reference', sa.String(), nullable=True),
    sa.Column('payment_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_by', sa.String(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('sync_status', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['offering_id'], ['offerings.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('offering_reconciliations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('temple_id', sa.UUID(), nullable=False),
    sa.Column('reconciliation_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('shift_name', sa.String(), nullable=True),
    sa.Column('operator_name', sa.String(), nullable=True),
    sa.Column('total_offerings_count', sa.Integer(), nullable=True),
    sa.Column('total_amount', sa.Float(), nullable=True),
    sa.Column('total_cash', sa.Float(), nullable=True),
    sa.Column('total_upi', sa.Float(), nullable=True),
    sa.Column('total_card', sa.Float(), nullable=True),
    sa.Column('total_other', sa.Float(), nullable=True),
    sa.Column('pending_balance', sa.Float(), nullable=True),
    sa.Column('expected_total', sa.Float(), nullable=True),
    sa.Column('actual_collected', sa.Float(), nullable=True),
    sa.Column('variance', sa.Float(), nullable=True),
    sa.Column('category_breakdown', sa.JSON(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('closed_by', sa.String(), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offering_reconciliations_temple_id'), 'offering_reconciliations', ['temple_id'], unique=False)

    op.alter_column('halls', 'photos',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=sa.JSON(),
               existing_nullable=True,
               existing_server_default=sa.text("'[]'::jsonb"))


def downgrade() -> None:
    op.alter_column('halls', 'photos',
               existing_type=sa.JSON(),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True,
               existing_server_default=sa.text("'[]'::jsonb"))
    op.drop_index(op.f('ix_offering_reconciliations_temple_id'), table_name='offering_reconciliations')
    op.drop_table('offering_reconciliations')
    op.drop_table('offering_payments')
    op.drop_table('offering_inventory_links')
    op.drop_index(op.f('ix_offering_audit_logs_temple_id'), table_name='offering_audit_logs')
    op.drop_table('offering_audit_logs')
    op.drop_constraint('offerings_receipt_id_fkey', 'offerings', type_='foreignkey')
    op.drop_index(op.f('ix_offering_receipts_temple_id'), table_name='offering_receipts')
    op.drop_table('offering_receipts')
    op.drop_index(op.f('ix_offerings_temple_id'), table_name='offerings')
    op.drop_index('idx_offering_temple', table_name='offerings')
    op.drop_index('idx_offering_status', table_name='offerings')
    op.drop_index('idx_offering_number', table_name='offerings')
    op.drop_table('offerings')
    op.drop_index(op.f('ix_offering_categories_temple_id'), table_name='offering_categories')
    op.drop_table('offering_categories')

