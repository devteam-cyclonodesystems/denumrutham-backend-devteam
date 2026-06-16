"""add_video_media_type_to_advertisements

Revision ID: 027dfbbd5b13
Revises: 3c7a911b6826
Create Date: 2026-06-16 16:42:14.778174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '027dfbbd5b13'
down_revision: Union[str, Sequence[str], None] = '3c7a911b6826'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Update platform_advertisements check constraint
    with op.batch_alter_table('platform_advertisements', schema=None) as batch_op:
        batch_op.drop_constraint('chk_platform_ad_media_type', type_='check')
        batch_op.create_check_constraint(
            'chk_platform_ad_media_type',
            "media_type IN ('IMAGE', 'CAROUSEL', 'VIDEO')"
        )

    # 2. Update temple_advertisements check constraint
    with op.batch_alter_table('temple_advertisements', schema=None) as batch_op:
        batch_op.drop_constraint('chk_temple_ad_media_type', type_='check')
        batch_op.create_check_constraint(
            'chk_temple_ad_media_type',
            "media_type IN ('IMAGE', 'CAROUSEL', 'VIDEO')"
        )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Revert platform_advertisements check constraint
    with op.batch_alter_table('platform_advertisements', schema=None) as batch_op:
        batch_op.drop_constraint('chk_platform_ad_media_type', type_='check')
        batch_op.create_check_constraint(
            'chk_platform_ad_media_type',
            "media_type IN ('IMAGE', 'CAROUSEL')"
        )

    # 2. Revert temple_advertisements check constraint
    with op.batch_alter_table('temple_advertisements', schema=None) as batch_op:
        batch_op.drop_constraint('chk_temple_ad_media_type', type_='check')
        batch_op.create_check_constraint(
            'chk_temple_ad_media_type',
            "media_type IN ('IMAGE', 'CAROUSEL')"
        )
