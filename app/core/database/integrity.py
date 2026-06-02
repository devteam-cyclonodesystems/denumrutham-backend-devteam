
import logging
import os
import subprocess
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import engine, AsyncSessionLocal
from app.modules.governance.models.operational_states import TempleOperationalState

logger = logging.getLogger("tms.integrity")

class DeploymentIntegrityService:
    @staticmethod
    def get_build_info() -> Dict[str, str]:
        """Capture git and build metadata."""
        try:
            # Note: In a container, we might rely on environment variables injected during build
            git_commit = os.getenv("GIT_COMMIT") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("COMMIT_SHA")
            if not git_commit:
                git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.STDOUT).decode().strip()
        except:
            git_commit = "unknown"
            
        return {
            "git_commit": git_commit,
            "build_timestamp": os.getenv("BUILD_TIMESTAMP", datetime.utcnow().isoformat()),
            "version": settings.VERSION,
            "environment": os.getenv("ENVIRONMENT", "production"),
            "container_id": os.getenv("HOSTNAME", "unknown")
        }

    @staticmethod
    async def validate_runtime_schema() -> bool:
        """
        Phase 5: Runtime Schema Validation.
        Checks for tables, columns, and critical ENUM types.
        """
        if engine.dialect.name == "sqlite":
            logger.info("Skipping runtime schema validation for SQLite database.")
            return True
            
        logger.info("Starting Runtime Schema Validation...")
        
        # 0. Ensure system tables exist (Phase 7 & 8)
        from app.models.system import ProcessedEvent, SyncCheckpoint, ConflictReport
        from app.models.domain import SupplierPriceHistory
        from app.db.session import Base
        
        def _get_tables(conn):
            return inspect(conn).get_table_names()

        async with engine.connect() as conn:
            existing_tables = await conn.run_sync(_get_tables)
            
            tables_to_create = []
            for model in [ProcessedEvent, SyncCheckpoint, ConflictReport, SupplierPriceHistory]:
                if model.__tablename__ not in existing_tables:
                    tables_to_create.append(model.__table__)
            
            if tables_to_create:
                logger.info(f"Creating missing system tables: {[t.name for t in tables_to_create]}")
                try:
                    # We need a fresh connection with begin() for DDL
                    async with engine.begin() as create_conn:
                        await create_conn.run_sync(Base.metadata.create_all, tables=tables_to_create)
                except Exception as e:
                    # If multiple workers try to create at the same time, one will win, others will fail.
                    # We log it and continue, as the first one likely succeeded.
                    logger.warning(f"Note: Table creation attempted by multiple workers. Continuing. Detail: {str(e)}")

        required_tables = [
            "temples", "users", "operational_state_audits", "audit_logs", 
            "security_audit_events", "alembic_version",
            "processed_events", "sync_checkpoints", "conflict_reports"
        ]
        
        required_enums = {
            "templeoperationalstate": [e.value for e in TempleOperationalState]
        }

        async with engine.connect() as conn:
            # 1. Check Tables
            for table in required_tables:
                result = await conn.execute(
                    text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)"),
                    {"t": table}
                )
                if not result.scalar():
                    logger.critical(f"INTEGRITY FAILURE: Missing critical table '{table}'")
                    return False

            # 2. Check ENUMs
            for enum_name, expected_values in required_enums.items():
                result = await conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = :e)"),
                    {"e": enum_name}
                )
                if not result.scalar():
                    logger.critical(f"INTEGRITY FAILURE: Missing critical ENUM type '{enum_name}'")
                    return False
                
                # Check enum values
                val_result = await conn.execute(
                    text("SELECT enumlabel FROM pg_enum WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = :e)"),
                    {"e": enum_name}
                )
                actual_values = [r[0] for r in val_result.fetchall()]
                for val in expected_values:
                    if val not in actual_values:
                        logger.warning(f"INTEGRITY WARNING: ENUM '{enum_name}' missing value '{val}'")

            # 3. Check Critical Columns
            # Example: Check for operational_state in temples
            res = await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'temples' AND column_name = 'operational_state'")
            )
            if not res.scalar():
                logger.critical("INTEGRITY FAILURE: Missing column 'operational_state' in 'temples'")
                return False

            # Verify created_from_supplier column in kalavara_inventory_items
            res_cf = await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'kalavara_inventory_items' AND column_name = 'created_from_supplier'")
            )
            if not res_cf.scalar():
                logger.critical("INTEGRITY FAILURE: Missing column 'created_from_supplier' in 'kalavara_inventory_items'")
                return False

            # Verify min_stock_source column in kalavara_inventory_items
            res_ms = await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'kalavara_inventory_items' AND column_name = 'min_stock_source'")
            )
            if not res_ms.scalar():
                logger.critical("INTEGRITY FAILURE: Missing column 'min_stock_source' in 'kalavara_inventory_items'")
                return False

        logger.info("Runtime Schema Validation PASSED.")
        return True

    @staticmethod
    async def get_integrity_status() -> Dict[str, Any]:
        """Phase 1: Deployment Drift Detection."""
        build_info = DeploymentIntegrityService.get_build_info()
        
        # Check migration status
        migration_version = "unknown"
        async with engine.connect() as conn:
            try:
                res = await conn.execute(text("SELECT version_num FROM alembic_version"))
                migration_version = res.scalar()
            except:
                pass

        schema_valid = await DeploymentIntegrityService.validate_runtime_schema()
        
        return {
            "status": "healthy" if schema_valid else "degraded",
            "schema_status": "HEALTHY" if schema_valid else "DRIFT_DETECTED",
            "backend_build": build_info["git_commit"][:8],
            "frontend_build": os.getenv("FRONTEND_BUILD", "unknown"),
            "migration_version": migration_version,
            "schema_valid": schema_valid,
            "event_bus_valid": True, # Placeholder for Redis health check
            "container_sync": True,
            "timestamp": datetime.utcnow().isoformat()
        }

