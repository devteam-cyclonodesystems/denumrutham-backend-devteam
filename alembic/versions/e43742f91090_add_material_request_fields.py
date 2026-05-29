"""add_material_request_fields

Revision ID: e43742f91090
Revises: 883472de95b6
Create Date: 2026-05-29 12:42:03.390086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e43742f91090'
down_revision: Union[str, Sequence[str], None] = '883472de95b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('inventory_item_requests', sa.Column('priority', sa.String(), nullable=True, server_default='Medium'))
    op.add_column('inventory_item_requests', sa.Column('purpose', sa.String(), nullable=True, server_default=''))
    op.add_column('inventory_item_requests', sa.Column('requested_by_user_id', sa.UUID(), nullable=True))
    op.add_column('inventory_item_requests', sa.Column('approved_by_user_id', sa.UUID(), nullable=True))
    op.add_column('inventory_item_requests', sa.Column('issued_by_user_id', sa.UUID(), nullable=True))
    
    op.create_foreign_key('fk_inventory_item_requests_requested_by_user_id_users', 'inventory_item_requests', 'users', ['requested_by_user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_inventory_item_requests_approved_by_user_id_users', 'inventory_item_requests', 'users', ['approved_by_user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_inventory_item_requests_issued_by_user_id_users', 'inventory_item_requests', 'users', ['issued_by_user_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_inventory_item_requests_issued_by_user_id_users', 'inventory_item_requests', type_='foreignkey')
    op.drop_constraint('fk_inventory_item_requests_approved_by_user_id_users', 'inventory_item_requests', type_='foreignkey')
    op.drop_constraint('fk_inventory_item_requests_requested_by_user_id_users', 'inventory_item_requests', type_='foreignkey')
    
    op.drop_column('inventory_item_requests', 'issued_by_user_id')
    op.drop_column('inventory_item_requests', 'approved_by_user_id')
    op.drop_column('inventory_item_requests', 'requested_by_user_id')
    op.drop_column('inventory_item_requests', 'purpose')
    op.drop_column('inventory_item_requests', 'priority')
