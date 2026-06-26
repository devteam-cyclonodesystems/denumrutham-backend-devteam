"""
Diagnostic script v2: identify the exact DB error causing /archana-bookings 500.
Each step uses a fresh session to avoid transaction abort cascade.

Run: cd backend && python -m app.scripts.diagnose_archana_500
"""
import asyncio
import traceback

TEMPLE_ID = "f96f45a1-d3a3-422f-9260-abfcd8df1aaa"

async def test_step(label, coro):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            result = await coro(db)
            print(f"  OK {label}: {result}")
        except Exception:
            print(f"  FAIL {label}:")
            traceback.print_exc()

async def main():
    print("=" * 70)
    print("Archana 500 Diagnosis - Testing each endpoint independently")
    print(f"Temple ID: {TEMPLE_ID}")
    print("=" * 70)

    # Step 1: Check promote_matured_bookings
    async def check_promote(db):
        from app.modules.bookings.services.archana_service import ArchanaService
        result = await ArchanaService.promote_matured_bookings(db, TEMPLE_ID)
        return f"promoted {result} bookings"
    await test_step("promote_matured_bookings", check_promote)

    # Step 2: Check get_queue
    async def check_queue(db):
        from app.modules.bookings.services.archana_service import ArchanaService
        result = await ArchanaService.get_queue(db, TEMPLE_ID)
        return f"returned {len(result)} queue entries"
    await test_step("get_queue", check_queue)

    # Step 3: Check get_kpis
    async def check_kpis(db):
        from app.modules.bookings.services.archana_service import ArchanaService
        result = await ArchanaService.get_kpis(db, TEMPLE_ID)
        return f"returned kpis: {result}"
    await test_step("get_kpis", check_kpis)

    # Step 4: Check get_financial_kpis
    async def check_fin_kpis(db):
        from app.modules.billing.services.accounting_service import AccountingService
        from uuid import UUID
        result = await AccountingService.get_financial_kpis(db, UUID(TEMPLE_ID))
        return f"returned: {result}"
    await test_step("get_financial_kpis", check_fin_kpis)

    # Step 5: Check get_bookings
    async def check_bookings(db):
        from app.modules.bookings.services.archana_service import ArchanaService
        result = await ArchanaService.get_bookings(db, TEMPLE_ID, skip=0, limit=5)
        return f"returned {len(result)} bookings"
    await test_step("get_bookings", check_bookings)

    # Step 6: Check full /kpis endpoint flow (promote + get_kpis + get_financial_kpis)
    async def check_full_kpis_endpoint(db):
        from app.modules.bookings.services.archana_service import ArchanaService
        from app.modules.billing.services.accounting_service import AccountingService
        from uuid import UUID
        await ArchanaService.promote_matured_bookings(db, TEMPLE_ID)
        data = await ArchanaService.get_kpis(db, TEMPLE_ID)
        fin_kpis = await AccountingService.get_financial_kpis(db, UUID(TEMPLE_ID))
        data.update(fin_kpis)
        return f"full kpis response: {list(data.keys())}"
    await test_step("full_kpis_endpoint", check_full_kpis_endpoint)

    # Step 7: Check full /queue endpoint flow
    async def check_full_queue_endpoint(db):
        from app.modules.bookings.services.archana_service import ArchanaService
        await ArchanaService.promote_matured_bookings(db, TEMPLE_ID)
        data = await ArchanaService.get_queue(db, TEMPLE_ID)
        return f"queue response: {len(data)} entries"
    await test_step("full_queue_endpoint", check_full_queue_endpoint)

    print()
    print("=" * 70)
    print("Diagnosis complete.")

if __name__ == "__main__":
    asyncio.run(main())
