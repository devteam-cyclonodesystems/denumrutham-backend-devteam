"""phase3_subscriptions

Revision ID: 05757f236a11
Revises: 05757f236a10
Create Date: 2026-06-11 19:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05757f236a11'
down_revision: Union[str, Sequence[str], None] = '05757f236a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('razorpay_subscription_id', sa.String(length=80), nullable=True),
        sa.Column('razorpay_plan_id', sa.String(length=80), nullable=True),
        sa.Column('subscription_plan', sa.String(length=40), nullable=False, server_default='FREE'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='ACTIVE'),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trial_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trial_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_period_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('temple_id')
    )
    op.create_index('idx_subscriptions_razorpay_sub', 'subscriptions', ['razorpay_subscription_id'], unique=False)

    op.create_table(
        'subscription_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('subscription_id', sa.UUID(), nullable=True),
        sa.Column('event_name', sa.String(length=80), nullable=False),
        sa.Column('previous_status', sa.String(length=30), nullable=True),
        sa.Column('new_status', sa.String(length=30), nullable=True),
        sa.Column('payload_snapshot', sa.JSON(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_subscription_events_sub', 'subscription_events', ['subscription_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_subscription_events_sub', table_name='subscription_events')
    op.drop_table('subscription_events')
    op.drop_index('idx_subscriptions_razorpay_sub', table_name='subscriptions')
    op.drop_table('subscriptions')
