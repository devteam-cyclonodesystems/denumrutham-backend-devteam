import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from app.api.deps import get_db, get_current_user, get_current_superadmin, get_current_temple_id, require_permission
from app.schemas.domain import TokenData
from app.core.response import api_response
from app.services.settlement_service import SettlementService
from app.models.archana import SettlementBatch, TempleBankAccount

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------- Schemas ----------
class BankAccountVerifySchema(BaseModel):
    action: str  # "VERIFY" or "REJECT"
    reason: Optional[str] = None

class BatchCompleteSchema(BaseModel):
    payout_reference_utr: str
    payout_method: str  # "NEFT", "IMPS", etc.

class SettlementBatchGenerateSchema(BaseModel):
    period_start: datetime
    period_end: datetime

# ---------- Endpoints ----------

@router.post("/temple/bank-account")
async def create_temple_bank_account(
    account_holder_name: Optional[str] = Form(None),
    account_holder: Optional[str] = Form(None),
    bank_name: str = Form(...),
    account_number: str = Form(...),
    ifsc_code: Optional[str] = Form(None),
    ifsc: Optional[str] = Form(None),
    account_type: str = Form("SAVINGS"),
    cheque_file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Exposes POST /api/v1/temple/bank-account to Temple Manager.
    Encrypts bank details at rest.
    """
    holder = account_holder_name or account_holder
    ifnot_holder = holder
    if not ifnot_holder:
        raise HTTPException(status_code=400, detail="Account holder name is required")
        
    ifsc_val = ifsc_code or ifsc
    if not ifsc_val:
        raise HTTPException(status_code=400, detail="IFSC code is required")

    cheque_url = None
    if cheque_file:
        import os
        upload_dir = "uploads/cheques"
        os.makedirs(upload_dir, exist_ok=True)
        cheque_path = os.path.join(upload_dir, f"{temple_id}_{cheque_file.filename}")
        try:
            with open(cheque_path, "wb") as f:
                f.write(await cheque_file.read())
            cheque_url = f"/static/cheques/{temple_id}_{cheque_file.filename}"
        except Exception as e:
            logger.error("Failed to save cancelled cheque file: %s", e)

    try:
        bank_ac = await SettlementService.submit_bank_account(
            db=db,
            temple_id=UUID(temple_id),
            account_holder_name=ifnot_holder,
            bank_name=bank_name,
            account_number=account_number,
            ifsc_code=ifsc_val,
            account_type=account_type,
            submitted_by_user_id=UUID(current_user.sub),
            cancelled_cheque_url=cheque_url
        )
        await db.commit()
        
        # Mask account number in response
        masked_number = f"xxxxxx{account_number[-4:]}" if len(account_number) >= 4 else "xxxx"
        return api_response(
            data={
                "id": str(bank_ac.id),
                "account_holder_name": bank_ac.account_holder_name,
                "bank_name": bank_ac.bank_name,
                "account_number": masked_number,
                "ifsc_code": bank_ac.ifsc_code,
                "verification_status": bank_ac.verification_status
            },
            message="Bank account details submitted successfully."
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to submit bank details: {str(e)}")


@router.get("/admin/bank-accounts/pending")
async def list_pending_bank_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Exposes GET /api/v1/admin/bank-accounts/pending to Super Admin.
    """
    stmt = select(TempleBankAccount).filter(TempleBankAccount.verification_status == "PENDING")
    res = await db.execute(stmt)
    accounts = res.scalars().all()
    
    result = []
    for ac in accounts:
        # Decrypt account number for Super Admin
        from app.core.security.encryption import decrypt_data
        try:
            raw_acc = decrypt_data(ac.account_number_enc)
        except Exception:
            raw_acc = "Decryption Failed"
            
        result.append({
            "id": str(ac.id),
            "temple_id": str(ac.temple_id),
            "account_holder_name": ac.account_holder_name,
            "bank_name": ac.bank_name,
            "account_number": raw_acc,
            "ifsc_code": ac.ifsc_code,
            "account_type": ac.account_type,
            "cancelled_cheque_url": ac.cancelled_cheque_url,
            "submitted_by": str(ac.submitted_by),
            "proof_uploaded_at": ac.proof_uploaded_at
        })
    return api_response(data=result, message="Pending bank accounts retrieved successfully")


@router.post("/admin/bank-accounts/{id}/verify")
async def verify_temple_bank_account(
    id: UUID,
    payload: BankAccountVerifySchema,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Exposes POST /api/v1/admin/bank-accounts/{id}/verify to Super Admin.
    """
    if payload.action.upper() not in ("VERIFY", "REJECT"):
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'VERIFY' or 'REJECT'")
        
    try:
        bank_ac = await SettlementService.verify_bank_account(
            db=db,
            bank_account_id=id,
            approver_id=UUID(current_user.sub),
            action=payload.action.upper(),
            reason=payload.reason
        )
        await db.commit()
        return api_response(
            data={"id": str(bank_ac.id), "verification_status": bank_ac.verification_status},
            message=f"Bank account status updated to {bank_ac.verification_status} successfully."
        )
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/settlements/batches/generate")
async def generate_settlement_batches(
    payload: SettlementBatchGenerateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Admin trigger for settlement batch generation.
    """
    try:
        batches = await SettlementService.generate_weekly_settlement_batches(
            db=db,
            period_start=payload.period_start,
            period_end=payload.period_end,
            created_by_user_id=UUID(current_user.sub)
        )
        return api_response(
            data=[{"batch_id": str(b.id), "batch_ref": b.batch_ref, "net_payout_amount": b.net_payout_amount} for b in batches],
            message=f"Generated {len(batches)} settlement batches successfully."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/settlements/batches")
async def list_settlement_batches(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Exposes GET /api/v1/admin/settlements/batches to Super Admin.
    """
    stmt = select(SettlementBatch).order_by(SettlementBatch.created_at.desc())
    res = await db.execute(stmt)
    batches = res.scalars().all()
    
    result = []
    for b in batches:
        result.append({
            "id": str(b.id),
            "temple_id": str(b.temple_id),
            "batch_ref": b.batch_ref,
            "period_start": b.period_start,
            "period_end": b.period_end,
            "transaction_count": b.transaction_count,
            "total_archana_amount": b.total_archana_amount,
            "total_refunds": b.total_refunds,
            "net_payout_amount": b.net_payout_amount,
            "status": b.status,
            "approved_by": str(b.approved_by) if b.approved_by else None,
            "payout_reference": b.payout_reference,
            "payout_method": b.payout_method,
            "settled_at": b.settled_at
        })
    return api_response(data=result, message="Settlement batches retrieved successfully")


@router.post("/admin/settlements/batches/{id}/approve")
async def approve_settlement_batch(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Exposes POST /api/v1/admin/settlements/batches/{id}/approve to Super Admin.
    """
    try:
        batch = await SettlementService.approve_settlement_batch(
            db=db,
            batch_id=id,
            approver_id=UUID(current_user.sub)
        )
        return api_response(
            data={"id": str(batch.id), "status": batch.status},
            message=f"Settlement batch approved successfully."
        )
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/settlements/batches/{id}/complete")
async def complete_settlement_batch(
    id: UUID,
    payload: BatchCompleteSchema,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Exposes POST /api/v1/admin/settlements/batches/{id}/complete to Super Admin.
    Logs UTR bank reference.
    """
    try:
        batch = await SettlementService.complete_settlement_batch(
            db=db,
            batch_id=id,
            utr_ref=payload.payout_reference_utr,
            payout_method=payload.payout_method,
            actor_id=UUID(current_user.sub)
        )
        return api_response(
            data={"id": str(batch.id), "status": batch.status, "payout_reference": batch.payout_reference},
            message="Settlement batch completed successfully."
        )
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/temple/settlements/history")
@router.get("/temple/settlements/dashboard")
async def get_temple_settlement_history(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(require_permission("website", "view"))
):
    """
    Exposes GET /api/v1/temple/settlements/history and GET /api/v1/temple/settlements/dashboard to Temple Manager.
    """
    try:
        data = await SettlementService.get_temple_settlement_dashboard(
            db=db,
            temple_id=UUID(temple_id)
        )
        return api_response(data=data, message="Temple settlement dashboard details retrieved successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/finance/overview")
async def get_admin_finance_overview(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Exposes GET /api/v1/admin/finance/overview to Super Admin.
    """
    try:
        data = await SettlementService.get_admin_finance_overview(db=db)
        return api_response(data=data, message="Platform financial overview retrieved successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
