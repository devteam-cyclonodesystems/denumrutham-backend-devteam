"""add seo_description to website settings

Revision ID: hardening_pass_006_add_seo_description
Revises: hardening_pass_005_seed_additional_permissions
Create Date: 2026-06-04 12:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'hardening_pass_006_add_seo_description'
down_revision: Union[str, Sequence[str], None] = 'hardening_pass_005_seed_additional_permissions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = 'db8df6465e0a'

def upgrade() -> None:
    # Add column with safety checks
    bind = op.get_bind()
    columns = [c['name'] for c in sa.inspect(bind).get_columns('temple_website_settings')]
    if 'seo_description' not in columns:
        op.add_column('temple_website_settings', sa.Column('seo_description', sa.String(), nullable=True))

def downgrade() -> None:
    bind = op.get_bind()
    columns = [c['name'] for c in sa.inspect(bind).get_columns('temple_website_settings')]
    if 'seo_description' in columns:
        op.drop_column('temple_website_settings', 'seo_description')
