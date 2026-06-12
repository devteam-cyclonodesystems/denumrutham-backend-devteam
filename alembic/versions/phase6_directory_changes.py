"""phase6 directory and search index changes

Revision ID: phase6_directory_changes
Revises: 48bd9fc73314, 05757f236a11
Create Date: 2026-06-11 23:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import datetime
import uuid

# revision identifiers, used by Alembic.
revision: str = 'phase6_directory_changes'
down_revision: Union[str, Sequence[str], None] = ('add_public_directory_indexes', '05757f236a11')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. Create state_master table
    if 'state_master' not in tables:
        op.create_table(
            'state_master',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False),
            sa.Column('code', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
            sa.UniqueConstraint('slug'),
            sa.UniqueConstraint('code')
        )
        op.create_index('idx_state_master_name', 'state_master', ['name'])
        op.create_index('idx_state_master_slug', 'state_master', ['slug'])

    # 2. Create district_master table
    if 'district_master' not in tables:
        op.create_table(
            'district_master',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('state_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False),
            sa.Column('code', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['state_id'], ['state_master.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('state_id', 'name', name='uq_state_district_name'),
            sa.UniqueConstraint('state_id', 'slug', name='uq_state_district_slug')
        )
        op.create_index('idx_district_master_name', 'district_master', ['name'])
        op.create_index('idx_district_master_slug', 'district_master', ['slug'])

    # 3. Add columns to temples table
    temple_columns = [c['name'] for c in inspector.get_columns('temples')]
    if 'state_id' not in temple_columns:
        op.add_column('temples', sa.Column('state_id', sa.UUID(), sa.ForeignKey('state_master.id', ondelete='SET NULL'), nullable=True))
    if 'district_id' not in temple_columns:
        op.add_column('temples', sa.Column('district_id', sa.UUID(), sa.ForeignKey('district_master.id', ondelete='SET NULL'), nullable=True))
    if 'verification_level' not in temple_columns:
        op.add_column('temples', sa.Column('verification_level', sa.Integer(), nullable=False, server_default='0'))
    if 'is_featured' not in temple_columns:
        op.add_column('temples', sa.Column('is_featured', sa.Boolean(), nullable=False, server_default='false'))

    # 4. Create temple_search_index table
    if 'temple_search_index' not in tables:
        op.create_table(
            'temple_search_index',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('temple_id', sa.UUID(), nullable=False),
            sa.Column('alternative_names', sa.Text(), nullable=False, server_default=''),
            sa.Column('keywords', sa.Text(), nullable=False, server_default=''),
            sa.Column('village', sa.String(), nullable=False, server_default=''),
            sa.Column('searchable_text', sa.Text(), nullable=False, server_default=''),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['temple_id'], ['temples.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('temple_id')
        )
        op.create_index('idx_temple_search_index_temple_id', 'temple_search_index', ['temple_id'])

    # 5. Seed default state and district data if empty
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    states = [
        {"id": "a0000000-0000-0000-0000-000000000001", "name": "Kerala", "slug": "kerala", "code": "KL", "created_at": now_dt},
        {"id": "a0000000-0000-0000-0000-000000000002", "name": "Tamil Nadu", "slug": "tamil-nadu", "code": "TN", "created_at": now_dt},
        {"id": "a0000000-0000-0000-0000-000000000003", "name": "Karnataka", "slug": "karnataka", "code": "KA", "created_at": now_dt},
        {"id": "a0000000-0000-0000-0000-000000000004", "name": "Andhra Pradesh", "slug": "andhra-pradesh", "code": "AP", "created_at": now_dt},
        {"id": "a0000000-0000-0000-0000-000000000005", "name": "Telangana", "slug": "telangana", "code": "TG", "created_at": now_dt}
    ]

    districts = [
        # Kerala
        {"id": "b0000000-0000-0000-0000-000000000001", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Thiruvananthapuram", "slug": "thiruvananthapuram", "code": "TVM", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000002", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Kollam", "slug": "kollam", "code": "KLM", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000003", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Pathanamthitta", "slug": "pathanamthitta", "code": "PTA", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000004", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Alappuzha", "slug": "alappuzha", "code": "ALP", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000005", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Kottayam", "slug": "kottayam", "code": "KTM", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000006", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Idukki", "slug": "idukki", "code": "IDK", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000007", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Ernakulam", "slug": "ernakulam", "code": "EKM", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000008", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Thrissur", "slug": "thrissur", "code": "TCR", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000009", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Palakkad", "slug": "palakkad", "code": "PKD", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000010", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Malappuram", "slug": "malappuram", "code": "MPM", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000011", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Kozhikode", "slug": "kozhikode", "code": "KKD", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000012", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Wayanad", "slug": "wayanad", "code": "WYD", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000013", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Kannur", "slug": "kannur", "code": "KNR", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000014", "state_id": "a0000000-0000-0000-0000-000000000001", "name": "Kasaragod", "slug": "kasaragod", "code": "KSD", "created_at": now_dt},
        # Tamil Nadu
        {"id": "b0000000-0000-0000-0000-000000000015", "state_id": "a0000000-0000-0000-0000-000000000002", "name": "Madurai", "slug": "madurai", "code": "MDU", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000016", "state_id": "a0000000-0000-0000-0000-000000000002", "name": "Chennai", "slug": "chennai", "code": "CHN", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000017", "state_id": "a0000000-0000-0000-0000-000000000002", "name": "Coimbatore", "slug": "coimbatore", "code": "CBE", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000018", "state_id": "a0000000-0000-0000-0000-000000000002", "name": "Kanyakumari", "slug": "kanyakumari", "code": "KK", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000019", "state_id": "a0000000-0000-0000-0000-000000000002", "name": "Thanjavur", "slug": "thanjavur", "code": "TJV", "created_at": now_dt},
        # Karnataka
        {"id": "b0000000-0000-0000-0000-000000000020", "state_id": "a0000000-0000-0000-0000-000000000003", "name": "Bengaluru", "slug": "bengaluru", "code": "BLR", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000021", "state_id": "a0000000-0000-0000-0000-000000000003", "name": "Mysuru", "slug": "mysuru", "code": "MYS", "created_at": now_dt},
        {"id": "b0000000-0000-0000-0000-000000000022", "state_id": "a0000000-0000-0000-0000-000000000003", "name": "Udupi", "slug": "udupi", "code": "UDp", "created_at": now_dt},
        # Andhra Pradesh
        {"id": "b0000000-0000-0000-0000-000000000023", "state_id": "a0000000-0000-0000-0000-000000000004", "name": "Tirupati", "slug": "tirupati", "code": "TPT", "created_at": now_dt},
        # Telangana
        {"id": "b0000000-0000-0000-0000-000000000024", "state_id": "a0000000-0000-0000-0000-000000000005", "name": "Hyderabad", "slug": "hyderabad", "code": "HYD", "created_at": now_dt}
    ]

    # Convert IDs to uuid.UUID objects
    for s in states:
        s["id"] = uuid.UUID(s["id"])
    for d in districts:
        d["id"] = uuid.UUID(d["id"])
        d["state_id"] = uuid.UUID(d["state_id"])

    # Insert states
    state_table = sa.table('state_master',
        sa.column('id', sa.UUID),
        sa.column('name', sa.String),
        sa.column('slug', sa.String),
        sa.column('code', sa.String),
        sa.column('created_at', sa.DateTime)
    )
    op.bulk_insert(state_table, states)

    # Insert districts
    district_table = sa.table('district_master',
        sa.column('id', sa.UUID),
        sa.column('state_id', sa.UUID),
        sa.column('name', sa.String),
        sa.column('slug', sa.String),
        sa.column('code', sa.String),
        sa.column('created_at', sa.DateTime)
    )
    op.bulk_insert(district_table, districts)

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. Drop temple_search_index
    if 'temple_search_index' in tables:
        op.drop_table('temple_search_index')

    # 2. Drop columns from temples
    temple_columns = [c['name'] for c in inspector.get_columns('temples')]
    if 'is_featured' in temple_columns:
        op.drop_column('temples', 'is_featured')
    if 'verification_level' in temple_columns:
        op.drop_column('temples', 'verification_level')
    if 'district_id' in temple_columns:
        op.drop_column('temples', 'district_id')
    if 'state_id' in temple_columns:
        op.drop_column('temples', 'state_id')

    # 3. Drop district_master
    if 'district_master' in tables:
        op.drop_table('district_master')

    # 4. Drop state_master
    if 'state_master' in tables:
        op.drop_table('state_master')