def validate_audit_bypass_prevention() -> bool:
    """
    Architectural safeguard that scans the python files in the 'app/' directory on boot.
    Raises a fatal error (blocking startup) if direct 'AuditLog(' instantiation is detected
    in any unauthorized files.
    """
    import os
    import re
    
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # Points to backend/app/
    
    # Define authorized files that are allowed to import or reference AuditLog
    allowed_suffixes = [
        os.path.normpath("app/modules/audit/services/audit_service.py"),
        os.path.normpath("app/api/api_v1/routes/audit.py"),
        os.path.normpath("app/models/__init__.py"),
        os.path.normpath("app/modules/governance/models/governance_models.py"),
        os.path.normpath("app/core/database/integrity.py"),
        os.path.normpath("app/core/integrity.py"),
    ]
    
    pattern = re.compile(r'\bAuditLog\s*\(')
    violations = []
    
    for root, dirs, files in os.walk(app_dir):
        if "__pycache__" in root or "tests" in root:
            continue
        for file in files:
            if not file.endswith(".py"):
                continue
            file_path = os.path.join(root, file)
            normalized_path = os.path.normpath(file_path)
            is_allowed = False
            for suffix in allowed_suffixes:
                if normalized_path.endswith(suffix):
                    is_allowed = True
                    break
            
            if is_allowed:
                continue
                
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if pattern.search(content):
                        rel_path = os.path.relpath(file_path, app_dir)
                        violations.append(rel_path)
            except Exception as e:
                logger.warning(f"Bypass scan skipped file {file_path}: {e}")
                
    if violations:
        logger.critical(
            f"AUDIT PIPELINE BYPASS DETECTED! Direct AuditLog instantiation is prohibited in: {violations}. "
            "Please use AuditService.log_action() to route audit events through the immutable pipeline."
        )
        return False
        
    logger.info("Audit pipeline bypass check PASSED.")
    return True

async def validate_on_startup():
    """Safety guard for application startup."""
    is_valid = await DeploymentIntegrityService.validate_runtime_schema()
    if not is_valid:
        logger.critical("CRITICAL: Application cannot start due to schema integrity failure.")
        import sys
        sys.exit(1)
        
    if not validate_audit_bypass_prevention():
        logger.critical("CRITICAL: Application cannot start due to audit pipeline bypass safeguard failure.")
        import sys
        sys.exit(1)
        
    return is_valid
