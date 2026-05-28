import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import text, delete

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import AsyncSessionLocal
from app.models.domain import (
    Temple, User, AuditLog, Transaction, Booking, Devotee, Pooja, 
    PoojaSlot, Donation, InventoryItem, InventoryMovement, Event, 
    Ticket, Payment, ApprovalRequest, Notification, TempleProfile, 
    TempleProfileDraft, TempleImage, TempleService, ServiceBooking, 
    Hall, HallBooking, Employee, Leave, ArchanaBooking, Supplier, 
    InventoryInvoice, InventoryItemRequest, InventoryTransaction, 
    ChangeRequest, TempleFollower, Cart, CartItem, Address, UserTemple
)
from app.models.rbac import Role, Permission, RolePermission, UserRole

async def system_reset():
    print("=" * 60)
    print("  TMS SAFE SYSTEM RESET")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        # PHASE 1: Dependency Analysis
        
        print("Finding SuperAdmin...")
        result = await db.execute(select(User).filter(User.user_id == "superadmin"))
        super_admin = result.scalars().first()
        if not super_admin:
            result = await db.execute(select(User).filter(User.role.in_(["SUPERADMIN", "SUPER_ADMIN"])))
            super_admin = result.scalars().first()
        
        if super_admin:
            print(f"Found SuperAdmin: {super_admin.user_id} (ID: {super_admin.id})")
            super_admin_id = super_admin.id
        else:
            print("WARNING: SuperAdmin not found!")
            super_admin_id = None

        # PHASE 2: Safe Cleanup Strategy
        
        raw_tables = [
            "user_roles", "role_permissions", "roles", "permissions",
            "staff_invites", "temple_domain_history", "temple_requests", 
            "user_requests", "temple_status_audit", "temple_code_sequences",
            "password_reset_tokens", "guest_bookings", "audit_logs"
        ]

        print("Clearing raw/RBAC tables...")
        for table_name in raw_tables:
            try:
                # Use a separate transaction for each cleanup to avoid aborting the whole block
                await db.execute(text(f"DELETE FROM {table_name}"))
                print(f"  [OK] Cleared {table_name}")
            except Exception as e:
                print(f"  [SKIP] {table_name}: {e}")
                await db.rollback() # Rollback the sub-transaction failure

        tables_to_clear = [
            InventoryTransaction, InventoryMovement, CartItem, 
            Ticket, Payment, Leave, HallBooking, 
            InventoryItemRequest, InventoryInvoice, 
            Cart, ServiceBooking, ArchanaBooking, 
            PoojaSlot, Booking, Donation, 
            InventoryItem, Pooja, Devotee, Hall, Employee, 
            Supplier, ChangeRequest, TempleFollower, 
            TempleImage, TempleProfileDraft, TempleProfile, 
            TempleService, ApprovalRequest, Notification, 
            Transaction, UserTemple, 
        ]

        print("Clearing child tables...")
        for table in tables_to_clear:
            try:
                await db.execute(delete(table))
                print(f"  [OK] Cleared {table.__tablename__}")
            except Exception as e:
                print(f"  [ERROR] clearing {table.__tablename__}: {e}")
                await db.rollback()
        
        print("Clearing temple association from users...")
        try:
            await db.execute(text("UPDATE users SET temple_id = NULL"))
            print("  [OK] Updated users")
        except Exception as e:
            print(f"  [ERROR] updating users: {e}")
            await db.rollback()
        
        # PHASE 3: Sequence Reset & Temple Deletion
        print("Deleting temples...")
        try:
            await db.execute(delete(Temple))
            print("  [OK] Deleted temples")
        except Exception as e:
            print(f"  [ERROR] deleting temples: {e}")
            await db.rollback()

        # Commit deletions before creating fresh data
        await db.commit()

        # Reset sequences
        print("Resetting sequences...")
        try:
            await db.execute(text("ALTER SEQUENCE temples_id_seq RESTART WITH 1"))
            print("  [OK] Reset temples_id_seq")
            await db.commit()
        except Exception as e:
            # print(f"  [INFO] Could not reset temples_id_seq: {e}")
            await db.rollback()

        # PHASE 6: Fresh Data Creation
        print("Creating fresh test data...")
        try:
            test_temple = Temple(
                id=uuid.uuid4(),
                name="Test Temple",
                domain="test-temple",
                status="APPROVED",
                is_active=True,
                created_by=super_admin_id
            )
            db.add(test_temple)
            await db.flush()
            
            test_profile = TempleProfile(
                temple_id=test_temple.id,
                description="Fresh test temple for system validation.",
                location="Test City",
                state="Test State"
            )
            db.add(test_profile)

            await db.commit()
            print(f"[SUCCESS] Created fresh temple: {test_temple.name} ({test_temple.id})")
        except Exception as e:
            print(f"[ERROR] failed to create fresh data: {e}")
            await db.rollback()

        # PHASE 5: Post-Reset Validation
        print("-" * 30)
        print("VALIDATION RESULTS:")
        try:
            t_count = await db.execute(text("SELECT COUNT(*) FROM temples"))
            print(f"  Temples count: {t_count.scalar()}")
            
            u_count = await db.execute(text("SELECT COUNT(*) FROM users"))
            print(f"  Users preserved: {u_count.scalar()}")
            
            b_count = await db.execute(text("SELECT COUNT(*) FROM bookings"))
            print(f"  Bookings count: {b_count.scalar()}")
        except Exception as e:
            print(f"  Validation failed: {e}")
        
        print("-" * 30)
        print("SAFE SYSTEM RESET COMPLETE.")

if __name__ == "__main__":
    asyncio.run(system_reset())
