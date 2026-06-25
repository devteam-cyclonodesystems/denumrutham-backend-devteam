"""Dashboard Service — Aggregates data from transactions, bookings, employees."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.transaction_service import TransactionService
from app.services.archana_service import ArchanaService
from app.services.employee_service import EmployeeService
from app.repositories.archana_repository import ArchanaRepository
from app.models.domain import HallBooking
from sqlalchemy.future import select
from sqlalchemy import func
from uuid import UUID

logger = logging.getLogger("tms.services.dashboard")


class DashboardService:

    @staticmethod
    async def get_summary(db: AsyncSession, temple_id: str) -> dict:
        from datetime import datetime, time, date
        from app.modules.auth.models.auth_models import User
        from app.modules.billing.models.billing_models import Transaction, TransactionType
        from app.modules.governance.models.governance_models import ChangeRequest, ApprovalRequest
        from app.modules.bookings.models.archana import ArchanaBooking
        from app.modules.inventory.models.inventory_models import InventoryItem
        from app.modules.attendance.models.attendance_models import Leave
        from app.modules.temple_management.models.temple_models import TempleProfile
        from app.modules.bookings.models.booking_models import HallBooking
        
        tid = UUID(str(temple_id))
        today_start = datetime.combine(date.today(), time.min)
        
        # 1. Financials
        total_income = await TransactionService.get_total_income(db, temple_id)
        total_expense = await TransactionService.get_total_expense(db, temple_id)
        
        # Today's Revenue
        today_rev_res = await db.execute(
            select(func.sum(Transaction.amount))
            .filter(Transaction.temple_id == tid, Transaction.type == TransactionType.INCOME, Transaction.created_at >= today_start)
        )
        today_income = today_rev_res.scalar() or 0

        # 2. Bookings
        total_bookings = await ArchanaRepository.get_booking_count(db, temple_id)
        
        # Today's Bookings
        today_bk_res = await db.execute(
            select(func.count(ArchanaBooking.id))
            .filter(ArchanaBooking.temple_id == tid, ArchanaBooking.created_at >= today_start)
        )
        today_bookings = today_bk_res.scalar() or 0

        # Hall bookings count
        hb_result = await db.execute(
            select(func.count(HallBooking.id)).filter(HallBooking.temple_id == tid)
        )
        total_hall_bookings = hb_result.scalar() or 0

        # 3. Staffing & HR
        employee_count = await EmployeeService.get_employee_count(db, temple_id)
        
        staff_res = await db.execute(
            select(func.count(User.id)).filter(User.temple_id == tid, User.role == "STAFF")
        )
        staff_count = staff_res.scalar() or 0

        active_staff_res = await db.execute(
            select(func.count(User.id)).filter(User.temple_id == tid, User.role == "STAFF", User.status == "ACTIVE")
        )
        active_staff_count = active_staff_res.scalar() or 0

        # Pending Leaves
        leaves_res = await db.execute(
            select(func.count(Leave.id)).filter(Leave.temple_id == tid, Leave.status == "pending")
        )
        pending_leaves = leaves_res.scalar() or 0

        # 4. Inventory
        low_stock_res = await db.execute(
            select(func.count(InventoryItem.id))
            .filter(InventoryItem.temple_id == tid, InventoryItem.stock < InventoryItem.min_stock)
        )
        low_inventory_count = low_stock_res.scalar() or 0

        # 5. Workflows & Approvals
        # Comprehensive pending count: ChangeRequests + ApprovalRequests
        cr_res = await db.execute(
            select(func.count(ChangeRequest.id)).filter(ChangeRequest.temple_id == tid, ChangeRequest.status == "PENDING")
        )
        pending_cr = cr_res.scalar() or 0
        
        ar_res = await db.execute(
            select(func.count(ApprovalRequest.id)).filter(ApprovalRequest.temple_id == tid, ApprovalRequest.status == "pending")
        )
        pending_ar = ar_res.scalar() or 0
        
        pending_approvals = pending_cr + pending_ar
        active_workflows = pending_cr # ChangeRequests act as field-level workflows

        # 6. Live Streams
        stream_res = await db.execute(
            select(func.count(TempleProfile.id))
            .filter(TempleProfile.temple_id == tid, TempleProfile.live_stream_url != "")
        )
        live_streams_active = stream_res.scalar() or 0

        # 7. Recent Activities
        recent_transactions = await TransactionService.get_recent(db, temple_id, limit=10)

        return {
            "total_income": total_income,
            "today_income": today_income,
            "total_expense": total_expense,
            "total_bookings": total_bookings,
            "today_bookings": today_bookings,
            "total_hall_bookings": total_hall_bookings,
            "employee_count": employee_count,
            "staff_count": staff_count,
            "active_staff_count": active_staff_count,
            "pending_leaves": pending_leaves,
            "low_inventory_count": low_inventory_count,
            "pending_approvals": pending_approvals,
            "active_workflows": active_workflows,
            "live_streams_active": live_streams_active,
            "attendance_summary": {
                "present": active_staff_count, # Mocked
                "total": staff_count
            },
            "recent_transactions": recent_transactions,
        }
