"""phase1_multi_tier_architecture

Revision ID: 05757f236a0f
Revises: add_public_directory_indexes
Create Date: 2026-06-11 18:44:02.752121

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05757f236a0f'
down_revision: Union[str, Sequence[str], None] = 'add_public_directory_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create temple_leads table
    op.create_table(
        'temple_leads',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('temple_name', sa.String(), nullable=False),
        sa.Column('contact_person', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('district', sa.String(), nullable=False),
        sa.Column('interested_plan', sa.String(), nullable=True),
        sa.Column('lead_source', sa.String(), nullable=True),
        sa.Column('follow_up_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='NEW'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_temple_leads_status_date', 'temple_leads', ['status', 'follow_up_date'], unique=False)

    # 2. Create temple_ownership_history table
    op.create_table(
        'temple_ownership_history',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('previous_management_mode', sa.String(length=30), nullable=True),
        sa.Column('new_management_mode', sa.String(length=30), nullable=False),
        sa.Column('previous_subscription_plan', sa.String(length=40), nullable=True),
        sa.Column('new_subscription_plan', sa.String(length=40), nullable=False),
        sa.Column('changed_by', sa.UUID(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_ownership_history_lookup', 'temple_ownership_history', ['temple_id', 'changed_at'], unique=False)
    op.create_index(op.f('ix_temple_ownership_history_temple_id'), 'temple_ownership_history', ['temple_id'], unique=False)

    # 3. Add columns to temple_website_settings
    op.add_column('temple_website_settings', sa.Column('approval_status', sa.String(length=30), nullable=False, server_default='DRAFT'))
    op.add_column('temple_website_settings', sa.Column('submitted_by', sa.UUID(), nullable=True))
    op.add_column('temple_website_settings', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('temple_website_settings', sa.Column('reviewed_by', sa.UUID(), nullable=True))
    op.add_column('temple_website_settings', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('temple_website_settings', sa.Column('rejection_reason', sa.Text(), nullable=True))
    op.create_foreign_key('fk_temple_website_settings_submitted_by', 'temple_website_settings', 'users', ['submitted_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_temple_website_settings_reviewed_by', 'temple_website_settings', 'users', ['reviewed_by'], ['id'], ondelete='SET NULL')

    # 4. Add columns to temples
    op.add_column('temples', sa.Column('management_mode', sa.String(length=30), nullable=False, server_default='SELF_MANAGED'))
    op.add_column('temples', sa.Column('directory_status', sa.String(length=30), nullable=False, server_default='ACTIVE'))
    op.add_column('temples', sa.Column('subscription_plan', sa.String(length=40), nullable=False, server_default='SELF_MANAGED_PRO'))
    op.create_index('idx_temples_directory_status', 'temples', ['directory_status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop index & columns from temples
    op.drop_index('idx_temples_directory_status', table_name='temples')
    op.drop_column('temples', 'subscription_plan')
    op.drop_column('temples', 'directory_status')
    op.drop_column('temples', 'management_mode')

    # 2. Drop constraints & columns from temple_website_settings
    op.drop_constraint('fk_temple_website_settings_reviewed_by', 'temple_website_settings', type_='foreignkey')
    op.drop_constraint('fk_temple_website_settings_submitted_by', 'temple_website_settings', type_='foreignkey')
    op.drop_column('temple_website_settings', 'rejection_reason')
    op.drop_column('temple_website_settings', 'reviewed_at')
    op.drop_column('temple_website_settings', 'reviewed_by')
    op.drop_column('temple_website_settings', 'submitted_at')
    op.drop_column('temple_website_settings', 'submitted_by')
    op.drop_column('temple_website_settings', 'approval_status')

    # 3. Drop temple_ownership_history table & indexes
    op.drop_index(op.f('ix_temple_ownership_history_temple_id'), table_name='temple_ownership_history')
    op.drop_index('idx_ownership_history_lookup', table_name='temple_ownership_history')
    op.drop_table('temple_ownership_history')

    # 4. Drop temple_leads table & index
    op.drop_index('idx_temple_leads_status_date', table_name='temple_leads')
    op.drop_table('temple_leads')
