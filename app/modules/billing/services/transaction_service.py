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
