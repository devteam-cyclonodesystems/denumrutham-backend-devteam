"""enforce_temple_status_constraint

Revision ID: 6dfc4490a13a
Revises: cf49bc934db9
Create Date: 2026-05-03 09:41:17.684728

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6dfc4490a13a'
down_revision: Union[str, Sequence[str], None] = 'cf49bc934db9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Data cleanup: update invalid statuses
    op.execute("UPDATE temples SET status = 'APPROVED' WHERE status IN ('active', 'ACTIVE');")
    op.execute("UPDATE temples SET status = 'PENDING' WHERE status IN ('inactive', 'INACTIVE');")
    
    # 2. Add CHECK constraint
    op.execute("ALTER TABLE temples ADD CONSTRAINT valid_temple_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED'));")

def downgrade() -> None:
    """Downgrade schema."""
    # Remove CHECK constraint
    op.execute("ALTER TABLE temples DROP CONSTRAINT valid_temple_status;")
