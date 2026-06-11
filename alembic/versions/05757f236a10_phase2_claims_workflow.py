"""phase2_claims_workflow

Revision ID: 05757f236a10
Revises: 05757f236a0f
Create Date: 2026-06-11 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05757f236a10'
down_revision: Union[str, Sequence[str], None] = '05757f236a0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — fully idempotent."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'temple_claim_requests' not in tables:
        op.create_table(
            'temple_claim_requests',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('temple_id', sa.UUID(), nullable=False),
            sa.Column('claimant_id', sa.UUID(), nullable=False),
            sa.Column('status', sa.String(length=30), nullable=False, server_default='PENDING'),
            sa.Column('proof_urls', sa.JSON(), nullable=True),
            sa.Column('target_management_mode', sa.String(length=30), nullable=False, server_default='GOVERNED'),
            sa.Column('target_subscription_plan', sa.String(length=40), nullable=False, server_default='GOVERNED_STANDARD'),
            sa.Column('trial_duration_days', sa.Integer(), nullable=False, server_default='30'),
            sa.Column('claimant_notes', sa.Text(), nullable=True),
            sa.Column('reviewed_by', sa.UUID(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('rejection_reason', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['claimant_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        indexes = {idx['name'] for idx in inspector.get_indexes('temple_claim_requests')} if 'temple_claim_requests' in tables else set()
        if 'idx_claims_temple_status' not in indexes:
            op.create_index('idx_claims_temple_status', 'temple_claim_requests', ['temple_id', 'status'], unique=False)
        if 'idx_claims_claimant' not in indexes:
            op.create_index('idx_claims_claimant', 'temple_claim_requests', ['claimant_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_claims_claimant', table_name='temple_claim_requests')
    op.drop_index('idx_claims_temple_status', table_name='temple_claim_requests')
    op.drop_table('temple_claim_requests')
