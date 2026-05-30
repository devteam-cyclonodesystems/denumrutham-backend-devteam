"""Extend price_approval_requests for governance tracking

Revision ID: hardening_pass_003_extend_price_approvals
Revises: 75172ef649ee
Create Date: 2026-05-30 12:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'hardening_pass_003_extend_price_approvals'
down_revision: Union[str, Sequence[str], None] = '75172ef649ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def column_exists(table_name, column_name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = insp.get_columns(table_name)
    return any(c['name'] == column_name for c in columns)

def upgrade() -> None:
    # Check & Add columns in price_approval_requests
    if not column_exists('price_approval_requests', 'requested_by_user_id'):
        op.add_column('price_approval_requests', sa.Column('requested_by_user_id', sa.UUID(), nullable=True))
    if not column_exists('price_approval_requests', 'requested_by_role'):
        op.add_column('price_approval_requests', sa.Column('requested_by_role', sa.String(), nullable=True))
    if not column_exists('price_approval_requests', 'reason_notes'):
        op.add_column('price_approval_requests', sa.Column('reason_notes', sa.String(), nullable=True))
    
    # Alter supplier_id to be nullable
    op.alter_column('supplier_price_history', 'supplier_id', existing_type=sa.UUID(), nullable=True)
    op.alter_column('price_approval_requests', 'supplier_id', existing_type=sa.UUID(), nullable=True)

def downgrade() -> None:
    op.alter_column('price_approval_requests', 'supplier_id', existing_type=sa.UUID(), nullable=False)
    op.alter_column('supplier_price_history', 'supplier_id', existing_type=sa.UUID(), nullable=False)

    if column_exists('price_approval_requests', 'reason_notes'):
        op.drop_column('price_approval_requests', 'reason_notes')
    if column_exists('price_approval_requests', 'requested_by_role'):
        op.drop_column('price_approval_requests', 'requested_by_role')
    if column_exists('price_approval_requests', 'requested_by_user_id'):
        op.drop_column('price_approval_requests', 'requested_by_user_id')
