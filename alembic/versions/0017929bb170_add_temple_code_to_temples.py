"""Add temple_code to temples

Revision ID: 0017929bb170
Revises: hardening_pass_001
Create Date: 2026-04-26 12:03:54.820787

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0017929bb170'
down_revision: Union[str, Sequence[str], None] = 'hardening_pass_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c['name'] for c in inspector.get_columns('temples')]
    if 'temple_code' not in columns:
        op.add_column('temples', sa.Column('temple_code', sa.String(), nullable=True))
    
    indexes = [idx['name'] for idx in inspector.get_indexes('temples')]
    if 'ix_temples_temple_code' not in indexes:
        op.create_index(op.f('ix_temples_temple_code'), 'temples', ['temple_code'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes('temples')]
    if 'ix_temples_temple_code' in indexes:
        op.drop_index(op.f('ix_temples_temple_code'), table_name='temples')
    
    columns = [c['name'] for c in inspector.get_columns('temples')]
    if 'temple_code' in columns:
        op.drop_column('temples', 'temple_code')
