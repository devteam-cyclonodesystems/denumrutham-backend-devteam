"""seed additional permissions

Revision ID: hardening_pass_005_seed_additional_permissions
Revises: hardening_pass_004_procurement_ledger
Create Date: 2026-05-31 10:00:00.000000

"""
from typing import Sequence, Union
import uuid
from datetime import datetime
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'hardening_pass_005_seed_additional_permissions'
down_revision: Union[str, Sequence[str], None] = 'hardening_pass_004_procurement_ledger'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    connection = op.get_bind()
    now = datetime.utcnow()

    # 1. New permissions to seed
    new_perms = [
        ("tab", "offerings:view", "View Offerings Module"),
        ("tab", "communication:view", "View Communication Module"),
        ("tab", "activity-logs:view", "View Activity Logs"),
        ("tab", "workflows:view", "View Workflows Dashboard"),
    ]

    inserted_perm_ids = []
    for r_type, r_key, desc in new_perms:
        # Check if already exists
        res = connection.execute(
            sa.text("SELECT id FROM permissions WHERE resource_type = :r_type AND resource_key = :r_key"),
            {"r_type": r_type, "r_key": r_key}
        ).first()
        
        if res:
            perm_id = res[0]
            # Convert string id to UUID object if string returned
            if isinstance(perm_id, str):
                perm_id = uuid.UUID(perm_id)
        else:
            perm_id = uuid.uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO permissions (id, temple_id, resource_type, resource_key, description, created_at) "
                    "VALUES (:id, NULL, :r_type, :r_key, :desc, :created_at)"
                ),
                {"id": perm_id, "r_type": r_type, "r_key": r_key, "desc": desc, "created_at": now}
            )
        inserted_perm_ids.append(perm_id)

    # 2. Assign all current permissions to any role named 'Manager'
    # Fetch all Manager roles
    res_roles = connection.execute(
        sa.text("SELECT id, temple_id FROM roles WHERE name = 'Manager'")
    ).fetchall()

    # Fetch all permissions in the database
    res_all_perms = connection.execute(
        sa.text("SELECT id FROM permissions")
    ).fetchall()
    all_perm_ids = []
    for p in res_all_perms:
        pid = p[0]
        if isinstance(pid, str):
            pid = uuid.UUID(pid)
        all_perm_ids.append(pid)

    for r_row in res_roles:
        role_id = r_row[0]
        if isinstance(role_id, str):
            role_id = uuid.UUID(role_id)
            
        # Check existing assignments for this role
        res_existing_rp = connection.execute(
            sa.text("SELECT permission_id FROM role_permissions WHERE role_id = :role_id"),
            {"role_id": role_id}
        ).fetchall()
        
        existing_perm_ids = set()
        for rp in res_existing_rp:
            rpid = rp[0]
            if isinstance(rpid, str):
                rpid = uuid.UUID(rpid)
            existing_perm_ids.add(rpid)

        for perm_id in all_perm_ids:
            if perm_id not in existing_perm_ids:
                rp_id = uuid.uuid4()
                connection.execute(
                    sa.text(
                        "INSERT INTO role_permissions (id, role_id, permission_id, access_level, created_at) "
                        "VALUES (:id, :role_id, :perm_id, 'full', :created_at)"
                    ),
                    {"id": rp_id, "role_id": role_id, "perm_id": perm_id, "created_at": now}
                )

def downgrade() -> None:
    connection = op.get_bind()
    new_keys = ["offerings:view", "communication:view", "activity-logs:view", "workflows:view"]
    
    # Get permissions ids
    res_perms = connection.execute(
        sa.text("SELECT id FROM permissions WHERE resource_key IN :keys"),
        {"keys": tuple(new_keys)}
    ).fetchall()
    
    perm_ids = []
    for p in res_perms:
        pid = p[0]
        if isinstance(pid, str):
            pid = uuid.UUID(pid)
        perm_ids.append(pid)
    
    if perm_ids:
        # Delete mappings
        connection.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id IN :perm_ids"),
            {"perm_ids": tuple(perm_ids)}
        )
        # Delete permissions
        connection.execute(
            sa.text("DELETE FROM permissions WHERE id IN :perm_ids"),
            {"perm_ids": tuple(perm_ids)}
        )
