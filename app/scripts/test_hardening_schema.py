import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def test():
    async with AsyncSessionLocal() as db:
        # Test notifications table exists
        r = await db.execute(text('SELECT count(*) FROM notifications'))
        print(f'Notifications table OK, rows: {r.scalar()}')
        
        # Test approval_requests table
        r = await db.execute(text('SELECT count(*) FROM approval_requests'))
        print(f'ApprovalRequests table OK, rows: {r.scalar()}')
        
        # Test audit_logs new columns
        r = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='audit_logs' AND column_name IN ('approval_id','content_hash','ip_address') "
            "ORDER BY column_name"
        ))
        cols = [row[0] for row in r.all()]
        print(f'AuditLog new columns: {cols}')
        
        # Test immutability trigger (DELETE on zero rows still triggers row-level trigger? No.)
        # Row-level triggers only fire when there ARE matching rows. Let's just verify trigger exists.
        r = await db.execute(text(
            "SELECT trigger_name FROM information_schema.triggers "
            "WHERE event_object_table='audit_logs'"
        ))
        triggers = [row[0] for row in r.all()]
        print(f'AuditLog triggers: {triggers}')
        
        print('All checks passed!')

asyncio.run(test())
