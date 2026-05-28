"""
Phase 2 Validation — Controlled System Enhancement Tests.
Run inside Docker: docker compose exec -T app python /app/test_phase2.py
"""
import asyncio
import uuid

from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, TempleStatusAudit, User
from app.services.registration_service import RegistrationService
from app.services.temple_audit_service import TempleAuditService
from app.services.temple_rbac import can_modify_temple, can_change_status, can_delete_temple


async def run():
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.current_temple_id', 'SYSTEM', false)"))
        await db.execute(text("SELECT set_config('app.current_role', 'SUPER_ADMIN', false)"))

        # Get a real user for approver
        user_result = await db.execute(select(User).filter(User.role == "SUPER_ADMIN").limit(1))
        real_user = user_result.scalars().first()
        if not real_user:
            print("SKIP: No users in DB")
            return
        approver = real_user.id
        print(f"Using approver: {approver}")
        print()

        # ── Test 1: Audit completeness — changed_by populated ─────────
        t1_id = uuid.uuid4()
        t1 = Temple(id=t1_id, name=f"P2Test1-{t1_id}", domain=f"p2t1-{t1_id}", status="PENDING")
        db.add(t1)
        await db.commit()

        await RegistrationService.approve_temple(db, t1_id, approver)

        audit_result = await db.execute(
            select(TempleStatusAudit).filter(
                TempleStatusAudit.temple_id == t1_id,
                TempleStatusAudit.new_status == "APPROVED",
            )
        )
        audit = audit_result.scalars().first()
        if audit and audit.changed_by == approver:
            print("Test 1 (Audit changed_by populated): PASS")
        else:
            print(f"Test 1 (Audit changed_by populated): FAIL - got {audit.changed_by if audit else 'no audit'}")
        print()

        # ── Test 2: Domain separation — delete doesn't change status ──
        t2_id = uuid.uuid4()
        t2 = Temple(id=t2_id, name=f"P2Test2-{t2_id}", domain=f"p2t2-{t2_id}", status="APPROVED")
        db.add(t2)
        await db.commit()

        from app.services.superadmin_service import SuperAdminService
        await SuperAdminService.delete_temple(db, str(t2_id), deleted_by=str(approver), user_role="SUPER_ADMIN")

        # Refetch
        check = await db.execute(select(Temple).filter(Temple.id == t2_id))
        deleted_temple = check.scalars().first()
        if deleted_temple and deleted_temple.status == "APPROVED" and deleted_temple.is_active == False and deleted_temple.deleted_at is not None:
            print("Test 2 (Domain separation — status unchanged on delete): PASS")
            print(f"  status={deleted_temple.status}, is_active={deleted_temple.is_active}, deleted_at={deleted_temple.deleted_at}")
        else:
            s = deleted_temple.status if deleted_temple else "N/A"
            a = deleted_temple.is_active if deleted_temple else "N/A"
            print(f"Test 2 (Domain separation): FAIL - status={s}, is_active={a}")
        print()

        # ── Test 3: Event hooks (verify no exceptions) ────────────────
        from app.services.temple_events import emit_event, TEMPLE_CREATED, TEMPLE_STATUS_CHANGED, TEMPLE_DELETED
        try:
            emit_event(TEMPLE_CREATED, {"temple_id": "test", "name": "test"})
            emit_event(TEMPLE_STATUS_CHANGED, {"temple_id": "test", "old_status": "PENDING", "new_status": "APPROVED"})
            emit_event(TEMPLE_DELETED, {"temple_id": "test", "name": "test"})
            print("Test 3 (Event hooks fire without error): PASS")
        except Exception as e:
            print(f"Test 3 (Event hooks): FAIL - {e}")
        print()

        # ── Test 4: RBAC placeholders return True ─────────────────────
        r1 = can_modify_temple(approver, "SUPER_ADMIN", t1_id)
        r2 = can_change_status(approver, "SUPER_ADMIN", t1_id)
        r3 = can_delete_temple(approver, "SUPER_ADMIN", t1_id)
        if r1 and r2 and r3:
            print("Test 4 (RBAC placeholders all return True): PASS")
        else:
            print(f"Test 4 (RBAC placeholders): FAIL - {r1}, {r2}, {r3}")
        print()

        # ── Test 5: Audit history query service ───────────────────────
        history = await TempleAuditService.get_temple_audit_history(db, t1_id)
        if history["total"] > 0 and len(history["records"]) > 0:
            print(f"Test 5 (Audit history service): PASS — {history['total']} records")
            for rec in history["records"]:
                print(f"  {rec['old_status']} -> {rec['new_status']} by {rec['changed_by']} at {rec['changed_at']}")
        else:
            print("Test 5 (Audit history service): FAIL — no records")
        print()

        # ── Cleanup ───────────────────────────────────────────────────
        for tid in [t1_id, t2_id]:
            await db.execute(text(f"DELETE FROM temple_status_audit WHERE temple_id = '{tid}'"))
            await db.execute(text(f"DELETE FROM temples WHERE id = '{tid}'"))
        await db.commit()
        print("Cleanup done")


if __name__ == "__main__":
    asyncio.run(run())
