"""create audit governance config table

Revision ID: e6ad20f0
Revises: fde8020f
Create Date: 2026-06-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6ad20f0'
down_revision: Union[str, Sequence[str], None] = 'fde8020f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('audit_governance_configs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('retention_days', sa.Integer(), nullable=False, server_default='365'),
        sa.Column('export_policy', sa.JSON(), nullable=True),
        sa.Column('severity_mapping', sa.JSON(), nullable=True),
        sa.Column('alert_thresholds', sa.JSON(), nullable=True),
        sa.Column('access_controls', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ),
        sa.UniqueConstraint('temple_id', name='uq_audit_governance_configs_temple_id')
    )
    op.create_index(op.f('ix_audit_governance_configs_temple_id'), 'audit_governance_configs', ['temple_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_governance_configs_temple_id'), table_name='audit_governance_configs')
    op.drop_table('audit_governance_configs')
