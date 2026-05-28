"""
Validation script for temple status machine hardening.
Run inside the Docker container:
  docker compose exec -T app python /app/test_status_machine.py
"""
import asyncio
import uuid

from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, TempleStatusAudit, User


async def run():
    async with AsyncSessionLocal() as db:
        # Set RLS context for system
        await db.execute(text("SELECT set_config('app.current_temple_id', 'SYSTEM', false)"))
        await db.execute(text("SELECT set_config('app.current_role', 'SUPER_ADMIN', false)"))

        # Get a real user ID from the DB for the approver
        user_result = await db.execute(select(User).limit(1))
        real_user = user_result.scalars().first()
        if not real_user:
            print("SKIP: No users in DB to use as approver")
            return
        approver = real_user.id
        print(f"Using approver: {approver}")

        from app.services.registration_service import RegistrationService

        # Test 1: PENDING -> APPROVED (should PASS)
        t1_id = uuid.uuid4()
        t1 = Temple(id=t1_id, name=f"HTest1-{t1_id}", domain=f"htest1-{t1_id}", status="PENDING")
        db.add(t1)
        await db.commit()
        try:
            await RegistrationService.approve_temple(db, t1_id, approver)
            print("Test 1 (PENDING -> APPROVED): PASS")
        except Exception as e:
            await db.rollback()
            print(f"Test 1 (PENDING -> APPROVED): FAIL - {e}")

        # Test 2: PENDING -> REJECTED (should PASS)
        t2_id = uuid.uuid4()
        t2 = Temple(id=t2_id, name=f"HTest2-{t2_id}", domain=f"htest2-{t2_id}", status="PENDING")
        db.add(t2)
        await db.commit()
        try:
            await RegistrationService.reject_temple(db, t2_id, approver)
            print("Test 2 (PENDING -> REJECTED): PASS")
        except Exception as e:
            await db.rollback()
            print(f"Test 2 (PENDING -> REJECTED): FAIL - {e}")

        # Test 3: APPROVED -> APPROVED (should FAIL — terminal state)
        t3_id = uuid.uuid4()
        t3 = Temple(id=t3_id, name=f"HTest3-{t3_id}", domain=f"htest3-{t3_id}", status="APPROVED")
        db.add(t3)
        await db.commit()
        try:
            await RegistrationService.approve_temple(db, t3_id, approver)
            print("Test 3 (APPROVED -> APPROVED): FAIL - should have raised")
        except Exception as e:
            await db.rollback()
            print(f"Test 3 (APPROVED -> APPROVED blocked): PASS - {e}")

        # Test 4: REJECTED -> APPROVED (should FAIL — terminal state)
        t4_id = uuid.uuid4()
        t4 = Temple(id=t4_id, name=f"HTest4-{t4_id}", domain=f"htest4-{t4_id}", status="REJECTED")
        db.add(t4)
        await db.commit()
        try:
            await RegistrationService.approve_temple(db, t4_id, approver)
            print("Test 4 (REJECTED -> APPROVED): FAIL - should have raised")
        except Exception as e:
            await db.rollback()
            print(f"Test 4 (REJECTED -> APPROVED blocked): PASS - {e}")

        # Test 5: Verify audit records exist for valid transitions
        result = await db.execute(
            select(TempleStatusAudit).filter(TempleStatusAudit.temple_id.in_([t1_id, t2_id]))
        )
        audits = result.scalars().all()
        status = "PASS" if len(audits) == 2 else "FAIL"
        print(f"Test 5 (Audit records): {len(audits)} audit records for 2 valid transitions -> {status}")

        # Test 6: NULL status blocked at DB level
        try:
            await db.execute(
                text("INSERT INTO temples (id, name, domain, status) VALUES (:id, :n, :d, NULL)"),
                {"id": str(uuid.uuid4()), "n": f"NullTest-{uuid.uuid4()}", "d": f"nulltest-{uuid.uuid4()}"},
            )
            await db.commit()
            print("Test 6 (NULL status blocked): FAIL - insert succeeded")
        except Exception as e:
            await db.rollback()
            print(f"Test 6 (NULL status blocked): PASS - {type(e).__name__}")

        # Cleanup test data
        for tid in [t1_id, t2_id, t3_id, t4_id]:
            await db.execute(text(f"DELETE FROM temple_status_audit WHERE temple_id = '{tid}'"))
            await db.execute(text(f"DELETE FROM temples WHERE id = '{tid}'"))
        await db.commit()
        print("Cleanup done")


if __name__ == "__main__":
    asyncio.run(run())

