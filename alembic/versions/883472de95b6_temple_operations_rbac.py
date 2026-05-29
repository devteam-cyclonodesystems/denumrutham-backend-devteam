"""temple_operations_rbac

Revision ID: 883472de95b6
Revises: 00c8ae576791
Create Date: 2026-05-29 12:18:11.649633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '883472de95b6'
down_revision: Union[str, Sequence[str], None] = '00c8ae576791'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add audit columns to archana_executions
    op.add_column('archana_executions', sa.Column('started_by_user_id', sa.UUID(), nullable=True))
    op.add_column('archana_executions', sa.Column('completed_by_user_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_archana_executions_started_by_user_id_users', 'archana_executions', 'users', ['started_by_user_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_archana_executions_completed_by_user_id_users', 'archana_executions', 'users', ['completed_by_user_id'], ['id'], ondelete='SET NULL')

    # 2. Update permissions table constraints
    # Drop old unique constraint on permissions
    op.drop_constraint('uq_perm_tenant_resource', 'permissions', type_='unique')
    
    # Make temple_id nullable on permissions
    op.alter_column('permissions', 'temple_id', existing_type=sa.UUID(), nullable=True)
    
    # Add new unique constraint
    op.create_unique_constraint('uq_perm_resource', 'permissions', ['resource_type', 'resource_key'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the new unique constraint on permissions
    op.drop_constraint('uq_perm_resource', 'permissions', type_='unique')
    
    # Re-enable NOT NULL on temple_id
    op.alter_column('permissions', 'temple_id', existing_type=sa.UUID(), nullable=False)
    
    # Re-add uq_perm_tenant_resource unique constraint
    op.create_unique_constraint('uq_perm_tenant_resource', 'permissions', ['temple_id', 'resource_type', 'resource_key'])
    
    # Drop columns on archana_executions
    op.drop_constraint('fk_archana_executions_completed_by_user_id_users', 'archana_executions', type_='foreignkey')
    op.drop_constraint('fk_archana_executions_started_by_user_id_users', 'archana_executions', type_='foreignkey')
    op.drop_column('archana_executions', 'completed_by_user_id')
    op.drop_column('archana_executions', 'started_by_user_id')
