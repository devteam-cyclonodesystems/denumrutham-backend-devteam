"""add_audit_chain_versioning_and_registry

Revision ID: 8b32f4ee0d89
Revises: c2c4d088f2c4
Create Date: 2026-06-06 13:28:32.148400

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8b32f4ee0d89'
down_revision: Union[str, Sequence[str], None] = 'c2c4d088f2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create audit_chain_incidents table
    op.create_table(
        'audit_chain_incidents',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('chain_version', sa.Integer(), nullable=False),
        sa.Column('incident_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='HIGH'),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('root_cause', sa.Text(), nullable=False),
        sa.Column('evidence_reference', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('resolution_summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='OPEN'),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 2. Create partial unique index on audit_chain_incidents for OPEN status
    op.create_index(
        'uq_temple_incident',
        'audit_chain_incidents',
        ['temple_id', 'chain_version'],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'")
    )

    # 3. Create audit_chain_versions table
    op.create_table(
        'audit_chain_versions',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('chain_version', sa.Integer(), nullable=False),
        sa.Column('chain_status', sa.String(20), nullable=False, server_default='ACTIVE'),
        sa.Column('verification_status', sa.String(20), nullable=False, server_default='PASS'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('sealed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('seal_reason', sa.Text(), nullable=True),
        sa.Column('parent_chain_version', sa.Integer(), nullable=True),
        sa.Column('parent_terminal_hash', sa.String(64), nullable=True),
        sa.Column('incident_id', sa.UUID(), nullable=True),
        sa.Column('recovery_method', sa.String(50), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['incident_id'], ['audit_chain_incidents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('temple_id', 'chain_version', name='uq_temple_chain_version'),
        sa.CheckConstraint("chain_status IN ('ACTIVE', 'SEALED')", name='chk_status'),
        sa.CheckConstraint("verification_status IN ('PASS', 'FAIL')", name='chk_verification')
    )

    # 4. Create partial unique index on audit_chain_versions for ACTIVE chain
    op.create_index(
        'idx_temple_active_chain',
        'audit_chain_versions',
        ['temple_id'],
        unique=True,
        postgresql_where=sa.text("chain_status = 'ACTIVE'")
    )

    # 5. Create audit_chain_index_registry table
    op.create_table(
        'audit_chain_index_registry',
        sa.Column('temple_id', sa.UUID(), nullable=False),
        sa.Column('audit_chain_index', sa.BigInteger(), nullable=False),
        sa.Column('created_utc', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('temple_id', 'audit_chain_index', name='pk_audit_chain_index_registry')
    )

    # 6. Add chain_version to partitioned immutable_activity_logs table
    op.add_column('immutable_activity_logs', sa.Column('chain_version', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    # Remove columns and tables in reverse order of creation
    op.drop_column('immutable_activity_logs', 'chain_version')
    op.drop_table('audit_chain_index_registry')
    op.drop_index('idx_temple_active_chain', table_name='audit_chain_versions')
    op.drop_table('audit_chain_versions')
    op.drop_index('uq_temple_incident', table_name='audit_chain_incidents')
    op.drop_table('audit_chain_incidents')
