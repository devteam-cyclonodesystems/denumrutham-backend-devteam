from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.core.deps import get_current_temple_id, require_permission
from app.schemas.domain import TokenData
from app.modules.audit.services.activity_log_query_service import ActivityLogQueryService
from app.core.response import api_response, paginated_response

router = APIRouter()

@router.get("/dashboard")
async def get_activity_logs_dashboard(
    current_user: TokenData = Depends(require_permission("activity-logs", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve Activity Logs dashboard aggregated stats."""
    metrics = await ActivityLogQueryService.get_dashboard_metrics(db, UUID(temple_id))
    return api_response(data=metrics, message="Activity logs dashboard metrics retrieved")

@router.get("/timeline")
async def get_activity_logs_timeline(
    module_name: Optional[str] = Query(None, description="Filter by module"),
    performed_by_user_id: Optional[UUID] = Query(None, description="Filter by staff member"),
    severity: Optional[str] = Query(None, description="Filter by severity level"),
    start_date: Optional[datetime] = Query(None, description="Start date boundary"),
    end_date: Optional[datetime] = Query(None, description="End date boundary"),
    search: Optional[str] = Query(None, description="Search term (text or PII values)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: TokenData = Depends(require_permission("activity-logs", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    """Query chronological, partitioned activity logs with pagination and filters."""
    offset = (page - 1) * page_size
    items, total = await ActivityLogQueryService.get_timeline(
        db=db,
        temple_id=UUID(temple_id),
        module_name=module_name,
        performed_by_user_id=performed_by_user_id,
        severity=severity,
        start_date=start_date,
        end_date=end_date,
        search=search,
        limit=page_size,
        offset=offset
    )
    
    items_list = []
    for item in items:
        items_list.append({
            "id": str(item.id),
            "module_name": item.module_name,
            "entity_name": item.entity_name,
            "entity_id": item.entity_id,
            "action_type": item.action_type,
            "action_category": item.action_category,
            "description": item.description,
            "before_value": item.before_value,
            "after_value": item.after_value,
            "performed_by_name": item.performed_by_name,
            "performed_by_role": item.performed_by_role,
            "masked_pii": item.masked_pii,
            "severity": item.severity,
            "risk_score": item.risk_score,
            "previous_hash": item.previous_hash,
            "current_hash": item.current_hash,
            "audit_chain_index": item.audit_chain_index,
            "created_utc": item.created_utc.isoformat()
        })
        
    return paginated_response(
        data=items_list,
        total_count=total,
        page=page,
        page_size=page_size,
        message="Activity logs retrieved"
    )

@router.get("/entity/{entity_name}/{entity_id}")
async def get_entity_audit_timeline(
    entity_name: str,
    entity_id: str,
    current_user: TokenData = Depends(require_permission("activity-logs", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve full chronological timeline of a specific entity lifecycle."""
    items = await ActivityLogQueryService.get_entity_history(db, UUID(temple_id), entity_name, entity_id)
    items_list = [
        {
            "id": str(item.id),
            "action_type": item.action_type,
            "action_category": item.action_category,
            "description": item.description,
            "before_value": item.before_value,
            "after_value": item.after_value,
            "performed_by_name": item.performed_by_name,
            "performed_by_role": item.performed_by_role,
            "severity": item.severity,
            "created_utc": item.created_utc.isoformat()
        }
        for item in items
    ]
    return api_response(data=items_list, message="Entity lifecycle timeline retrieved")

@router.get("/forensic/{log_id}")
async def verify_log_forensic_integrity(
    log_id: UUID,
    current_user: TokenData = Depends(require_permission("activity-logs", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    """Perform sequential backwards cryptographic verification for a target log block."""
    result = await ActivityLogQueryService.verify_chain_integrity(db, log_id)
    return api_response(data=result, message="Cryptographic chain integrity verification completed")

@router.get("/export")
async def export_forensic_evidence(
    module_name: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: TokenData = Depends(require_permission("activity-logs", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    """Generate and stream a sealed forensic evidence package containing JSON logs and signature manifests."""
    zip_bytes = await ActivityLogQueryService.generate_evidence_package(
        db=db,
        temple_id=UUID(temple_id),
        investigator_name=current_user.username or "Authorized Manager",
        module_name=module_name,
        search=search
    )
    
    headers = {
        "Content-Disposition": "attachment; filename=tms_forensic_evidence.zip"
    }
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)
