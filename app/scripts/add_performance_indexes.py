"""
Audit log performance indexes + notification indexes.
Safe to run on existing data — CREATE INDEX IF NOT EXISTS is idempotent.
"""
import asyncio
from sqlalchemy import text
from app.core.database import engine


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_module ON audit_logs(module_name);",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action_type);",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_approval_id ON audit_logs(approval_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_id);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_role ON notifications(role);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_approval_entity_status ON approval_requests(entity_id, module, status);",
]


async def apply_indexes():
    async with engine.begin() as conn:
        for ddl in INDEXES:
            print(f"  → {ddl.split('ON')[0].strip()}")
            await conn.execute(text(ddl))
    print("All indexes applied successfully.")


if __name__ == "__main__":
    asyncio.run(apply_indexes())
