"""add_sprint4_entities

Revision ID: 591618e0a71a
Revises: d912501e7d00
Create Date: 2026-06-09 10:33:52.812618

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '591618e0a71a'
down_revision: Union[str, Sequence[str], None] = 'd912501e7d00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

