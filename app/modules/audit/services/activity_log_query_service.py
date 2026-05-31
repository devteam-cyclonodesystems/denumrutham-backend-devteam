import io
import zipfile
import json
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc, or_, String, cast
from app.modules.audit.models.audit_models import ImmutableActivityLog
from app.modules.audit.services.activity_log_processor import ActivityLogProcessor

class ActivityLogQueryService:
    @staticmethod
    async def get_dashboard_metrics(db: AsyncSession, temple_id: UUID) -> Dict[str, Any]:
        # Today's boundary in UTC
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 1. Today's Activities
        today_cnt_stmt = select(func.count(ImmutableActivityLog.id)).filter(
            ImmutableActivityLog.temple_id == temple_id,
            ImmutableActivityLog.created_utc >= today_start
        )
        today_cnt = (await db.execute(today_cnt_stmt)).scalar() or 0
        
        # 2. Critical Events
        crit_cnt_stmt = select(func.count(ImmutableActivityLog.id)).filter(
            ImmutableActivityLog.temple_id == temple_id,
            ImmutableActivityLog.severity == "CRITICAL"
        )
        crit_cnt = (await db.execute(crit_cnt_stmt)).scalar() or 0
        
        # 3. High Severity Events
        high_cnt_stmt = select(func.count(ImmutableActivityLog.id)).filter(
            ImmutableActivityLog.temple_id == temple_id,
            ImmutableActivityLog.severity == "HIGH"
        )
        high_cnt = (await db.execute(high_cnt_stmt)).scalar() or 0
        
        # 4. Active Staff Count (Unique users with log entries today)
        active_staff_stmt = select(func.count(func.distinct(ImmutableActivityLog.performed_by_user_id))).filter(
            ImmutableActivityLog.temple_id == temple_id,
            ImmutableActivityLog.created_utc >= today_start
        )
        active_staff = (await db.execute(active_staff_stmt)).scalar() or 0
        
        # 5. Module-wise distribution
        module_dist_stmt = select(
            ImmutableActivityLog.module_name,
            func.count(ImmutableActivityLog.id)
        ).filter(
            ImmutableActivityLog.temple_id == temple_id
        ).group_by(ImmutableActivityLog.module_name)
        
        module_dist_res = await db.execute(module_dist_stmt)
        module_distribution = {row[0]: row[1] for row in module_dist_res.all()}
        
        # 6. Recent high-risk events (risk_score >= 50 or severity in HIGH/VERY_HIGH/CRITICAL)
        recent_high_risk_stmt = select(ImmutableActivityLog).filter(
            ImmutableActivityLog.temple_id == temple_id,
            or_(
                ImmutableActivityLog.risk_score >= 50,
                ImmutableActivityLog.severity.in_(["HIGH", "VERY_HIGH", "CRITICAL"])
            )
        ).order_by(desc(ImmutableActivityLog.created_utc)).limit(5)
        
        recent_high_risk_res = await db.execute(recent_high_risk_stmt)
        recent_high_risk = recent_high_risk_res.scalars().all()
        
        return {
            "today_activities_count": today_cnt,
            "critical_events_count": crit_cnt,
            "high_severity_events_count": high_cnt,
            "active_staff_count": active_staff,
            "module_distribution": module_distribution,
            "recent_high_risk_events": [
                {
                    "id": str(log.id),
                    "module_name": log.module_name,
                    "action_type": log.action_type,
                    "description": log.description,
                    "performed_by_name": log.performed_by_name,
                    "severity": log.severity,
                    "risk_score": log.risk_score,
                    "created_utc": log.created_utc.isoformat()
                }
                for log in recent_high_risk
            ]
        }

    @staticmethod
    async def get_timeline(
        db: AsyncSession,
        temple_id: UUID,
        module_name: Optional[str] = None,
        performed_by_user_id: Optional[UUID] = None,
        severity: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[ImmutableActivityLog], int]:
        base = select(ImmutableActivityLog).filter(ImmutableActivityLog.temple_id == temple_id)
        
        if module_name:
            base = base.filter(ImmutableActivityLog.module_name == module_name)
        if performed_by_user_id:
            base = base.filter(ImmutableActivityLog.performed_by_user_id == performed_by_user_id)
        if severity:
            base = base.filter(ImmutableActivityLog.severity == severity)
        if start_date:
            base = base.filter(ImmutableActivityLog.created_utc >= start_date)
        if end_date:
            base = base.filter(ImmutableActivityLog.created_utc <= end_date)
            
        if search:
            # Match standard text fields
            text_filters = [
                ImmutableActivityLog.description.ilike(f"%{search}%"),
                ImmutableActivityLog.performed_by_name.ilike(f"%{search}%"),
                ImmutableActivityLog.entity_id.ilike(f"%{search}%"),
                ImmutableActivityLog.entity_name.ilike(f"%{search}%"),
                ImmutableActivityLog.action_type.ilike(f"%{search}%")
            ]
            
            # Salted SHA-256 hash match for searchable PII indexing without exposing raw text
            from app.modules.audit.services.activity_log_service import ActivityLogService
            search_hash = ActivityLogService.hash_pii_value(search)
            text_filters.append(cast(ImmutableActivityLog.hashed_pii, String).contains(search_hash))
            
            base = base.filter(or_(*text_filters))
            
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0
        
        stmt = base.order_by(desc(ImmutableActivityLog.created_utc)).offset(offset).limit(limit)
        res = await db.execute(stmt)
        items = res.scalars().all()
        
        return items, total

    @staticmethod
    async def get_entity_history(
        db: AsyncSession,
        temple_id: UUID,
        entity_name: str,
        entity_id: str
    ) -> List[ImmutableActivityLog]:
        """Retrieve complete chronological history of a specific entity."""
        stmt = (
            select(ImmutableActivityLog)
            .filter(
                ImmutableActivityLog.temple_id == temple_id,
                ImmutableActivityLog.entity_name == entity_name,
                ImmutableActivityLog.entity_id == entity_id
            )
            .order_by(ImmutableActivityLog.audit_chain_index.asc())
        )
        res = await db.execute(stmt)
        return res.scalars().all()

    @staticmethod
    async def verify_chain_integrity(db: AsyncSession, log_id: UUID) -> Dict[str, Any]:
        """Verify chain integrity backwards from a given log to the genesis block (index = 1)."""
        stmt = select(ImmutableActivityLog).filter(ImmutableActivityLog.id == log_id)
        res = await db.execute(stmt)
        target_log = res.scalar_one_or_none()
        
        if not target_log:
            return {"verified": False, "status": "not_found", "steps_checked": 0, "report": []}
            
        temple_id = target_log.temple_id
        target_index = target_log.audit_chain_index
        
        # Load the sequence of logs up to the target index
        chain_stmt = (
            select(ImmutableActivityLog)
            .filter(
                ImmutableActivityLog.temple_id == temple_id,
                ImmutableActivityLog.audit_chain_index <= target_index
            )
            .order_by(ImmutableActivityLog.audit_chain_index.asc())
        )
        chain_res = await db.execute(chain_stmt)
        chain_logs = chain_res.scalars().all()
        
        verification_steps = []
        is_compromised = False
        mismatched_index = None
        
        for idx, log in enumerate(chain_logs):
            expected_index = idx + 1
            if log.audit_chain_index != expected_index:
                is_compromised = True
                mismatched_index = expected_index
                verification_steps.append({
                    "index": log.audit_chain_index,
                    "id": str(log.id),
                    "status": f"Sequence break: expected index {expected_index}, found {log.audit_chain_index}"
                })
                break
                
            expected_prev_hash = "0" * 64 if expected_index == 1 else chain_logs[idx - 1].current_hash
            if log.previous_hash != expected_prev_hash:
                is_compromised = True
                mismatched_index = log.audit_chain_index
                verification_steps.append({
                    "index": log.audit_chain_index,
                    "id": str(log.id),
                    "status": "Previous hash mismatch"
                })
                break
                
            recalc_hash = ActivityLogProcessor.calculate_log_hash(
                log_id=log.id,
                temple_id=log.temple_id,
                action_type=log.action_type,
                created_utc=log.created_utc,
                after_value=log.after_value,
                prev_hash=log.previous_hash
            )
            
            if log.current_hash != recalc_hash:
                is_compromised = True
                mismatched_index = log.audit_chain_index
                verification_steps.append({
                    "index": log.audit_chain_index,
                    "id": str(log.id),
                    "status": f"Hash mismatch: stored={log.current_hash}, recalculated={recalc_hash}"
                })
                break
                
            verification_steps.append({
                "index": log.audit_chain_index,
                "id": str(log.id),
                "status": "Verified"
            })
            
        if is_compromised:
            return {
                "verified": False,
                "status": "compromised",
                "compromised_at_index": mismatched_index,
                "steps_checked": len(verification_steps),
                "report": verification_steps
            }
            
        return {
            "verified": True,
            "status": "verified",
            "steps_checked": len(verification_steps),
            "report": verification_steps
        }

    @staticmethod
    async def generate_evidence_package(
        db: AsyncSession,
        temple_id: UUID,
        investigator_name: str,
        module_name: Optional[str] = None,
        search: Optional[str] = None
    ) -> bytes:
        """Compile a cryptographically-verified zip package containing logs and integrity report."""
        # 1. Fetch filtered logs for evidence scope
        logs, total = await ActivityLogQueryService.get_timeline(
            db=db,
            temple_id=temple_id,
            module_name=module_name,
            search=search,
            limit=5000, # Large batch cap for audit packages
            offset=0
        )
        
        # 2. Standardize JSON formatting of logs (hiding hash values but displaying masks)
        logs_dump = []
        for log in logs:
            logs_dump.append({
                "id": str(log.id),
                "module_name": log.module_name,
                "entity_name": log.entity_name,
                "entity_id": log.entity_id,
                "action_type": log.action_type,
                "action_category": log.action_category,
                "description": log.description,
                "before_value": log.before_value,
                "after_value": log.after_value,
                "performed_by_name": log.performed_by_name,
                "performed_by_role": log.performed_by_role,
                "masked_pii": log.masked_pii,
                "severity": log.severity,
                "risk_score": log.risk_score,
                "previous_hash": log.previous_hash,
                "current_hash": log.current_hash,
                "audit_chain_index": log.audit_chain_index,
                "created_utc": log.created_utc.isoformat()
            })
            
        # 3. Perform a validation audit verification check from the latest matching log to genesis block
        validation_report = {"verified": True, "details": "No logs in export scope."}
        if logs:
            latest_log = logs[0] # Timeline returns DESC, so index 0 is the newest
            validation_report = await ActivityLogQueryService.verify_chain_integrity(db, latest_log.id)
            
        # 4. Generate human-readable TXT/Markdown verification report
        report_buffer = []
        report_buffer.append("=========================================================================")
        report_buffer.append("DENUMRUTHAM TEMPLE MANAGEMENT SYSTEM - DIGITAL EVIDENCE FORENSICS REPORT")
        report_buffer.append("=========================================================================")
        report_buffer.append(f"Generated At: {datetime.now(timezone.utc).isoformat()}")
        report_buffer.append(f"Investigator: {investigator_name}")
        report_buffer.append(f"Temple UUID : {temple_id}")
        report_buffer.append(f"Export Scope: {total} records")
        if module_name:
            report_buffer.append(f"Module Filter: {module_name}")
        if search:
            report_buffer.append(f"Search Query: '{search}'")
        report_buffer.append("-------------------------------------------------------------------------")
        report_buffer.append(f"Cryptographic Chain Verification Status: {validation_report.get('status', 'unknown').upper()}")
        report_buffer.append(f"Blocks Audited: {validation_report.get('steps_checked', 0)}")
        if not validation_report.get("verified", False):
            report_buffer.append(f"ALERT: Compromise detected at chain index: {validation_report.get('compromised_at_index', 'N/A')}")
        report_buffer.append("-------------------------------------------------------------------------")
        report_buffer.append("\nAudited Chain Ledger Verification:")
        for step in validation_report.get("report", []):
            report_buffer.append(f"  [Index {step['index']}] ID {step['id']} -> {step['status']}")
            
        report_text = "\n".join(report_buffer)
        
        # 5. Pack into ZIP archive
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr("activity_logs.json", json.dumps(logs_dump, indent=2, default=str))
            zip_file.writestr("chain_verification_report.txt", report_text)
            
            # Simple manifest
            manifest = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "investigator": investigator_name,
                "temple_id": str(temple_id),
                "record_count": total,
                "chain_integrity_verified": validation_report.get("verified", False),
                "validation_steps_completed": validation_report.get("steps_checked", 0)
            }
            zip_file.writestr("evidence_manifest.json", json.dumps(manifest, indent=2))
            
        zip_buffer.seek(0)
        return zip_buffer.getvalue()
