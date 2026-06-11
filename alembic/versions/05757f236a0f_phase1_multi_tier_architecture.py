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
    """Upgrade schema — fully idempotent."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    indexes = {idx['name'] for t in tables for idx in inspector.get_indexes(t)}

    # 1. Create temple_leads table
    if 'temple_leads' not in tables:
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
        if 'idx_temple_leads_status_date' not in indexes:
            op.create_index('idx_temple_leads_status_date', 'temple_leads', ['status', 'follow_up_date'], unique=False)

    # 2. Create temple_ownership_history table
    if 'temple_ownership_history' not in tables:
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
        if 'idx_ownership_history_lookup' not in indexes:
            op.create_index('idx_ownership_history_lookup', 'temple_ownership_history', ['temple_id', 'changed_at'], unique=False)
        if 'ix_temple_ownership_history_temple_id' not in indexes:
            op.create_index(op.f('ix_temple_ownership_history_temple_id'), 'temple_ownership_history', ['temple_id'], unique=False)

    # 3. Add columns to temple_website_settings
    tws_columns = [c['name'] for c in inspector.get_columns('temple_website_settings')]
    if 'approval_status' not in tws_columns:
        op.add_column('temple_website_settings', sa.Column('approval_status', sa.String(length=30), nullable=False, server_default='DRAFT'))
    if 'submitted_by' not in tws_columns:
        op.add_column('temple_website_settings', sa.Column('submitted_by', sa.UUID(), nullable=True))
    if 'submitted_at' not in tws_columns:
        op.add_column('temple_website_settings', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))
    if 'reviewed_by' not in tws_columns:
        op.add_column('temple_website_settings', sa.Column('reviewed_by', sa.UUID(), nullable=True))
    if 'reviewed_at' not in tws_columns:
        op.add_column('temple_website_settings', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    if 'rejection_reason' not in tws_columns:
        op.add_column('temple_website_settings', sa.Column('rejection_reason', sa.Text(), nullable=True))

    # Create FKs only if they don't exist
    tws_fks = {fk['name'] for fk in inspector.get_foreign_keys('temple_website_settings')}
    if 'fk_temple_website_settings_submitted_by' not in tws_fks:
        op.create_foreign_key('fk_temple_website_settings_submitted_by', 'temple_website_settings', 'users', ['submitted_by'], ['id'], ondelete='SET NULL')
    if 'fk_temple_website_settings_reviewed_by' not in tws_fks:
        op.create_foreign_key('fk_temple_website_settings_reviewed_by', 'temple_website_settings', 'users', ['reviewed_by'], ['id'], ondelete='SET NULL')

    # 4. Add columns to temples
    temple_columns = [c['name'] for c in inspector.get_columns('temples')]
    if 'management_mode' not in temple_columns:
        op.add_column('temples', sa.Column('management_mode', sa.String(length=30), nullable=False, server_default='SELF_MANAGED'))
    if 'directory_status' not in temple_columns:
        op.add_column('temples', sa.Column('directory_status', sa.String(length=30), nullable=False, server_default='ACTIVE'))
    if 'subscription_plan' not in temple_columns:
        op.add_column('temples', sa.Column('subscription_plan', sa.String(length=40), nullable=False, server_default='SELF_MANAGED_PRO'))
    if 'idx_temples_directory_status' not in indexes:
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
