import asyncio
from uuid import UUID
from app.core.database import AsyncSessionLocal
from app.modules.bookings.services.archana_lifecycle_service import ArchanaLifecycleService

async def debug():
    async with AsyncSessionLocal() as db:
        # Just pass dummy UUIDs, it should fail with a database error if there's a schema issue,
        # or NOT_FOUND if it works correctly but finds no records.
        try:
            print("Trying to start grouped rituals...")
            await ArchanaLifecycleService.start_grouped_rituals(
                db=db,
                execution_ids=[UUID('00000000-0000-0000-0000-000000000001')],
                priest_id=UUID('00000000-0000-0000-0000-000000000002'),
                actor_id=UUID('00000000-0000-0000-0000-000000000003'),
                temple_id=UUID('00000000-0000-0000-0000-000000000004')
            )
            print("Success")
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug())
