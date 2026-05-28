"""
Accounting & Billing Service Module

Purpose:
Handles financial transactions, cash sessions, and daily ledger settlements.

Responsibilities:
- Manages income/expense bookkeeping categories
- Operator shift closures and reconciliation reporting
- Integrates with Stripe/UPI payment methods

Operational Notes:
- Transactional safety is critical; all actions run under db.begin() block
- Audit logs generated for every cash session mutation
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from uuid import UUID
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from app.models.accounting import FinancialLedgerEntry, LedgerEntryType, DailySettlement, CashSession, BookingAdjustment
from app.models.archana import EnterpriseArchanaBooking

class AccountingService:
    @staticmethod
    async def record_booking_ledger(
        db: AsyncSession,
        temple_id: UUID,
        booking: EnterpriseArchanaBooking,
        recorded_by: Optional[UUID] = None
    ) -> FinancialLedgerEntry:
        """Records a booking into the financial ledger."""
        entry = FinancialLedgerEntry(
            temple_id=temple_id,
            entry_type=LedgerEntryType.BOOKING,
            ref_id=booking.ref_id,
            amount=booking.grand_total,
            payment_mode=booking.payment_mode,
            temple_revenue=booking.total_amount,
            priest_dakshina=booking.dakshina,
            recorded_by=recorded_by,
            description=f"Archana Booking {booking.ref_id} for {booking.primary_devotee_name}",
            sync_status="SYNCED"
        )
        db.add(entry)
        return entry

    @staticmethod
    async def get_financial_kpis(db: AsyncSession, temple_id: UUID) -> Dict[str, Any]:
        """Aggregates financial KPIs for the dashboard."""
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Today's Revenue
        query = select(func.sum(FinancialLedgerEntry.amount)).filter(
            FinancialLedgerEntry.temple_id == temple_id,
            FinancialLedgerEntry.created_at >= today
        )
        res = await db.execute(query)
        today_revenue = res.scalar() or 0.0
        
        # Cash in Hand (Today's Cash)
        query = select(func.sum(FinancialLedgerEntry.amount)).filter(
            FinancialLedgerEntry.temple_id == temple_id,
            FinancialLedgerEntry.created_at >= today,
            FinancialLedgerEntry.payment_mode == "Cash"
        )
        res = await db.execute(query)
        cash_in_hand = res.scalar() or 0.0
        
        # Dakshina Liability
        query = select(func.sum(FinancialLedgerEntry.priest_dakshina)).filter(
            FinancialLedgerEntry.temple_id == temple_id,
            FinancialLedgerEntry.created_at >= today
        )
        res = await db.execute(query)
        dakshina_liability = res.scalar() or 0.0
        
        return {
            "today_revenue": today_revenue,
            "cash_in_hand": cash_in_hand,
            "dakshina_liability": dakshina_liability,
            "pending_settlement": today_revenue,
            "revenue_trend": "+12.5%", # Placeholder
            "top_ritual_revenue": 5400, # Placeholder
            "booking_source_revenue": {"Counter": today_revenue, "Online": 0}
        }

    @staticmethod
    async def close_day(
        db: AsyncSession, 
        temple_id: UUID, 
        actual_total: float, 
        closed_by: UUID,
        variance_reason: Optional[str] = None
    ) -> DailySettlement:
        """Closes the current business day."""
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Aggregate today's entries
        query = select(
            func.sum(FinancialLedgerEntry.amount).label("total"),
            func.sum(FinancialLedgerEntry.temple_revenue).label("revenue"),
            func.sum(FinancialLedgerEntry.priest_dakshina).label("dakshina"),
            func.sum(FinancialLedgerEntry.donation_portion).label("donations")
        ).filter(
            FinancialLedgerEntry.temple_id == temple_id,
            FinancialLedgerEntry.created_at >= today
        )
        res = await db.execute(query)
        aggregates = res.one_or_none()
        
        expected_total = 0.0
        if aggregates:
            expected_total = (aggregates.total or 0.0)
        
        # Separate by payment mode
        modes_query = select(
            FinancialLedgerEntry.payment_mode,
            func.sum(FinancialLedgerEntry.amount)
        ).filter(
            FinancialLedgerEntry.temple_id == temple_id,
            FinancialLedgerEntry.created_at >= today
        ).group_by(FinancialLedgerEntry.payment_mode)
        
        modes_res = await db.execute(modes_query)
        modes_data = dict(modes_res.all())
        
        settlement = DailySettlement(
            temple_id=temple_id,
            settlement_date=today,
            total_cash=modes_data.get("Cash", 0.0),
            total_upi=modes_data.get("UPI", 0.0),
            total_card=modes_data.get("Card", 0.0),
            total_dakshina=(aggregates.dakshina if aggregates else 0.0) or 0.0,
            total_donations=(aggregates.donations if aggregates else 0.0) or 0.0,
            expected_total=expected_total,
            actual_total=actual_total,
            variance=actual_total - expected_total,
            variance_reason=variance_reason,
            status="CLOSED",
            closed_by=closed_by,
            closed_at=datetime.now(timezone.utc)
        )
        db.add(settlement)
        
        await db.flush()
        return settlement
