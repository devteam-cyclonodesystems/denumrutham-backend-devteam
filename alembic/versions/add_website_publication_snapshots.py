"""add website publication snapshots

Revision ID: add_website_publication_snapshots
Revises: 8b32f4ee0d89
Create Date: 2026-06-07 11:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.types import JSON
import json
from datetime import datetime, timezone

# revision identifiers, used by Alembic.
revision: str = 'add_website_publication_snapshots'
down_revision: Union[str, Sequence[str], None] = '8b32f4ee0d89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Create the temple_website_settings_live table
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    # Define JSONB variant conditionally for PostgreSQL vs SQLite
    json_type = JSONB().with_variant(sa.JSON, "sqlite")
    
    if 'temple_website_settings_live' not in tables:
        op.create_table(
            'temple_website_settings_live',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('temple_id', sa.UUID(), nullable=False),
            sa.Column('settings_snapshot', json_type, nullable=False),
            sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('status', sa.String(), nullable=False, server_default='PUBLISHED'),
            sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('published_by', sa.UUID(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['published_by'], ['users.id'], ondelete='SET NULL')
        )
        op.create_index('ix_temple_website_settings_live_temple_id', 'temple_website_settings_live', ['temple_id'], unique=True)
        
    # 2. Perform safe data migration for existing active, approved temples
    try:
        connection = op.get_bind()
        temples = connection.execute(sa.text(
            "SELECT id, name, domain FROM temples WHERE is_active = True AND status = 'APPROVED'"
        )).fetchall()
        
        for temple in temples:
            temple_id, name, domain = temple
            
            # Check if domain matches slug regex
            import re
            if not domain or not re.match(r"^[a-z0-9-]+$", str(domain)):
                print(f"[Migration Warning] Skipping publication migration for temple '{name}' (ID: {temple_id}) due to invalid/missing slug: '{domain}'")
                continue
                
            # Fetch draft settings
            settings_row = connection.execute(sa.text(
                "SELECT theme_name, primary_color, secondary_color, logo_url, hero_layout, section_order, "
                "enable_mantras, enable_festivals, enable_donations, enable_hall_booking, enable_store, "
                "seo_keywords, og_image_url, hero_title, hero_subtitle, seo_description, notice_board_content "
                "FROM temple_website_settings WHERE temple_id = :tid"
            ), {"tid": str(temple_id)}).fetchone()
            
            if not settings_row:
                print(f"[Migration Warning] Skipping publication migration for temple '{name}' (ID: {temple_id}) due to missing settings row.")
                continue
                
            def safe_json_load(val):
                if isinstance(val, str):
                    try:
                        return json.loads(val)
                    except Exception:
                        return val
                return val

            # Serialize using explicit snapshot contract
            snapshot = {
                "theme_name": settings_row[0] or "default",
                "primary_color": settings_row[1] or "#ff6600",
                "secondary_color": settings_row[2] or "#ffcc00",
                "logo_url": settings_row[3],
                "hero_layout": settings_row[4] or "split",
                "section_order": safe_json_load(settings_row[5]) or ["hero", "about", "deities", "announcements", "activities", "gallery", "offerings", "location"],
                "enable_mantras": bool(settings_row[6]) if settings_row[6] is not None else True,
                "enable_festivals": bool(settings_row[7]) if settings_row[7] is not None else True,
                "enable_donations": bool(settings_row[8]) if settings_row[8] is not None else True,
                "enable_hall_booking": bool(settings_row[9]) if settings_row[9] is not None else True,
                "enable_store": bool(settings_row[10]) if settings_row[10] is not None else True,
                "seo_keywords": settings_row[11],
                "og_image_url": settings_row[12],
                "hero_title": settings_row[13],
                "hero_subtitle": settings_row[14],
                "seo_description": settings_row[15],
                "notice_board_content": safe_json_load(settings_row[16])
            }
            
            # Insert live snapshot
            import uuid as uuid_mod
            live_id = str(uuid_mod.uuid4())
            connection.execute(sa.text(
                "INSERT INTO temple_website_settings_live "
                "(id, temple_id, settings_snapshot, schema_version, version, status, published_at, published_by) "
                "VALUES (:id, :tid, :snapshot, 1, 1, 'PUBLISHED', :pub_at, NULL)"
            ), {
                "id": live_id,
                "tid": str(temple_id),
                "snapshot": json.dumps(snapshot),
                "pub_at": datetime.now(timezone.utc)
            })
            print(f"[Migration SUCCESS] Created live publication snapshot for temple '{name}' (ID: {temple_id}, Domain: {domain})")
            
    except Exception as e:
        print(f"[Migration Error] Safe data migration skipped or failed: {str(e)}")

def downgrade() -> None:
    op.drop_table('temple_website_settings_live')
