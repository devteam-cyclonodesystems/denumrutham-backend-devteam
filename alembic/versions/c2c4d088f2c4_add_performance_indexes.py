"""add_performance_indexes

Revision ID: c2c4d088f2c4
Revises: baef2bfd7714
Create Date: 2026-06-04 15:58:58.799568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2c4d088f2c4'
down_revision: Union[str, Sequence[str], None] = 'baef2bfd7714'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('idx_announcements_temple_active', 'temple_announcements', ['temple_id', 'is_active'])
    op.create_index('idx_activities_temple_active', 'temple_activities', ['temple_id', 'is_active'])
    op.create_index('idx_images_temple_category', 'temple_images', ['temple_id', 'category'])
    op.create_index('idx_announcements_is_pinned', 'temple_announcements', ['is_pinned'])
    op.create_index('idx_activities_status', 'temple_activities', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_activities_status', table_name='temple_activities')
    op.drop_index('idx_announcements_is_pinned', table_name='temple_announcements')
    op.drop_index('idx_images_temple_category', table_name='temple_images')
    op.drop_index('idx_activities_temple_active', table_name='temple_activities')
    op.drop_index('idx_announcements_temple_active', table_name='temple_announcements')
