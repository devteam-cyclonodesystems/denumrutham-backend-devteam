"""add_merged_temple_id_to_temples

Revision ID: 3c7a911b6826
Revises: 253cb6f74d6c
Create Date: 2026-06-13 12:47:13.882745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c7a911b6826'
down_revision: Union[str, Sequence[str], None] = '253cb6f74d6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('temples', sa.Column('merged_temple_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_temples_merged_temple_id', 'temples', 'temples', ['merged_temple_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_temples_merged_temple_id', 'temples', type_='foreignkey')
    op.drop_column('temples', 'merged_temple_id')
