"""
Audit Log query endpoint — uses indexed columns for filtering and
keyset-aware pagination.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, func
from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.core.deps import get_current_temple_id, require_permission
from app.schemas.domain import TokenData
from app.models.domain import AuditLog
from app.core.response import paginated_response
from app.core.pagination import PaginationParams, get_pagination

router = APIRouter()


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    temple_id: UUID
    user_id: Optional[UUID] = None
    role: Optional[str] = None
    module_name: Optional[str] = None
    action: str
    action_type: Optional[str] = None
    entity_id: Optional[str] = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    ip_address: Optional[str] = None
    details: Optional[str] = None
    approval_id: Optional[UUID] = None
    content_hash: Optional[str] = None
    created_at: datetime


@router.get("/")
async def get_audit_logs(
    module_name: Optional[str] = None,
    action_type: Optional[str] = None,
    user_id: Optional[UUID] = None,
    entity_id: Optional[str] = None,
    approval_id: Optional[UUID] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    pagination: PaginationParams = Depends(get_pagination),
    current_user: TokenData = Depends(require_permission("audit", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Query audit logs with indexed filters.

    All filter columns have dedicated B-tree indexes for sub-ms lookups
    even on tables with millions of rows.
    """
    tid = UUID(temple_id)
    base = select(AuditLog).filter(AuditLog.temple_id == tid)

    # ── Indexed filters ──────────────────────────────────────────────
    if module_name:
        base = base.filter(AuditLog.module_name == module_name)
    if action_type:
        base = base.filter(AuditLog.action_type == action_type)
    if user_id:
        base = base.filter(AuditLog.user_id == user_id)
    if entity_id:
        base = base.filter(AuditLog.entity_id == entity_id)
    if approval_id:
        base = base.filter(AuditLog.approval_id == approval_id)
    if start_date:
        base = base.filter(AuditLog.created_at >= start_date)
    if end_date:
        base = base.filter(AuditLog.created_at <= end_date)

    # ── Total count (for UI pagination controls) ─────────────────────
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # ── Fetch page (uses idx_audit_logs_created_at DESC index) ───────
    data_stmt = base.order_by(desc(AuditLog.created_at)).offset(pagination.offset).limit(pagination.limit)
    result = await db.execute(data_stmt)
    items = result.scalars().all()

    items_list = [AuditLogResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(
        data=items_list,
        total_count=total,
        page=pagination.page,
        page_size=pagination.page_size,
        message="Audit logs retrieved"
    )


from app.modules.audit.models.audit_models import AuditGovernanceConfig, AuditIntegrityVerificationReport
from app.modules.audit.services.chain_verification_service import ChainVerificationService
from app.modules.audit.services.activity_log_query_service import ActivityLogQueryService
from app.modules.audit.services.audit_service import AuditService
from fastapi import Response

class AuditGovernanceConfigUpdate(BaseModel):
    retention_days: int
    export_policy: Optional[dict] = None
    severity_mapping: Optional[dict] = None
    alert_thresholds: Optional[dict] = None
    access_controls: Optional[dict] = None

class ExportPayload(BaseModel):
    investigator_name: str
    module_name: Optional[str] = None
    search: Optional[str] = None

@router.get("/governance/config")
async def get_governance_config(
    current_user: TokenData = Depends(require_permission("audit", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    tid = UUID(temple_id)
    stmt = select(AuditGovernanceConfig).filter(AuditGovernanceConfig.temple_id == tid)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()
    
    if not config:
        # Create a default configuration
        config = AuditGovernanceConfig(
            temple_id=tid,
            retention_days=365,
            export_policy={},
            severity_mapping={},
            alert_thresholds={},
            access_controls={}
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
        
    return config

@router.put("/governance/config")
async def update_governance_config(
    payload: AuditGovernanceConfigUpdate,
    current_user: TokenData = Depends(require_permission("audit", "write")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    tid = UUID(temple_id)
    stmt = select(AuditGovernanceConfig).filter(AuditGovernanceConfig.temple_id == tid)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()
    
    is_new = False
    old_value = {}
    if not config:
        is_new = True
        config = AuditGovernanceConfig(temple_id=tid)
        db.add(config)
    else:
        old_value = {
            "retention_days": config.retention_days,
            "export_policy": config.export_policy,
            "severity_mapping": config.severity_mapping,
            "alert_thresholds": config.alert_thresholds,
            "access_controls": config.access_controls
        }
        
    config.retention_days = payload.retention_days
    if payload.export_policy is not None:
        config.export_policy = payload.export_policy
    if payload.severity_mapping is not None:
        config.severity_mapping = payload.severity_mapping
    if payload.alert_thresholds is not None:
        config.alert_thresholds = payload.alert_thresholds
    if payload.access_controls is not None:
        config.access_controls = payload.access_controls
        
    await db.flush()
    
    new_value = {
        "retention_days": config.retention_days,
        "export_policy": config.export_policy,
        "severity_mapping": config.severity_mapping,
        "alert_thresholds": config.alert_thresholds,
        "access_controls": config.access_controls
    }
    
    # Audit-of-Audit logging
    await AuditService.log_action(
        db=db,
        temple_id=tid,
        user_id=UUID(current_user.sub) if current_user.sub else None,
        role=current_user.role,
        module_name="Audit",
        action="GOVERNANCE_CONFIG_UPDATED" if not is_new else "GOVERNANCE_CONFIG_CREATED",
        action_type="UPDATE" if not is_new else "CREATE",
        entity_id=str(config.id),
        old_value=old_value if not is_new else None,
        new_value=new_value,
        details=f"Audit governance policy updated: retention set to {config.retention_days} days."
    )
    
    await db.commit()
    await db.refresh(config)
    return config

@router.post("/governance/verify")
async def trigger_manual_verification(
    current_user: TokenData = Depends(require_permission("audit", "write")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    tid = UUID(temple_id)
    result = await ChainVerificationService.verify_audit_chain(db, tid)
    report = await ChainVerificationService.record_verification_report(db, tid, result)
    await db.commit()
    
    # Audit logging for manual verification trigger
    await AuditService.log_action(
        db=db,
        temple_id=tid,
        user_id=UUID(current_user.sub) if current_user.sub else None,
        role=current_user.role,
        module_name="Audit",
        action="MANUAL_INTEGRITY_SCAN_RUN",
        action_type="EXECUTE",
        entity_id=str(report.id),
        new_value={"status": result["status"], "total_logs": result["total_logs"]},
        details=f"Manual cryptographic audit chain integrity scan executed. Status: {result['status']}."
    )
    await db.commit()
    return result

@router.get("/governance/reports")
async def get_verification_reports(
    current_user: TokenData = Depends(require_permission("audit", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    tid = UUID(temple_id)
    stmt = (
        select(AuditIntegrityVerificationReport)
        .filter(AuditIntegrityVerificationReport.temple_id == tid)
        .order_by(desc(AuditIntegrityVerificationReport.verified_at))
        .limit(20)
    )
    res = await db.execute(stmt)
    reports = res.scalars().all()
    return reports

@router.post("/governance/export")
async def export_evidence_package(
    payload: ExportPayload,
    current_user: TokenData = Depends(require_permission("audit", "write")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    tid = UUID(temple_id)
    zip_bytes = await ActivityLogQueryService.generate_evidence_package(
        db=db,
        temple_id=tid,
        investigator_name=payload.investigator_name,
        module_name=payload.module_name,
        search=payload.search
    )
    
    # Audit log of the export
    await AuditService.log_action(
        db=db,
        temple_id=tid,
        user_id=UUID(current_user.sub) if current_user.sub else None,
        role=current_user.role,
        module_name="Audit",
        action="EVIDENCE_PACKAGE_EXPORTED",
        action_type="EXECUTE",
        entity_id=str(tid),
        new_value={"investigator": payload.investigator_name, "module_filter": payload.module_name, "search_query": payload.search},
        details=f"Signed evidence package exported by {payload.investigator_name}."
    )
    await db.commit()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"evidence_package_{temple_id}_{timestamp}.zip"
    
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@router.get("/monitoring/metrics")
async def get_outbox_metrics(
    current_user: TokenData = Depends(require_permission("audit", "read")),
):
    from app.modules.audit.services.activity_log_processor import OutboxMetrics
    return {
        "queue_size": OutboxMetrics.queue_size,
        "processing_rate": OutboxMetrics.processing_rate,
        "failure_count": OutboxMetrics.failure_count,
        "poison_pill_skips": OutboxMetrics.poison_pill_skips
    }
