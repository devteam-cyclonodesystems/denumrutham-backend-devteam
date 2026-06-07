from datetime import datetime, timezone
import logging
from uuid import UUID
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.future import select

from app.modules.audit.models.audit_models import ImmutableActivityLog, AuditIntegrityVerificationReport, AuditChainVersion
from app.modules.audit.services.activity_log_processor import ActivityLogProcessor
from app.modules.governance.services.operational_state_service import OperationalStateService
from app.modules.governance.models.operational_states import TempleOperationalState

logger = logging.getLogger(__name__)

class ChainVerificationService:
    @staticmethod
    async def verify_audit_chain(db: AsyncSession, temple_id: UUID) -> Dict[str, Any]:
        """
        Verifies the cryptographic chain of audit logs for a given temple.
        Recalculates the hash chain from genesis block (index = 1) up to the latest log
        for the currently active chain version.
        """
        # Get active chain version
        version_stmt = (
            select(AuditChainVersion.chain_version)
            .filter(
                AuditChainVersion.temple_id == temple_id,
                AuditChainVersion.chain_status == 'ACTIVE'
            )
            .limit(1)
        )
        version_res = await db.execute(version_stmt)
        active_version = version_res.scalar() or 1

        stmt = (
            select(ImmutableActivityLog)
            .filter(
                ImmutableActivityLog.temple_id == temple_id,
                ImmutableActivityLog.chain_version == active_version
            )
            .order_by(ImmutableActivityLog.audit_chain_index.asc())
        )
        res = await db.execute(stmt)
        logs = res.scalars().all()

        if not logs:
            return {
                "verified": True,
                "status": "PASS",
                "total_logs": 0,
                "failed_logs_count": 0,
                "failed_log_ids": [],
                "details": "No audit log entries found for this temple. Genesis chain is empty but intact."
            }

        failed_log_ids = []
        is_compromised = False
        mismatched_reason = ""

        for idx, log in enumerate(logs):
            expected_index = idx + 1
            if log.audit_chain_index != expected_index:
                is_compromised = True
                mismatched_reason = f"Sequence break: expected index {expected_index}, found {log.audit_chain_index}"
                failed_log_ids.append(str(log.id))
                break

            expected_prev_hash = "0" * 64 if expected_index == 1 else logs[idx - 1].current_hash
            if log.previous_hash != expected_prev_hash:
                is_compromised = True
                mismatched_reason = f"Previous hash mismatch at index {expected_index}. Expected: {expected_prev_hash}, Got: {log.previous_hash}"
                failed_log_ids.append(str(log.id))
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
                mismatched_reason = f"Current hash mismatch at index {expected_index}. Stored: {log.current_hash}, Recalculated: {recalc_hash}"
                failed_log_ids.append(str(log.id))
                break

        if is_compromised:
            details = f"Chain verification failed: {mismatched_reason}"
            status = "FAIL"
            logger.critical(f"CRITICAL: AUDIT CHAIN COMPROMISED for temple {temple_id}: {mismatched_reason}")
        else:
            details = f"All {len(logs)} audit logs cryptographically verified up to the latest entry."
            status = "PASS"

        return {
            "verified": not is_compromised,
            "status": status,
            "total_logs": len(logs),
            "failed_logs_count": len(failed_log_ids),
            "failed_log_ids": failed_log_ids,
            "details": details
        }

    @staticmethod
    async def record_verification_report(
        db: AsyncSession,
        temple_id: UUID,
        result: Dict[str, Any]
    ) -> AuditIntegrityVerificationReport:
        """
        Saves a verification report to the database.
        """
        report = AuditIntegrityVerificationReport(
            temple_id=temple_id,
            status=result["status"],
            total_logs=result["total_logs"],
            failed_logs_count=result["failed_logs_count"],
            failed_log_ids=result["failed_log_ids"],
            details=result["details"],
            verified_at=datetime.now(timezone.utc)
        )
        db.add(report)
        await db.flush()  # Let the caller commit
        return report

    @staticmethod
    async def verify_all_temples(db: AsyncSession) -> Dict[str, Any]:
        """
        Verifies the audit chain for all active temples.
        Records a verification report for each.
        If a failure is detected, transition the temple operational state to SUSPENDED.
        Returns a summary of verification status across the platform.
        """
        from app.models.domain import Temple
        temples_res = await db.execute(select(Temple).filter(Temple.is_active == True))
        temples = temples_res.scalars().all()

        total_temples = len(temples)
        failed_temples = []
        reports = []

        for temple in temples:
            res = await ChainVerificationService.verify_audit_chain(db, temple.id)
            report = await ChainVerificationService.record_verification_report(db, temple.id, res)
            reports.append(report)
            
            if res["status"] == "FAIL":
                failed_temples.append(str(temple.id))
                # Lock down temple console by transitioning operational state to SUSPENDED
                try:
                    await OperationalStateService.transition_to(
                        db=db,
                        temple_id=temple.id,
                        new_state=TempleOperationalState.SUSPENDED,
                        changed_by=None,
                        reason=f"System Lock: Audit log cryptographic chain corruption detected: {res['details']}"
                    )
                    logger.critical(f"Temple {temple.id} successfully locked down to SUSPENDED operational state.")
                except Exception as ex:
                    logger.error(f"Failed to transition temple {temple.id} state to SUSPENDED: {str(ex)}")

        await db.commit()

        status = "FAIL" if failed_temples else "PASS"
        return {
            "status": status,
            "total_temples_checked": total_temples,
            "failed_temples_count": len(failed_temples),
            "failed_temple_ids": failed_temples,
            "reports_recorded": len(reports)
        }
