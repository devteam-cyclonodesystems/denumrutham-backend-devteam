import sys
import os

try:
    from app.real_main import app
except BaseException as e:
    import traceback
    tb_str = traceback.format_exc()
    print(f"CRITICAL MAIN IMPORT ERROR: {tb_str}", file=sys.stderr)
    try:
        from sqlalchemy import create_engine, text
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("CRITICAL: DATABASE_URL not set. Skipping import error logging.", file=sys.stderr)
            raise e
        sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        sync_engine = create_engine(sync_url)
        with sync_engine.connect() as conn:
            import uuid
            conn.execute(
                text("""
                    INSERT INTO audit_integrity_verification_reports (id, temple_id, status, details, total_logs, failed_logs_count, verified_at)
                    VALUES (:id, :temple_id, :status, :details, 0, 0, NOW())
                """),
                {
                    "id": str(uuid.uuid4()),
                    "temple_id": "f96f45a1-d3a3-422f-9260-abfcd8df1aaa",
                    "status": "IMPORT_ERROR",
                    "details": f"Main Import Error:\n{tb_str}"
                }
            )
            conn.commit()
    except Exception as db_err:
        print(f"Failed to log import error to DB: {db_err}", file=sys.stderr)
    raise e
