"""rename_version_to_version_number

Revision ID: 4c2b9a1d3f0e
Revises: bb4828bc10ec
Create Date: 2026-05-13 13:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4c2b9a1d3f0e'
down_revision: Union[str, Sequence[str], None] = 'bb4828bc10ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Rename version to version_number in archana_executions
    op.alter_column('archana_executions', 'version', new_column_name='version_number')
    
    # Ensure all required columns exist and are not nullable if needed
    # (Based on prompt requirements)
    # status, started_at, expected_completion_at, completed_at, completion_mode, execution_group_id, version_number
    # These were mostly added in bb4828bc10ec or 0f99a02d05d3.

def downgrade() -> None:
    op.alter_column('archana_executions', 'version_number', new_column_name='version')
