import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

from sqlalchemy import select, update, func, and_, or_
from app.core.database.database import AsyncSessionLocal
from app.models.domain import Temple, User
from app.models.archana import (
    OnlineSettlementLedger, TempleBankAccount, SettlementBatch, SettlementBatchItem
)
from app.core.security.encryption import encrypt_data, decrypt_data
from app.modules.audit.services.activity_log_service import ActivityLogService

logger = logging.getLogger(__name__)

class SettlementService:
    """
    Settlement Ledger Engine service managing:
    - Temple Bank Accounts (submission, verification)
    - Weekly Settlement Batch generation with rollover and guards
    - Batch approval and UTR manual completion workflows
    """

    @classmethod
    async def submit_bank_account(
        cls,
        db: AsyncSessionLocal,
        temple_id: UUID,
        account_holder_name: str,
        bank_name: str,
        account_number: str,
        ifsc_code: str,
        account_type: str,
        submitted_by_user_id: UUID,
        cancelled_cheque_url: str = None
    ) -> TempleBankAccount:
        """
        Submit a new bank account for a temple.
        Encrypts the account number at rest using AES-256 (Fernet).
        """
        # Deactivate any existing bank accounts for this temple
        await db.execute(
            update(TempleBankAccount)
            .where(TempleBankAccount.temple_id == temple_id)
            .values(is_active=False, is_primary=False)
        )

        account_number_enc = encrypt_data(account_number)
        
        bank_ac = TempleBankAccount(
            temple_id=temple_id,
            account_holder_name=account_holder_name,
            bank_name=bank_name,
            account_number_enc=account_number_enc,
            ifsc_code=ifsc_code,
            account_type=account_type.upper(),
            cancelled_cheque_url=cancelled_cheque_url,
            verification_status="PENDING",
            is_active=True,
            is_primary=True,
            submitted_by=submitted_by_user_id,
            proof_uploaded_at=datetime.now(timezone.utc)
        )
        db.add(bank_ac)
        await db.flush()

        # Emit audit log
        await ActivityLogService.emit_event(
            db=db,
            temple_id=temple_id,
            module_name="FINANCE",
            entity_name="TempleBankAccount",
            entity_id=str(bank_ac.id),
            action_type="BANK_DETAILS_SUBMITTED",
            action_category="GOVERNANCE_FINANCE",
            description=f"Bank account submitted for verification by user {submitted_by_user_id}.",
            before_value=None,
            after_value={"bank_name": bank_name, "ifsc_code": ifsc_code},
            performed_by_user_id=submitted_by_user_id,
            performed_by_name="Temple Manager",
            performed_by_role="MANAGER",
            severity="MEDIUM",
            risk_score=20
        )
        return bank_ac

    @classmethod
    async def verify_bank_account(
        cls,
        db: AsyncSessionLocal,
        bank_account_id: UUID,
        approver_id: UUID,
        action: str,  # "VERIFY" or "REJECT"
        reason: str = None
    ) -> TempleBankAccount:
        """
        Super Admin approves or rejects temple bank account verification.
        """
        stmt = select(TempleBankAccount).filter(TempleBankAccount.id == bank_account_id)
        res = await db.execute(stmt)
        bank_ac = res.scalar_one_or_none()
        if not bank_ac:
            raise ValueError("Bank account not found")

        action_type = "BANK_DETAILS_VERIFIED" if action == "VERIFY" else "BANK_DETAILS_REJECTED"
        status = "VERIFIED" if action == "VERIFY" else "REJECTED"

        bank_ac.verification_status = status
        bank_ac.verified_by = approver_id
        bank_ac.verified_at = datetime.now(timezone.utc)
        bank_ac.rejection_reason = reason

        await db.flush()

        # Emit audit log
        await ActivityLogService.emit_event(
            db=db,
            temple_id=bank_ac.temple_id,
            module_name="FINANCE",
            entity_name="TempleBankAccount",
            entity_id=str(bank_ac.id),
            action_type=action_type,
            action_category="GOVERNANCE_FINANCE",
            description=f"Bank account {status} by Super Admin. Reason: {reason or 'N/A'}",
            before_value={"verification_status": "PENDING"},
            after_value={"verification_status": status},
            performed_by_user_id=approver_id,
            performed_by_name="Super Admin",
            performed_by_role="SUPERADMIN",
            severity="HIGH",
            risk_score=30
        )
        return bank_ac

    @classmethod
    async def generate_weekly_settlement_batches(
        cls,
        db: AsyncSessionLocal,
        period_start: datetime,
        period_end: datetime,
        created_by_user_id: UUID
    ) -> List[SettlementBatch]:
        """
        Generate weekly settlement batches for all temples satisfying the eligibility criteria:
        1. Temple operational and active
        2. Verified and active primary bank account
        3. Temple marked as eligible for settlements (is_settlement_eligible = True)
        Enforces rollover for balances < Rs 500 or failing eligibility checks.
        """
        # Fetch all temples
        temple_stmt = select(Temple).filter(
            Temple.is_active == True,
            Temple.status == "APPROVED"
        )
        res = await db.execute(temple_stmt)
        temples = res.scalars().all()

        batches_created = []

        for temple in temples:
            temple_id = temple.id

            # 1. Eligibility Check: is_settlement_eligible
            if not temple.is_settlement_eligible:
                logger.info("Temple %s skipped: is_settlement_eligible is False. Reason: %s", temple.id, temple.settlement_hold_reason)
                continue

            # 2. Eligibility Check: Active and Verified bank account
            bank_stmt = select(TempleBankAccount).filter(
                TempleBankAccount.temple_id == temple_id,
                TempleBankAccount.verification_status == "VERIFIED",
                TempleBankAccount.is_active == True,
                TempleBankAccount.is_primary == True
            )
            bank_res = await db.execute(bank_stmt)
            bank_ac = bank_res.scalar_one_or_none()
            if not bank_ac:
                logger.info("Temple %s skipped: No verified primary bank account found.", temple.id)
                continue

            # Lock and fetch unsettled ledger entries using SELECT FOR UPDATE
            ledger_stmt = select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.temple_id == temple_id,
                OnlineSettlementLedger.settlement_batch_id == None,
                OnlineSettlementLedger.is_settled == False
            )
            # Safe dialect: apply skip_locked only for PostgreSQL (not supported by SQLite)
            try:
                dialect_name = db.get_bind().dialect.name
            except Exception:
                dialect_name = "unknown"
            if dialect_name == "postgresql":
                ledger_stmt = ledger_stmt.with_for_update(skip_locked=True)
            else:
                ledger_stmt = ledger_stmt.with_for_update()

            ledger_res = await db.execute(ledger_stmt)
            unsettled_entries = ledger_res.scalars().all()

            if not unsettled_entries:
                continue

            # Calculate Dynamic Ledger Balance
            total_credits = 0.0
            total_debits = 0.0
            transaction_count = len(unsettled_entries)

            for entry in unsettled_entries:
                # debits are saved as negative values in the ledger
                if entry.temple_net_amount >= 0:
                    total_credits += entry.temple_net_amount
                else:
                    total_debits += abs(entry.temple_net_amount)

            pending_balance = total_credits - total_debits

            # 3. Rollover threshold check (Rs 500)
            if pending_balance < 500.0:
                logger.info("Temple %s skipped: Pending balance Rs %.2f is below Rs 500 threshold (Rollover).", temple.id, pending_balance)
                continue

            # Deterministic batch_ref: SET-{temple_code/hex}-{period_start_YYYYMMDD}-{period_end_YYYYMMDD}
            temple_ref_part = temple.temple_code or str(temple_id).replace("-", "")[:8]
            batch_ref = f"SET-{temple_ref_part}-{period_start.strftime('%Y%m%d')}-{period_end.strftime('%Y%m%d')}"

            # Check if batch_ref already exists (retry-safe idempotency guard)
            dup_batch_stmt = select(SettlementBatch).filter(SettlementBatch.batch_ref == batch_ref)
            dup_batch_res = await db.execute(dup_batch_stmt)
            existing_batch = dup_batch_res.scalar_one_or_none()
            if existing_batch:
                logger.warning("Settlement batch %s already exists. Skipping duplicate generation.", batch_ref)
                continue

            try:
                # Start transaction for this temple's batch creation
                async with db.begin_nested():
                    batch = SettlementBatch(
                        temple_id=temple_id,
                        batch_ref=batch_ref,
                        period_start=period_start,
                        period_end=period_end,
                        transaction_count=transaction_count,
                        total_archana_amount=total_credits,
                        total_refunds=total_debits,
                        net_payout_amount=pending_balance,
                        status="PENDING",
                        bank_account_id=bank_ac.id,
                        created_by=created_by_user_id
                    )
                    db.add(batch)
                    await db.flush()

                    # Link ledger entries to batch items and update batch_id on ledger entries
                    for entry in unsettled_entries:
                        item = SettlementBatchItem(
                            batch_id=batch.id,
                            ledger_entry_id=entry.id
                        )
                        db.add(item)
                        entry.settlement_batch_id = batch.id
                    
                    await db.flush()

                    # Stage outbox event for batch generation
                    await ActivityLogService.emit_event(
                        db=db,
                        temple_id=temple_id,
                        module_name="FINANCE",
                        entity_name="SettlementBatch",
                        entity_id=str(batch.id),
                        action_type="SETTLEMENT_BATCH_GEN",
                        action_category="GOVERNANCE_FINANCE",
                        description=f"Settlement batch generated: {batch_ref} (Net Payout: INR {pending_balance:.2f}).",
                        before_value=None,
                        after_value={"batch_ref": batch_ref, "net_payout_amount": pending_balance},
                        performed_by_user_id=created_by_user_id,
                        performed_by_name="System Cron",
                        performed_by_role="SYSTEM",
                        severity="MEDIUM",
                        risk_score=20
                    )
                    batches_created.append(batch)
            except Exception as e:
                logger.error("Failed to generate settlement batch for temple %s: %s", temple_id, e)
                # Nest transaction rolls back this temple's changes and moves to next temple
                continue

        # Commit overall generation transaction
        await db.commit()
        return batches_created

    @classmethod
    async def approve_settlement_batch(
        cls,
        db: AsyncSessionLocal,
        batch_id: UUID,
        approver_id: UUID
    ) -> SettlementBatch:
        """
        Super Admin approves a pending settlement batch.
        """
        stmt = select(SettlementBatch).filter(SettlementBatch.id == batch_id).with_for_update()
        res = await db.execute(stmt)
        batch = res.scalar_one_or_none()
        if not batch:
            raise ValueError("Settlement batch not found")

        if batch.status != "PENDING":
            # safe retry / no-op
            return batch

        batch.status = "APPROVED"
        batch.approved_by = approver_id
        batch.approved_at = datetime.now(timezone.utc)
        await db.flush()

        # Emit audit log
        await ActivityLogService.emit_event(
            db=db,
            temple_id=batch.temple_id,
            module_name="FINANCE",
            entity_name="SettlementBatch",
            entity_id=str(batch.id),
            action_type="SETTLEMENT_BATCH_APPR",
            action_category="GOVERNANCE_FINANCE",
            description=f"Settlement batch {batch.batch_ref} approved by Super Admin.",
            before_value={"status": "PENDING"},
            after_value={"status": "APPROVED"},
            performed_by_user_id=approver_id,
            performed_by_name="Super Admin",
            performed_by_role="SUPERADMIN",
            severity="HIGH",
            risk_score=30
        )
        await db.commit()
        return batch

    @classmethod
    async def complete_settlement_batch(
        cls,
        db: AsyncSessionLocal,
        batch_id: UUID,
        utr_ref: str,
        payout_method: str,
        actor_id: UUID
    ) -> SettlementBatch:
        """
        Super Admin marks the batch as COMPLETED once payout is processed, registering UTR.
        Updates all linked ledger entries to is_settled = True.
        """
        stmt = select(SettlementBatch).filter(SettlementBatch.id == batch_id).with_for_update()
        res = await db.execute(stmt)
        batch = res.scalar_one_or_none()
        if not batch:
            raise ValueError("Settlement batch not found")

        if batch.status == "COMPLETED":
            return batch

        now = datetime.now(timezone.utc)
        batch.status = "COMPLETED"
        batch.payout_reference = utr_ref
        batch.payout_method = payout_method.upper()
        batch.settled_at = now
        batch.payout_initiated_at = now

        # Update all ledger entries linked to this batch
        update_stmt = (
            update(OnlineSettlementLedger)
            .where(OnlineSettlementLedger.settlement_batch_id == batch.id)
            .values(is_settled=True, settled_at=now)
        )
        await db.execute(update_stmt)
        await db.flush()

        # Emit audit log
        await ActivityLogService.emit_event(
            db=db,
            temple_id=batch.temple_id,
            module_name="FINANCE",
            entity_name="SettlementBatch",
            entity_id=str(batch.id),
            action_type="SETTLEMENT_BATCH_COMPL",
            action_category="GOVERNANCE_FINANCE",
            description=f"Settlement batch {batch.batch_ref} completed. UTR: {utr_ref}",
            before_value={"status": batch.status},
            after_value={"status": "COMPLETED", "utr": utr_ref},
            performed_by_user_id=actor_id,
            performed_by_name="Super Admin / Finance",
            performed_by_role="SUPERADMIN",
            severity="HIGH",
            risk_score=40
        )
        await db.commit()
        return batch

    @classmethod
    async def get_temple_settlement_dashboard(cls, db: AsyncSessionLocal, temple_id: UUID) -> Dict[str, Any]:
        """
        Calculate pending balance and fetch history for a temple manager dashboard.
        """
        # Sum credits & debits where settlement_batch_id IS NULL
        ledger_stmt = select(OnlineSettlementLedger.temple_net_amount).filter(
            OnlineSettlementLedger.temple_id == temple_id,
            OnlineSettlementLedger.is_settled == False
        )
        ledger_res = await db.execute(ledger_stmt)
        amounts = ledger_res.scalars().all()
        pending_balance = sum(amounts)

        # Get last completed batch
        last_batch_stmt = select(SettlementBatch).filter(
            SettlementBatch.temple_id == temple_id,
            SettlementBatch.status == "COMPLETED"
        ).order_by(SettlementBatch.settled_at.desc()).limit(1)
        last_batch_res = await db.execute(last_batch_stmt)
        last_batch = last_batch_res.scalar_one_or_none()

        last_payout = None
        if last_batch:
            last_payout = {
                "amount": last_batch.net_payout_amount,
                "date": last_batch.settled_at,
                "utr": last_batch.payout_reference
            }

        # Get history of batches
        history_stmt = select(SettlementBatch).filter(
            SettlementBatch.temple_id == temple_id
        ).order_by(SettlementBatch.created_at.desc()).limit(10)
        history_res = await db.execute(history_stmt)
        history = history_res.scalars().all()

        history_list = []
        for batch in history:
            history_list.append({
                "batch_id": str(batch.id),
                "batch_ref": batch.batch_ref,
                "period_start": batch.period_start,
                "period_end": batch.period_end,
                "amount": batch.net_payout_amount,
                "status": batch.status,
                "utr": batch.payout_reference,
                "settled_at": batch.settled_at
            })

        return {
            "pending_balance": pending_balance,
            "last_payout": last_payout,
            "history": history_list
        }

    @classmethod
    async def get_admin_finance_overview(cls, db: AsyncSessionLocal) -> Dict[str, Any]:
        """
        Calculate total platform revenue and pending payouts for Super Admin dashboard.
        """
        # Sum convenience fee splits from ledger
        revenue_stmt = select(
            func.sum(OnlineSettlementLedger.gross_convenience_fee),
            func.sum(OnlineSettlementLedger.gst_component),
            func.sum(OnlineSettlementLedger.gateway_fee),
            func.sum(OnlineSettlementLedger.net_platform_revenue)
        )
        res = await db.execute(revenue_stmt)
        row = res.fetchone()
        
        gross_fee = row[0] or 0.0 if row else 0.0
        gst = row[1] or 0.0 if row else 0.0
        gateway_fee = row[2] or 0.0 if row else 0.0
        net_revenue = row[3] or 0.0 if row else 0.0

        # Payouts status aggregation
        status_stmt = select(
            SettlementBatch.status,
            func.sum(SettlementBatch.net_payout_amount),
            func.count(SettlementBatch.id)
        ).group_by(SettlementBatch.status)
        status_res = await db.execute(status_stmt)
        payouts_by_status = {}
        for st, amt, cnt in status_res.fetchall():
            payouts_by_status[st] = {
                "amount": amt or 0.0,
                "count": cnt
            }

        return {
            "platform_revenue": {
                "gross_convenience_fee": gross_fee,
                "gst_absorbed": gst,
                "gateway_fees_absorbed": gateway_fee,
                "net_platform_revenue": net_revenue
            },
            "payouts": payouts_by_status
        }
