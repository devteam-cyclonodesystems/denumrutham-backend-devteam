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
from app.modules.finance.services.finance_service import FinanceService
from app.models import (
    SettlementBatch, TempleBankAccount, PlatformFinancialAccount, 
    BankAccountStatus
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------- Schemas ----------
class BankAccountVerifySchema(BaseModel):
    action: str  # "VERIFY" or "REJECT"
    reason: Optional[str] = None

class BatchCompleteSchema(BaseModel):
    payout_reference_utr: str
    payout_method: str  # "NEFT", "IMPS", etc.
    idempotency_key: Optional[str] = None

class SettlementBatchGenerateSchema(BaseModel):
    period_start: datetime
    period_end: datetime

class PlatformFinancialAccountCreate(BaseModel):
    account_name: str
    account_identifier: str
    account_type: str  # BANK, UPI, ESCROW, GATEWAY
    bank_name: Optional[str] = None
    ifsc_code: Optional[str] = None

class PlatformFinancialAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    account_identifier: Optional[str] = None
    account_type: Optional[str] = None
    bank_name: Optional[str] = None
    ifsc_code: Optional[str] = None
    is_active: Optional[bool] = None

# ---------- Platform Financial Accounts Endpoints (Super Admin Only) ----------

@router.get("/admin/finance/platform-accounts")
async def list_platform_financial_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Lists all platform financial accounts."""
    stmt = select(PlatformFinancialAccount).order_by(PlatformFinancialAccount.created_at.desc())
    res = await db.execute(stmt)
    accounts = res.scalars().all()
    return api_response(data=accounts, message="Platform financial accounts retrieved successfully")

@router.post("/admin/finance/platform-accounts")
async def create_platform_financial_account(
    payload: PlatformFinancialAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Creates a new platform financial account."""
    ac = PlatformFinancialAccount(
        account_name=payload.account_name,
        account_identifier=payload.account_identifier,
        account_type=payload.account_type.upper(),
        bank_name=payload.bank_name,
        ifsc_code=payload.ifsc_code,
        is_active=True
    )
    db.add(ac)
    await db.commit()
    await db.refresh(ac)

    # Emit standardized audit log
    from app.modules.audit.services.activity_log_service import ActivityLogService
    await ActivityLogService.emit_event(
        db=db,
        temple_id=None,
        module_name="FINANCE",
        entity_name="PlatformFinancialAccount",
        entity_id=str(ac.id),
        action_type="PLATFORM_ACCOUNT_CREATED",
        action_category="GOVERNANCE_FINANCE",
        description=f"Platform financial account {ac.account_name} created.",
        before_value=None,
        after_value={"account_name": ac.account_name, "account_type": ac.account_type},
        performed_by_user_id=UUID(current_user.sub),
        performed_by_name="Super Admin",
        performed_by_role="SUPERADMIN",
        severity="MEDIUM",
        risk_score=10
    )

    return api_response(data=ac, message="Platform financial account created successfully")

@router.put("/admin/finance/platform-accounts/{id}")
async def update_platform_financial_account(
    id: UUID,
    payload: PlatformFinancialAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Updates a platform financial account's parameters."""
    stmt = select(PlatformFinancialAccount).filter(PlatformFinancialAccount.id == id)
    res = await db.execute(stmt)
    ac = res.scalar_one_or_none()
    if not ac:
        raise HTTPException(status_code=404, detail="Platform financial account not found")

    if payload.account_name is not None:
        ac.account_name = payload.account_name
    if payload.account_identifier is not None:
        ac.account_identifier = payload.account_identifier
    if payload.account_type is not None:
        ac.account_type = payload.account_type.upper()
    if payload.bank_name is not None:
        ac.bank_name = payload.bank_name
    if payload.ifsc_code is not None:
        ac.ifsc_code = payload.ifsc_code
    if payload.is_active is not None:
        ac.is_active = payload.is_active

    await db.commit()
    await db.refresh(ac)

    # Emit standardized audit log
    from app.modules.audit.services.activity_log_service import ActivityLogService
    await ActivityLogService.emit_event(
        db=db,
        temple_id=None,
        module_name="FINANCE",
        entity_name="PlatformFinancialAccount",
        entity_id=str(ac.id),
        action_type="PLATFORM_ACCOUNT_UPDATED",
        action_category="GOVERNANCE_FINANCE",
        description=f"Platform financial account {ac.account_name} updated.",
        before_value=None,
        after_value={"account_name": ac.account_name, "is_active": ac.is_active},
        performed_by_user_id=UUID(current_user.sub),
        performed_by_name="Super Admin",
        performed_by_role="SUPERADMIN",
        severity="MEDIUM",
        risk_score=10
    )

    return api_response(data=ac, message="Platform financial account updated successfully")

@router.delete("/admin/finance/platform-accounts/{id}")
async def delete_platform_financial_account(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Soft deactivates a platform financial account."""
    stmt = select(PlatformFinancialAccount).filter(PlatformFinancialAccount.id == id)
    res = await db.execute(stmt)
    ac = res.scalar_one_or_none()
    if not ac:
        raise HTTPException(status_code=404, detail="Platform financial account not found")

    ac.is_active = False
    await db.commit()

    # Emit standardized audit log
    from app.modules.audit.services.activity_log_service import ActivityLogService
    await ActivityLogService.emit_event(
        db=db,
        temple_id=None,
        module_name="FINANCE",
        entity_name="PlatformFinancialAccount",
        entity_id=str(ac.id),
        action_type="PLATFORM_ACCOUNT_UPDATED",
        action_category="GOVERNANCE_FINANCE",
        description=f"Platform financial account {ac.account_name} deactivated.",
        before_value={"is_active": True},
        after_value={"is_active": False},
        performed_by_user_id=UUID(current_user.sub),
        performed_by_name="Super Admin",
        performed_by_role="SUPERADMIN",
        severity="MEDIUM",
        risk_score=10
    )

    return api_response(message="Platform financial account deactivated successfully")

# ---------- Temple Bank Accounts & Payout Settlements Endpoints ----------

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
    Encrypts bank details at rest and registers a new version.
    """
    holder = account_holder_name or account_holder
    if not holder:
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
        bank_ac = await FinanceService.submit_bank_account(
            db=db,
            temple_id=UUID(temple_id),
            account_holder_name=holder,
            bank_name=bank_name,
            account_number=account_number,
            ifsc_code=ifsc_val,
            account_type=account_type,
            submitted_by_user_id=UUID(current_user.sub),
            cancelled_cheque_url=cheque_url
        )
        await db.commit()
        
        masked_number = f"xxxxxx{account_number[-4:]}" if len(account_number) >= 4 else "xxxx"
        return api_response(
            data={
                "id": str(bank_ac.id),
                "account_holder_name": bank_ac.account_holder_name,
                "bank_name": bank_ac.bank_name,
                "account_number": masked_number,
                "ifsc_code": bank_ac.ifsc_code,
                "verification_status": bank_ac.verification_status,
                "version": bank_ac.version
            },
            message="Bank account details version submitted successfully."
        )
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to submit bank details: {str(e)}")


@router.get("/temple/bank-accounts")
async def list_temple_bank_accounts(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user)
):
    """Lists all bank account versions and history for the current temple manager."""
    stmt = select(TempleBankAccount).filter(
        TempleBankAccount.temple_id == UUID(temple_id)
    ).order_by(TempleBankAccount.version.desc())
    res = await db.execute(stmt)
    accounts = res.scalars().all()
    
    result = []
    for ac in accounts:
        from app.core.security.encryption import decrypt_data
        try:
            raw_acc = decrypt_data(ac.account_number_enc)
            # Mask all but last 4 digits for security in display
            masked_acc = f"xxxxxx{raw_acc[-4:]}" if len(raw_acc) >= 4 else "xxxx"
        except Exception:
            masked_acc = "Decryption Failed"
            
        result.append({
            "id": str(ac.id),
            "account_holder_name": ac.account_holder_name,
            "bank_name": ac.bank_name,
            "account_number": masked_acc,
            "ifsc_code": ac.ifsc_code,
            "account_type": ac.account_type,
            "verification_status": ac.verification_status,
            "version": ac.version,
            "is_active": ac.is_active,
            "is_primary": ac.is_primary,
            "effective_from": ac.effective_from,
            "effective_to": ac.effective_to,
            "rejection_reason": ac.rejection_reason,
            "proof_uploaded_at": ac.proof_uploaded_at
        })
    return api_response(data=result, message="Temple bank accounts history retrieved successfully")


@router.get("/admin/bank-accounts/pending")
async def list_pending_bank_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Lists all pending bank account requests for Super Admin checker approval."""
    stmt = select(TempleBankAccount).filter(TempleBankAccount.verification_status == BankAccountStatus.PENDING)
    res = await db.execute(stmt)
    accounts = res.scalars().all()
    
    result = []
    for ac in accounts:
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
            "proof_uploaded_at": ac.proof_uploaded_at,
            "version": ac.version
        })
    return api_response(data=result, message="Pending bank accounts retrieved successfully")


@router.post("/admin/bank-accounts/{id}/verify")
async def verify_temple_bank_account(
    id: UUID,
    payload: BankAccountVerifySchema,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Super Admin checker verifies or rejects a bank account version."""
    if payload.action.upper() not in ("VERIFY", "REJECT"):
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'VERIFY' or 'REJECT'")
        
    try:
        bank_ac = await FinanceService.verify_bank_account(
            db=db,
            bank_account_id=id,
            approver_id=UUID(current_user.sub),
            action=payload.action.upper(),
            reason=payload.reason
        )
        await db.commit()
        return api_response(
            data={"id": str(bank_ac.id), "verification_status": bank_ac.verification_status},
            message=f"Bank account version status updated to {bank_ac.verification_status} successfully."
        )
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/settlements/batches/generate")
async def generate_settlement_batches(
    payload: SettlementBatchGenerateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Triggers settlement batch generation."""
    try:
        batches = await FinanceService.generate_weekly_settlement_batches(
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
    """Retrieves all settlement batches."""
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
            "settled_at": b.settled_at,
            "bank_account_id": str(b.bank_account_id) if b.bank_account_id else None
        })
    return api_response(data=result, message="Settlement batches retrieved successfully")


@router.post("/admin/settlements/batches/{id}/approve")
async def approve_settlement_batch(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Approves a settlement batch payout."""
    try:
        batch = await FinanceService.approve_settlement_batch(
            db=db,
            batch_id=id,
            approver_id=UUID(current_user.sub)
        )
        return api_response(
            data={"id": str(batch.id), "status": batch.status},
            message="Settlement batch approved successfully."
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
    """Logs UTR bank reference and completes batch settlement."""
    try:
        # Check idempotency if key is passed
        if payload.idempotency_key:
            stmt = select(SettlementBatch).filter(SettlementBatch.idempotency_key == payload.idempotency_key)
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing and existing.id == id:
                return api_response(
                    data={"id": str(existing.id), "status": existing.status, "payout_reference": existing.payout_reference},
                    message="Settlement batch already completed (Idempotency Hit)."
                )

        batch = await FinanceService.complete_settlement_batch(
            db=db,
            batch_id=id,
            utr_ref=payload.payout_reference_utr,
            payout_method=payload.payout_method,
            actor_id=UUID(current_user.sub)
        )
        
        # Save idempotency key if present
        if payload.idempotency_key:
            batch.idempotency_key = payload.idempotency_key
            await db.commit()

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
    """Exposes history and pending payouts overview to Temple Manager."""
    try:
        data = await FinanceService.get_temple_settlement_dashboard(
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
    """Platform financial overview dashboard statistics."""
    try:
        data = await FinanceService.get_admin_finance_overview(db=db)
        return api_response(data=data, message="Platform financial overview retrieved successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
