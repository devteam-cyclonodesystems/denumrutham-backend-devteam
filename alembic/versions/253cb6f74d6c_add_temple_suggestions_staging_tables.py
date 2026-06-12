"""Add temple suggestions staging tables

Revision ID: 253cb6f74d6c
Revises: phase6_directory_changes
Create Date: 2026-06-12 20:27:39.580269

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '253cb6f74d6c'
down_revision: Union[str, Sequence[str], None] = 'phase6_directory_changes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('temple_suggestions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('reference_number', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('deity', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('address_line_1', sa.String(), nullable=False),
        sa.Column('address_line_2', sa.String(), nullable=True),
        sa.Column('village_town', sa.String(length=150), nullable=False),
        sa.Column('district_id', sa.UUID(), nullable=False),
        sa.Column('state_id', sa.UUID(), nullable=False),
        sa.Column('pincode', sa.String(length=10), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('google_maps_url', sa.String(length=512), nullable=True),
        sa.Column('website', sa.String(length=255), nullable=True),
        sa.Column('social_media_links', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('festival_info', sa.Text(), nullable=True),
        sa.Column('office_phone', sa.String(length=30), nullable=True),
        sa.Column('submitter_affiliation', sa.String(length=50), nullable=False),
        sa.Column('submitted_by', sa.UUID(), nullable=False),
        sa.Column('submitter_ip', sa.String(length=45), nullable=True),
        sa.Column('confidence_score', sa.Integer(), nullable=False),
        sa.Column('original_submission_json', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='PENDING'),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('moderator_notes', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('promoted_temple_id', sa.UUID(), nullable=True),
        sa.Column('merged_temple_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['district_id'], ['district_master.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['merged_temple_id'], ['temples.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['promoted_temple_id'], ['temples.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['state_id'], ['state_master.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_temple_suggestions_district_id'), 'temple_suggestions', ['district_id'], unique=False)
    op.create_index(op.f('ix_temple_suggestions_reference_number'), 'temple_suggestions', ['reference_number'], unique=True)
    op.create_index(op.f('ix_temple_suggestions_state_id'), 'temple_suggestions', ['state_id'], unique=False)
    op.create_index(op.f('ix_temple_suggestions_status'), 'temple_suggestions', ['status'], unique=False)
    op.create_index(op.f('ix_temple_suggestions_submitted_by'), 'temple_suggestions', ['submitted_by'], unique=False)

    op.create_table('temple_suggestion_audits',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('suggestion_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('performed_by', sa.UUID(), nullable=False),
        sa.Column('change_diff', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['performed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['suggestion_id'], ['temple_suggestions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_temple_suggestion_audits_suggestion_id'), 'temple_suggestion_audits', ['suggestion_id'], unique=False)

    op.create_table('temple_suggestion_contacts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('suggestion_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('designation', sa.String(length=150), nullable=False),
        sa.Column('mobile_number', sa.String(length=20), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['suggestion_id'], ['temple_suggestions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_temple_suggestion_contacts_suggestion_id'), 'temple_suggestion_contacts', ['suggestion_id'], unique=False)

    op.create_table('temple_suggestion_images',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('suggestion_id', sa.UUID(), nullable=False),
        sa.Column('image_url', sa.String(length=512), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['suggestion_id'], ['temple_suggestions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_temple_suggestion_images_suggestion_id'), 'temple_suggestion_images', ['suggestion_id'], unique=False)

    # Add columns to temples table
    op.add_column('temples', sa.Column('creation_source', sa.String(length=50), server_default='SUPERADMIN_CREATED', nullable=False))
    op.add_column('temples', sa.Column('source_suggestion_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_temples_source_suggestion_id', 'temples', 'temple_suggestions', ['source_suggestion_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_temples_source_suggestion_id', 'temples', type_='foreignkey')
    op.drop_column('temples', 'source_suggestion_id')
    op.drop_column('temples', 'creation_source')
    
    op.drop_index(op.f('ix_temple_suggestion_images_suggestion_id'), table_name='temple_suggestion_images')
    op.drop_table('temple_suggestion_images')
    op.drop_index(op.f('ix_temple_suggestion_contacts_suggestion_id'), table_name='temple_suggestion_contacts')
    op.drop_table('temple_suggestion_contacts')
    op.drop_index(op.f('ix_temple_suggestion_audits_suggestion_id'), table_name='temple_suggestion_audits')
    op.drop_table('temple_suggestion_audits')
    op.drop_index(op.f('ix_temple_suggestions_submitted_by'), table_name='temple_suggestions')
    op.drop_index(op.f('ix_temple_suggestions_status'), table_name='temple_suggestions')
    op.drop_index(op.f('ix_temple_suggestions_state_id'), table_name='temple_suggestions')
    op.drop_index(op.f('ix_temple_suggestions_reference_number'), table_name='temple_suggestions')
    op.drop_index(op.f('ix_temple_suggestions_district_id'), table_name='temple_suggestions')
    op.drop_table('temple_suggestions')
