import asyncio
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models.domain import User
from app.models.system_rbac import SystemRole, SystemPermission, SystemRolePermission

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_ROLES = [
    {"name": "SUPER_ADMIN", "description": "Full platform access", "is_system": True},
    {"name": "TEMPLE_ADMIN", "description": "Temple management access", "is_system": True},
    {"name": "STAFF", "description": "Temple staff access", "is_system": True},
    {"name": "DEVOTEE", "description": "Devotee portal access", "is_system": True},
]

SYSTEM_PERMISSIONS = [
    {"key": "APPROVE_TEMPLE", "description": "Approve/reject temple registrations", "is_sensitive": True},
    {"key": "REJECT_TEMPLE", "description": "Reject temple registrations", "is_sensitive": True},
    {"key": "CREATE_TEMPLE", "description": "Create temples directly", "is_sensitive": False},
    {"key": "EDIT_TEMPLE", "description": "Edit temple details", "is_sensitive": False},
    {"key": "DELETE_TEMPLE", "description": "Soft-delete temples", "is_sensitive": True},
    {"key": "MANAGE_ROLES", "description": "Create/edit system roles", "is_sensitive": True},
    {"key": "MANAGE_USERS", "description": "Manage user accounts", "is_sensitive": True},
    {"key": "MANAGE_BOOKINGS", "description": "Manage bookings", "is_sensitive": False},
    {"key": "UPLOAD_MEDIA", "description": "Upload temple media", "is_sensitive": False},
    {"key": "VIEW_DASHBOARD", "description": "View dashboard analytics", "is_sensitive": False},
    {"key": "BOOK_OFFERING", "description": "Book offerings/archana", "is_sensitive": False},
    {"key": "VIEW_TEMPLE", "description": "View temple public profile", "is_sensitive": False},
    {"key": "MANAGE_INVENTORY", "description": "Manage inventory", "is_sensitive": False},
    {"key": "MANAGE_EMPLOYEES", "description": "Manage HR/payroll", "is_sensitive": False},
    {"key": "MANAGE_HALL_BOOKINGS", "description": "Manage hall bookings", "is_sensitive": False},
    {"key": "VIEW_AUDIT_LOGS", "description": "View audit trail", "is_sensitive": False},
    {"key": "MANAGE_CHANGE_REQUESTS", "description": "Approve/reject change requests", "is_sensitive": False},
    {"key": "VIEW_ADMIN_DASHBOARD", "description": "View platform-level admin dashboard", "is_sensitive": True},
    # --- Staff Operational Permissions ---
    {"key": "MANAGE_ARCHANA", "description": "Manage archana bookings", "is_sensitive": False},
    {"key": "MANAGE_POOJA", "description": "Manage pooja bookings", "is_sensitive": False},
    {"key": "MANAGE_OFFERINGS", "description": "Manage temple offerings", "is_sensitive": False},
    {"key": "GENERATE_RECEIPTS", "description": "Generate financial receipts", "is_sensitive": False},
    {"key": "MANAGE_STORE", "description": "Manage store sales", "is_sensitive": False},
    {"key": "MANAGE_EXPENSES", "description": "Enter temple expenses", "is_sensitive": False},
    {"key": "MANAGE_DEVOTEES", "description": "Manage devotee records", "is_sensitive": False},
    {"key": "MANAGE_QUEUE", "description": "Manage darshan queue", "is_sensitive": False},
    {"key": "MANAGE_ANNOUNCEMENTS", "description": "Post temple announcements", "is_sensitive": False},
    {"key": "BROADCAST_MESSAGE", "description": "Send broadcast messages", "is_sensitive": False},
    {"key": "MANAGE_SCHEDULE", "description": "Manage temple timings/schedule", "is_sensitive": False},
    {"key": "MARK_ATTENDANCE", "description": "Mark employee attendance", "is_sensitive": False},
    {"key": "APPLY_LEAVE", "description": "Apply for leave", "is_sensitive": False},
    {"key": "VIEW_ATTENDANCE", "description": "View attendance records", "is_sensitive": False},
]

