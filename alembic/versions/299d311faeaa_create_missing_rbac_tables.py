"""create_missing_rbac_tables

Revision ID: 299d311faeaa
Revises: 027dfbbd5b13
Create Date: 2026-06-17 11:47:23.912441

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '299d311faeaa'
down_revision: Union[str, Sequence[str], None] = '027dfbbd5b13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — fully idempotent."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'permissions' not in tables:
        op.create_table('permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('temple_id', sa.UUID(), nullable=True),
        sa.Column('resource_type', sa.String(), nullable=False),
        sa.Column('resource_key', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('resource_type', 'resource_key', name='uq_perm_resource')
        )
        op.create_index(op.f('ix_permissions_temple_id'), 'permissions', ['temple_id'], unique=False)

    if 'roles' not in tables:
        op.create_table('roles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('temple_id', 'name', name='uq_role_tenant_name')
        )
        op.create_index(op.f('ix_roles_temple_id'), 'roles', ['temple_id'], unique=False)

    if 'role_permissions' not in tables:
        op.create_table('role_permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('permission_id', sa.UUID(), nullable=False),
        sa.Column('access_level', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'permission_id', name='uq_role_permission')
        )

    if 'user_roles' not in tables:
        op.create_table('user_roles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role')
        )
        op.create_index(op.f('ix_user_roles_temple_id'), 'user_roles', ['temple_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema — fully idempotent."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'user_roles' in tables:
        op.drop_index(op.f('ix_user_roles_temple_id'), table_name='user_roles')
        op.drop_table('user_roles')
    if 'role_permissions' in tables:
        op.drop_table('role_permissions')
    if 'roles' in tables:
        op.drop_index(op.f('ix_roles_temple_id'), table_name='roles')
        op.drop_table('roles')
    if 'permissions' in tables:
        op.drop_index(op.f('ix_permissions_temple_id'), table_name='permissions')
        op.drop_table('permissions')
    # ### end Alembic commands ###
