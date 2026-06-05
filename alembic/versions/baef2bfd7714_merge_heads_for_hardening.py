"""merge_heads_for_hardening

Revision ID: baef2bfd7714
Revises: db8df6465e0a, hardening_pass_006_add_seo_description
Create Date: 2026-06-04 15:58:51.442208

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'baef2bfd7714'
down_revision: Union[str, Sequence[str], None] = ('db8df6465e0a', 'hardening_pass_006_add_seo_description')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
