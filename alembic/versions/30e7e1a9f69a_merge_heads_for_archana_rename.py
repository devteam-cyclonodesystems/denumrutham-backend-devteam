"""merge heads for archana rename

Revision ID: 30e7e1a9f69a
Revises: 6422b59e11f6, a9f1e2d3c4b5
Create Date: 2026-06-26 13:10:12.784317

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '30e7e1a9f69a'
down_revision: Union[str, Sequence[str], None] = ('6422b59e11f6', 'a9f1e2d3c4b5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