ROLE_PERMISSIONS_MAPPING = {
    # SUPER_ADMIN gets all implicitly in code, but we can explicitly map some if we want.
    # However, code logic typically grants ALL to SUPER_ADMIN. We'll map all just in case.
    "SUPER_ADMIN": [p["key"] for p in SYSTEM_PERMISSIONS],
    "TEMPLE_ADMIN": [
        "EDIT_TEMPLE", "MANAGE_BOOKINGS", "UPLOAD_MEDIA", "VIEW_DASHBOARD", 
        "MANAGE_INVENTORY", "MANAGE_EMPLOYEES", "MANAGE_HALL_BOOKINGS", 
        "VIEW_AUDIT_LOGS", "MANAGE_CHANGE_REQUESTS", "VIEW_TEMPLE", "MANAGE_USERS"
    ],
    "STAFF": [
        "VIEW_DASHBOARD", "VIEW_TEMPLE", "MANAGE_BOOKINGS",
        "MANAGE_ARCHANA", "MANAGE_POOJA", "MANAGE_OFFERINGS", "GENERATE_RECEIPTS",
        "MANAGE_STORE", "MANAGE_DEVOTEES", "MANAGE_QUEUE", "MANAGE_ANNOUNCEMENTS",
        "BROADCAST_MESSAGE", "MANAGE_SCHEDULE", "MARK_ATTENDANCE", "APPLY_LEAVE",
        "VIEW_ATTENDANCE", "MANAGE_INVENTORY"
    ],
    "DEVOTEE": [
        "BOOK_OFFERING", "VIEW_TEMPLE"
    ],
}

async def seed_system_rbac(db: AsyncSession):
    logger.info("Seeding system roles...")
    role_map = {}
    for r_data in SYSTEM_ROLES:
        result = await db.execute(select(SystemRole).filter_by(name=r_data["name"]))
        role = result.scalars().first()
        if not role:
            role = SystemRole(
                id=uuid.uuid4(),
                name=r_data["name"],
                description=r_data["description"],
                is_system=r_data["is_system"]
            )
            db.add(role)
            logger.info(f"Created role: {role.name}")
        role_map[role.name] = role
    await db.flush()

    logger.info("Seeding system permissions...")
    perm_map = {}
    for p_data in SYSTEM_PERMISSIONS:
        result = await db.execute(select(SystemPermission).filter_by(key=p_data["key"]))
        perm = result.scalars().first()
        if not perm:
            perm = SystemPermission(
                id=uuid.uuid4(),
                key=p_data["key"],
                description=p_data["description"],
                is_sensitive=p_data["is_sensitive"]
            )
            db.add(perm)
            logger.info(f"Created permission: {perm.key}")
        perm_map[perm.key] = perm
    await db.flush()

    logger.info("Mapping permissions to roles...")
    for role_name, perm_keys in ROLE_PERMISSIONS_MAPPING.items():
        role = role_map.get(role_name)
        if not role:
            continue
        for perm_key in perm_keys:
            perm = perm_map.get(perm_key)
            if not perm:
                continue
            
            # Check if mapping exists
            result = await db.execute(
                select(SystemRolePermission)
                .filter_by(role_id=role.id, permission_id=perm.id)
            )
            existing = result.scalars().first()
            if not existing:
                mapping = SystemRolePermission(
                    id=uuid.uuid4(),
                    role_id=role.id,
                    permission_id=perm.id
                )
                db.add(mapping)
    await db.flush()

    logger.info("Backfilling users with system_role_id...")
    users_result = await db.execute(select(User).filter(User.system_role_id.is_(None)))
    users = users_result.scalars().all()
    
    role_fallback_map = {
        "SUPERADMIN": "SUPER_ADMIN",
        "SUPER_ADMIN": "SUPER_ADMIN",
        "ADMIN": "TEMPLE_ADMIN",
        "TEMPLE_MANAGER": "TEMPLE_ADMIN",
        "STAFF": "STAFF",
        "DEVOTEE": "DEVOTEE"
    }
    
    backfill_count = 0
    for user in users:
        target_role_name = role_fallback_map.get(user.role.upper()) if user.role else "STAFF"
        target_role = role_map.get(target_role_name)
        if target_role:
            user.system_role_id = target_role.id
            backfill_count += 1
            
    logger.info(f"Backfilled {backfill_count} users with system roles.")
    
    await db.commit()
    logger.info("System RBAC seeding completed successfully.")

async def main():
    async with AsyncSessionLocal() as session:
        try:
            await seed_system_rbac(session)
        except Exception as e:
            logger.error(f"Error seeding RBAC: {e}")
            await session.rollback()

if __name__ == "__main__":
    asyncio.run(main())
