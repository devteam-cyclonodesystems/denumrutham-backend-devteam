"""add public directory indexes

Revision ID: add_public_directory_indexes
Revises: hardening_pass_007_live_temple_experience
Create Date: 2026-06-10 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_public_directory_indexes'
down_revision: Union[str, Sequence[str], None] = '48bd9fc73314'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # composite index on temple_profiles(state, district)
    op.create_index('idx_temple_profiles_state_district', 'temple_profiles', ['state', 'district'])
    # index on temple_profiles(district)
    op.create_index('idx_temple_profiles_district', 'temple_profiles', ['district'])
    # index on temples(name) for alphabetical ordering
    op.create_index('idx_temples_name_alphabetical', 'temples', ['name'])

def downgrade() -> None:
    op.drop_index('idx_temples_name_alphabetical', table_name='temples')
    op.drop_index('idx_temple_profiles_district', table_name='temple_profiles')
    op.drop_index('idx_temple_profiles_state_district', table_name='temple_profiles')
