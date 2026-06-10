"""add live temple experience settings and festival table

Revision ID: hardening_pass_007_live_temple_experience
Revises: hardening_pass_006_add_seo_description
Create Date: 2026-06-09 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'hardening_pass_007_live_temple_experience'
down_revision: Union[str, Sequence[str], None] = '591618e0a71a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # 1. Add columns to temple_website_settings
    columns = [c['name'] for c in inspector.get_columns('temple_website_settings')]
    
    if 'location_settings' not in columns:
        op.add_column(
            'temple_website_settings',
            sa.Column('location_settings', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True)
        )
    if 'timings_settings' not in columns:
        op.add_column(
            'temple_website_settings',
            sa.Column('timings_settings', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True)
        )
    if 'daily_activities_settings' not in columns:
        op.add_column(
            'temple_website_settings',
            sa.Column('daily_activities_settings', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True)
        )

    # 2. Create temple_festivals table
    tables = inspector.get_table_names()
    if 'temple_festivals' not in tables:
        op.create_table(
            'temple_festivals',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('temple_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('start_date', sa.Date(), nullable=False),
            sa.Column('end_date', sa.Date(), nullable=False),
            sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('banner_image', sa.String(), nullable=True),
            sa.Column('catalogue_urls', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False, server_default='[]'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_temple_festivals_temple_id', 'temple_festivals', ['temple_id'])

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # 1. Drop temple_festivals table
    tables = inspector.get_table_names()
    if 'temple_festivals' in tables:
        op.drop_index('idx_temple_festivals_temple_id', table_name='temple_festivals')
        op.drop_table('temple_festivals')
        
    # 2. Drop columns from temple_website_settings
    columns = [c['name'] for c in inspector.get_columns('temple_website_settings')]
    
    if 'daily_activities_settings' in columns:
        op.drop_column('temple_website_settings', 'daily_activities_settings')
    if 'timings_settings' in columns:
        op.drop_column('temple_website_settings', 'timings_settings')
    if 'location_settings' in columns:
        op.drop_column('temple_website_settings', 'location_settings')
