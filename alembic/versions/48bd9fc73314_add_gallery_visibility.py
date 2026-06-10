"""add_gallery_visibility

Revision ID: 48bd9fc73314
Revises: hardening_pass_007_live_temple_experience
Create Date: 2026-06-10 11:10:30.549858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48bd9fc73314'
down_revision: Union[str, Sequence[str], None] = 'hardening_pass_007_live_temple_experience'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('temple_images', sa.Column('is_visible', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('temple_images', 'is_visible')
