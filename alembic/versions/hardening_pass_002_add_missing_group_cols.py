"""Add missing columns to archana_execution_groups

Revision ID: hardening_pass_002
Revises: hardening_pass_001
Create Date: 2026-05-29 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'hardening_pass_002'
down_revision: Union[str, Sequence[str], None] = 'hardening_pass_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Check if columns exist
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c["name"] for c in insp.get_columns('archana_execution_groups')]
    
    if 'expected_completion_at' not in columns:
        op.add_column('archana_execution_groups', sa.Column('expected_completion_at', sa.DateTime(timezone=True), nullable=True))
    if 'completed_at' not in columns:
        op.add_column('archana_execution_groups', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    if 'status' not in columns:
        op.add_column('archana_execution_groups', sa.Column('status', postgresql.ENUM('WAITING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'SKIPPED', 'SYNC_PENDING', name='queuestatus', create_type=False), nullable=True))
        
    # Check if foreign keys exist
    fkeys = insp.get_foreign_keys('archana_execution_groups')
    fkey_names = [fk['name'] for fk in fkeys]
    
    if 'fk_archana_execution_groups_temple_id_temples' not in fkey_names:
        op.create_foreign_key('fk_archana_execution_groups_temple_id_temples', 'archana_execution_groups', 'temples', ['temple_id'], ['id'])
    if 'fk_archana_execution_groups_started_by_users' not in fkey_names:
        op.create_foreign_key('fk_archana_execution_groups_started_by_users', 'archana_execution_groups', 'users', ['started_by'], ['id'])

def downgrade() -> None:
    op.drop_constraint('fk_archana_execution_groups_started_by_users', 'archana_execution_groups', type_='foreignkey')
    op.drop_constraint('fk_archana_execution_groups_temple_id_temples', 'archana_execution_groups', type_='foreignkey')
    op.drop_column('archana_execution_groups', 'status')
    op.drop_column('archana_execution_groups', 'completed_at')
    op.drop_column('archana_execution_groups', 'expected_completion_at')
