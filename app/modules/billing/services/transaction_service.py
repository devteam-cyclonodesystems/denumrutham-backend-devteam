"""Transaction Service — Creates and queries financial transactions."""
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.modules.billing.models.billing_models import Transaction, TransactionType, TransactionCategory

logger = logging.getLogger("tms.services.transaction")


class TransactionService:
    """Single source of truth for all money flows."""

    @staticmethod
    async def create_transaction(
        db: AsyncSession,
        temple_id: str,
        txn_type: str,
        category: str,
        amount: float,
        description: str = "",
        reference_id: str = None,
        source: str = "system",
    ) -> Transaction:
        tid = UUID(str(temple_id))
        txn = Transaction(
            temple_id=tid,
            type=TransactionType(txn_type),
            category=TransactionCategory(category),
            amount=amount,
            description=description,
            reference_id=reference_id,
            source=source,
        )
        db.add(txn)
        await db.flush()
        await db.refresh(txn)
        logger.info("Transaction created: %s %s ₹%.2f ref=%s", txn_type, category, amount, reference_id)
        
        # Emit standardized audit log
        from app.modules.audit.services.activity_log_service import ActivityLogService
        action_type = "INCOME_CREATED" if txn_type == "income" else "EXPENSE_CREATED"
        if category.lower() in ("adjustment", "correction"):
            action_type = "FINANCE_LEDGER_ADJUSTED"

        await ActivityLogService.emit_event(
            db=db,
            temple_id=tid,
            module_name="FINANCE",
            entity_name="Transaction",
            entity_id=str(txn.id),
            action_type=action_type,
            action_category="TRANSACTION_FINANCE",
            description=f"Transaction {action_type} - {description} (Amount: INR {amount:.2f}).",
            before_value=None,
            after_value={"type": txn_type, "category": category, "amount": amount},
            performed_by_user_id=None,
            performed_by_name="System / Finance Service",
            performed_by_role="MANAGER",
            severity="MEDIUM",
            risk_score=10
        )

        # Invalidate finance dashboard cache
        from app.modules.finance.services.finance_service import FinanceService
        await FinanceService.invalidate_dashboard_cache(tid)

        return txn

    @staticmethod
    async def get_transactions(
        db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 100
    ):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(Transaction)
            .filter(Transaction.temple_id == tid)
            .order_by(Transaction.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def get_total_income(db: AsyncSession, temple_id: str) -> float:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0.0))
            .filter(Transaction.temple_id == tid, Transaction.type == TransactionType.INCOME)
        )
        return float(result.scalar())

    @staticmethod
    async def get_total_expense(db: AsyncSession, temple_id: str) -> float:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0.0))
            .filter(Transaction.temple_id == tid, Transaction.type == TransactionType.EXPENSE)
        )
        return float(result.scalar())

    @staticmethod
    async def get_recent(db: AsyncSession, temple_id: str, limit: int = 10):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(Transaction)
            .filter(Transaction.temple_id == tid)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
