"""Offerings Module — Service layer (static async methods)."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, desc, or_
from uuid import UUID
import uuid
from datetime import datetime, timezone, timedelta

from app.models.offering import (
    Offering, OfferingCategory, OfferingPayment, OfferingReceipt,
    OfferingAuditLog, OfferingInventoryLink, OfferingReconciliation,
)
from app.schemas.offering import (
    OfferingCreate, OfferingUpdate, OfferingPaymentCreate,
    OfferingCategoryCreate, OfferingCategoryUpdate,
)

logger = logging.getLogger("tms.services.offering")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OfferingService:
    """Stateless service facade for the Offerings module."""

    # ----------------------------------------------------------------
    # Payment-status helper
    # ----------------------------------------------------------------
    @staticmethod
    def _compute_payment_status(total: float, paid: float) -> str:
        if paid <= 0:
            return "PENDING"
        if paid < total:
            return "PARTIAL"
        if paid == total:
            return "FULLY_PAID"
        return "OVERPAID"

    # ================================================================
    #  CATEGORIES
    # ================================================================
    @staticmethod
    async def get_categories(db: AsyncSession, temple_id: str, include_inactive: bool = False):
        tid = UUID(str(temple_id))
        query = select(OfferingCategory).filter(OfferingCategory.temple_id == tid)
        if not include_inactive:
            query = query.filter(OfferingCategory.is_active == True)
        result = await db.execute(query.order_by(OfferingCategory.created_at))
        return result.scalars().all()

    @staticmethod
    async def create_category(
        db: AsyncSession, data: OfferingCategoryCreate, temple_id: str
    ) -> OfferingCategory:
        tid = UUID(str(temple_id))
        cat = OfferingCategory(
            temple_id=tid,
            category_name=data.category_name,
            category_code=data.category_code,
            receipt_prefix=data.receipt_prefix,
            color_code=data.color_code,
            icon=data.icon,
        )
        db.add(cat)
        await db.commit()
        await db.refresh(cat)
        return cat

    @staticmethod
    async def update_category(
        db: AsyncSession, category_id: str, data: OfferingCategoryUpdate, temple_id: str
    ):
        tid = UUID(str(temple_id))
        cid = UUID(str(category_id))
        result = await db.execute(
            select(OfferingCategory).filter(
                OfferingCategory.id == cid, OfferingCategory.temple_id == tid
            )
        )
        cat = result.scalar_one_or_none()
        if not cat:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(cat, key, value)
        await db.commit()
        await db.refresh(cat)
        return cat

    # ================================================================
    #  CORE CRUD
    # ================================================================
    @staticmethod
    async def create_offering(
        db: AsyncSession,
        data: OfferingCreate,
        temple_id: str,
        created_by: str,
    ) -> Offering:
        tid = UUID(str(temple_id))
        now = data.created_at
        if now:
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
        else:
            now = _utcnow()
        year = now.year

        # --- auto-generate offering number ---
        count_result = await db.execute(
            select(func.count(Offering.id)).filter(
                Offering.temple_id == tid,
                func.extract("year", Offering.created_at) == year,
            )
        )
        seq = (count_result.scalar() or 0) + 1
        offering_number = f"OFF-{year}-{seq:06d}"

        # --- compute financials ---
        paid = data.paid_amount or 0
        balance = data.total_amount - paid
        status = OfferingService._compute_payment_status(data.total_amount, paid)

        offering = Offering(
            temple_id=tid,
            offering_number=offering_number,
            donor_name=data.donor_name,
            donor_phone=data.donor_phone,
            donor_address=data.donor_address,
            category_id=data.category_id,
            total_amount=data.total_amount,
            paid_amount=paid,
            balance_amount=balance,
            payment_status=status,
            payment_method=data.payment_method,
            booking_mode=data.booking_mode or "Counter",
            remarks=data.remarks,
            offering_status="CONFIRMED",
            created_by=created_by,
            created_at=now,
        )
        db.add(offering)
        await db.flush()

        # --- initial payment record ---
        if paid > 0 and data.payment_method:
            txn_count = await db.execute(
                select(func.count(OfferingPayment.id)).filter(
                    OfferingPayment.offering_id == offering.id,
                )
            )
            txn_seq = (txn_count.scalar() or 0) + 1
            txn_number = f"TXN-{year}-{txn_seq:06d}"
            payment = OfferingPayment(
                offering_id=offering.id,
                transaction_number=txn_number,
                payment_method=data.payment_method,
                amount=paid,
                received_by=created_by,
                payment_date=now,
                created_at=now,
            )
            db.add(payment)

        # --- inventory link (metal offerings) ---
        if data.metal_type and data.metal_weight is not None:
            inv_link = OfferingInventoryLink(
                offering_id=offering.id,
                metal_type=data.metal_type,
                purity=data.metal_purity,
                weight=data.metal_weight,
                estimated_value=data.metal_estimated_value if data.metal_estimated_value is not None else 0.0,
                locker_reference=data.metal_locker,
            )
            db.add(inv_link)

        # --- audit log ---
        await OfferingService._log_audit(
            db=db,
            offering_id=offering.id,
            temple_id=temple_id,
            action_type="CREATED",
            changed_by=created_by,
            new_value={
                "offering_number": offering_number,
                "donor_name": data.donor_name,
                "total_amount": data.total_amount,
                "paid_amount": paid,
            },
        )

        await db.commit()
        await db.refresh(offering)
        return offering

    # ----------------------------------------------------------------
    @staticmethod
    async def get_offerings(
        db: AsyncSession,
        temple_id: str,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        category_id: str | None = None,
        payment_status: str | None = None,
        booking_mode: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ):
        tid = UUID(str(temple_id))

        base = (
            select(
                Offering,
                OfferingCategory.category_name,
            )
            .outerjoin(OfferingCategory, Offering.category_id == OfferingCategory.id)
            .filter(Offering.temple_id == tid, Offering.deleted_at.is_(None))
        )

        # --- filters ---
        if search:
            pattern = f"%{search}%"
            base = base.filter(
                or_(
                    Offering.donor_name.ilike(pattern),
                    Offering.donor_phone.ilike(pattern),
                    Offering.offering_number.ilike(pattern),
                )
            )
        if category_id:
            base = base.filter(Offering.category_id == UUID(str(category_id)))
        if payment_status:
            base = base.filter(Offering.payment_status == payment_status)
        if booking_mode:
            base = base.filter(Offering.booking_mode == booking_mode)
        if date_from:
            base = base.filter(Offering.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            # Include the full day
            base = base.filter(Offering.created_at <= datetime.fromisoformat(date_to) + timedelta(days=1))

        # --- count ---
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        # --- paginate ---
        offset = (page - 1) * page_size
        rows_q = base.order_by(Offering.created_at.desc()).offset(offset).limit(page_size)
        rows = (await db.execute(rows_q)).all()

        items = []
        for row in rows:
            offering = row[0]
            cat_name = row[1]
            d = {c.key: getattr(offering, c.key) for c in offering.__table__.columns}
            d["category_name"] = cat_name
            items.append(d)

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ----------------------------------------------------------------
    @staticmethod
    async def get_offering_detail(db: AsyncSession, offering_id: str, temple_id: str):
        tid = UUID(str(temple_id))
        oid = UUID(str(offering_id))

        # Offering + category name
        result = await db.execute(
            select(Offering, OfferingCategory.category_name)
            .outerjoin(OfferingCategory, Offering.category_id == OfferingCategory.id)
            .filter(Offering.id == oid, Offering.temple_id == tid, Offering.deleted_at.is_(None))
        )
        row = result.first()
        if not row:
            return None

        offering = row[0]
        cat_name = row[1]

        # Payments
        pay_result = await db.execute(
            select(OfferingPayment)
            .filter(OfferingPayment.offering_id == oid)
            .order_by(OfferingPayment.created_at)
        )
        payments = pay_result.scalars().all()

        # Audit logs
        audit_result = await db.execute(
            select(OfferingAuditLog)
            .filter(OfferingAuditLog.offering_id == oid, OfferingAuditLog.temple_id == tid)
            .order_by(OfferingAuditLog.changed_at.desc())
        )
        audit_logs = audit_result.scalars().all()

        # Inventory links
        inv_result = await db.execute(
            select(OfferingInventoryLink)
            .filter(OfferingInventoryLink.offering_id == oid)
        )
        inventory_links = inv_result.scalars().all()

        # Receipt
        receipt = None
        if offering.receipt_id:
            rcpt_result = await db.execute(
                select(OfferingReceipt).filter(OfferingReceipt.id == offering.receipt_id)
            )
            receipt = rcpt_result.scalar_one_or_none()

        detail = {c.key: getattr(offering, c.key) for c in offering.__table__.columns}
        detail["category_name"] = cat_name
        detail["payments"] = payments
        detail["audit_logs"] = audit_logs
        detail["inventory_links"] = inventory_links
        detail["receipt"] = receipt
        return detail

    # ----------------------------------------------------------------
    @staticmethod
    async def update_offering(
        db: AsyncSession,
        offering_id: str,
        data: OfferingUpdate,
        temple_id: str,
        changed_by: str,
    ):
        tid = UUID(str(temple_id))
        oid = UUID(str(offering_id))
        result = await db.execute(
            select(Offering).filter(
                Offering.id == oid, Offering.temple_id == tid, Offering.deleted_at.is_(None)
            )
        )
        offering = result.scalar_one_or_none()
        if not offering:
            return None

        update_data = data.model_dump(exclude_unset=True)
        old_values = {}
        for key in update_data:
            old_values[key] = getattr(offering, key)
            setattr(offering, key, update_data[key])

        offering.sync_version = (offering.sync_version or 1) + 1

        await OfferingService._log_audit(
            db=db,
            offering_id=offering.id,
            temple_id=temple_id,
            action_type="UPDATED",
            changed_by=changed_by,
            old_value=old_values,
            new_value=update_data,
        )

        await db.commit()
        await db.refresh(offering)
        return offering

    # ----------------------------------------------------------------
    @staticmethod
    async def delete_offering(
        db: AsyncSession, offering_id: str, temple_id: str, changed_by: str
    ):
        tid = UUID(str(temple_id))
        oid = UUID(str(offering_id))
        result = await db.execute(
            select(Offering).filter(
                Offering.id == oid, Offering.temple_id == tid, Offering.deleted_at.is_(None)
            )
        )
        offering = result.scalar_one_or_none()
        if not offering:
            return False

        offering.deleted_at = _utcnow()
        offering.offering_status = "CANCELLED"

        await OfferingService._log_audit(
            db=db,
            offering_id=offering.id,
            temple_id=temple_id,
            action_type="DELETED",
            changed_by=changed_by,
            old_value={"offering_status": "CONFIRMED"},
            new_value={"offering_status": "CANCELLED", "deleted_at": offering.deleted_at.isoformat()},
        )

        await db.commit()
        return True

    # ================================================================
    #  PAYMENTS
    # ================================================================
    @staticmethod
    async def add_payment(
        db: AsyncSession,
        offering_id: str,
        data: OfferingPaymentCreate,
        temple_id: str,
        received_by: str,
    ):
        tid = UUID(str(temple_id))
        oid = UUID(str(offering_id))

        # Verify offering belongs to temple
        result = await db.execute(
            select(Offering).filter(
                Offering.id == oid, Offering.temple_id == tid, Offering.deleted_at.is_(None)
            )
        )
        offering = result.scalar_one_or_none()
        if not offering:
            return None

        year = _utcnow().year
        # auto-generate transaction number
        txn_count_result = await db.execute(
            select(func.count(OfferingPayment.id)).filter(
                OfferingPayment.offering_id == oid,
            )
        )
        txn_seq = (txn_count_result.scalar() or 0) + 1
        txn_number = f"TXN-{year}-{txn_seq:06d}"

        payment = OfferingPayment(
            offering_id=oid,
            transaction_number=txn_number,
            payment_method=data.payment_method,
            amount=data.amount,
            gateway_reference=data.gateway_reference,
            received_by=received_by,
            notes=data.notes,
        )
        db.add(payment)

        # Update offering financials
        old_paid = offering.paid_amount or 0
        new_paid = old_paid + data.amount
        offering.paid_amount = new_paid
        offering.balance_amount = offering.total_amount - new_paid
        offering.payment_status = OfferingService._compute_payment_status(
            offering.total_amount, new_paid
        )

        await OfferingService._log_audit(
            db=db,
            offering_id=offering.id,
            temple_id=temple_id,
            action_type="PAYMENT_ADDED",
            changed_by=received_by,
            old_value={"paid_amount": old_paid},
            new_value={
                "paid_amount": new_paid,
                "payment_amount": data.amount,
                "payment_method": data.payment_method,
                "transaction_number": txn_number,
            },
        )

        await db.commit()
        await db.refresh(payment)
        return payment

    @staticmethod
    async def get_payments(db: AsyncSession, offering_id: str, temple_id: str):
        tid = UUID(str(temple_id))
        oid = UUID(str(offering_id))

        # Verify offering belongs to temple
        result = await db.execute(
            select(Offering.id).filter(Offering.id == oid, Offering.temple_id == tid)
        )
        if not result.scalar_one_or_none():
            return None

        pay_result = await db.execute(
            select(OfferingPayment)
            .filter(OfferingPayment.offering_id == oid)
            .order_by(OfferingPayment.created_at)
        )
        return pay_result.scalars().all()

    # ================================================================
    #  AUDIT
    # ================================================================
    @staticmethod
    async def get_audit_trail(db: AsyncSession, offering_id: str, temple_id: str):
        tid = UUID(str(temple_id))
        oid = UUID(str(offering_id))
        result = await db.execute(
            select(OfferingAuditLog)
            .filter(OfferingAuditLog.offering_id == oid, OfferingAuditLog.temple_id == tid)
            .order_by(OfferingAuditLog.changed_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def _log_audit(
        db: AsyncSession,
        offering_id,
        temple_id: str,
        action_type: str,
        changed_by: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
    ):
        tid = UUID(str(temple_id))
        oid = offering_id if isinstance(offering_id, uuid.UUID) else UUID(str(offering_id)) if offering_id else None
        entry = OfferingAuditLog(
            offering_id=oid,
            temple_id=tid,
            action_type=action_type,
            changed_by=changed_by,
            old_value=old_value,
            new_value=new_value,
        )
        db.add(entry)

    # ================================================================
    #  SUMMARY
    # ================================================================
    @staticmethod
    async def get_summary(
        db: AsyncSession,
        temple_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ):
        tid = UUID(str(temple_id))
        now = _utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Parse date range securely with timezone safety
        d_from = None
        if date_from:
            try:
                d_from = datetime.fromisoformat(date_from)
                if d_from.tzinfo is None:
                    d_from = d_from.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        d_to = None
        if date_to:
            try:
                # Include the end day fully
                parsed_to = datetime.fromisoformat(date_to)
                if parsed_to.tzinfo is None:
                    parsed_to = parsed_to.replace(tzinfo=timezone.utc)
                d_to = parsed_to + timedelta(days=1)
            except ValueError:
                pass

        base_filter = and_(Offering.temple_id == tid, Offering.deleted_at.is_(None))
        receipt_filter = OfferingReceipt.temple_id == tid

        # Apply date filters if provided
        if d_from:
            base_filter = and_(base_filter, Offering.created_at >= d_from)
            receipt_filter = and_(receipt_filter, OfferingReceipt.generated_at >= d_from)
        if d_to:
            base_filter = and_(base_filter, Offering.created_at < d_to)
            receipt_filter = and_(receipt_filter, OfferingReceipt.generated_at < d_to)

        # Total offerings amount
        total_q = await db.execute(
            select(func.coalesce(func.sum(Offering.total_amount), 0)).filter(base_filter)
        )
        total_offerings = total_q.scalar() or 0

        # Unique donors
        donor_q = await db.execute(
            select(func.count(func.distinct(Offering.donor_name))).filter(base_filter)
        )
        total_donors = donor_q.scalar() or 0

        # Receipts count
        receipt_q = await db.execute(
            select(func.count(OfferingReceipt.id)).filter(receipt_filter)
        )
        total_receipts = receipt_q.scalar() or 0

        # Pending payments
        pending_q = await db.execute(
            select(func.count(Offering.id)).filter(
                base_filter,
                Offering.payment_status.in_(["PENDING", "PARTIAL"]),
            )
        )
        pending_payments = pending_q.scalar() or 0

        # Period / Today's totals:
        # If date parameters were provided, today_total/today_count represents the selected period's totals.
        # Otherwise, they fallback to today's totals specifically.
        if d_from or d_to:
            period_total = total_offerings
            period_count_q = await db.execute(
                select(func.count(Offering.id)).filter(base_filter)
            )
            period_count = period_count_q.scalar() or 0
        else:
            today_filter = and_(
                Offering.temple_id == tid,
                Offering.deleted_at.is_(None),
                Offering.created_at >= today_start
            )
            today_total_q = await db.execute(
                select(func.coalesce(func.sum(Offering.total_amount), 0)).filter(today_filter)
            )
            period_total = today_total_q.scalar() or 0

            today_count_q = await db.execute(
                select(func.count(Offering.id)).filter(today_filter)
            )
            period_count = today_count_q.scalar() or 0

        # Category-wise totals
        cat_q = await db.execute(
            select(
                OfferingCategory.id,
                OfferingCategory.category_name,
                func.count(Offering.id),
                func.coalesce(func.sum(Offering.total_amount), 0),
            )
            .outerjoin(OfferingCategory, Offering.category_id == OfferingCategory.id)
            .filter(base_filter)
            .group_by(OfferingCategory.id, OfferingCategory.category_name)
        )
        category_totals = [
            {
                "category_id": str(cid) if cid else None,
                "category": name or "Uncategorized",
                "count": cnt,
                "total": float(amt),
                "total_amount": float(amt)
            }
            for cid, name, cnt, amt in cat_q.all()
        ]

        return {
            "total_offerings": float(total_offerings),
            "total_donors": int(total_donors),
            "total_receipts": int(total_receipts),
            "pending_payments": int(pending_payments),
            "today_total": float(period_total),
            "today_count": int(period_count),
            "category_totals": category_totals,
        }

    # ================================================================
    #  RECONCILIATION
    # ================================================================
    @staticmethod
    async def get_today_reconciliation(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        now = _utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        base = and_(
            Offering.temple_id == tid,
            Offering.deleted_at.is_(None),
            Offering.created_at >= today_start,
        )

        # Total count
        count_q = await db.execute(select(func.count(Offering.id)).filter(base))
        total_count = count_q.scalar() or 0

        # Total amount
        total_q = await db.execute(
            select(func.coalesce(func.sum(Offering.paid_amount), 0)).filter(base)
        )
        total_amount = total_q.scalar() or 0

        # Method-wise breakdown  (aggregate from offering_payments created today)
        pay_base = and_(
            OfferingPayment.created_at >= today_start,
            OfferingPayment.offering_id.in_(
                select(Offering.id).filter(Offering.temple_id == tid, Offering.deleted_at.is_(None))
            ),
        )

        async def _method_sum(method_pattern: str) -> float:
            r = await db.execute(
                select(func.coalesce(func.sum(OfferingPayment.amount), 0)).filter(
                    pay_base,
                    OfferingPayment.payment_method.ilike(method_pattern),
                )
            )
            return float(r.scalar() or 0)

        total_cash = await _method_sum("Cash")
        total_upi = await _method_sum("UPI")
        total_card = await _method_sum("Card")
        total_other = float(total_amount) - total_cash - total_upi - total_card

        # Pending balance
        pending_q = await db.execute(
            select(func.coalesce(func.sum(Offering.balance_amount), 0)).filter(
                base, Offering.payment_status.in_(["PENDING", "PARTIAL"])
            )
        )
        pending_balance = pending_q.scalar() or 0

        # Category breakdown
        cat_q = await db.execute(
            select(
                OfferingCategory.category_name,
                func.count(Offering.id),
                func.coalesce(func.sum(Offering.paid_amount), 0),
            )
            .outerjoin(OfferingCategory, Offering.category_id == OfferingCategory.id)
            .filter(base)
            .group_by(OfferingCategory.category_name)
        )
        category_breakdown = {
            (name or "Uncategorized"): {"count": cnt, "total": float(amt)}
            for name, cnt, amt in cat_q.all()
        }

        return {
            "reconciliation_date": today_start.isoformat(),
            "total_offerings_count": total_count,
            "total_amount": float(total_amount),
            "total_cash": total_cash,
            "total_upi": total_upi,
            "total_card": total_card,
            "total_other": max(0, total_other),
            "pending_balance": float(pending_balance),
            "category_breakdown": category_breakdown,
        }

    @staticmethod
    async def close_reconciliation(
        db: AsyncSession,
        temple_id: str,
        actual_collected: float,
        notes: str | None,
        closed_by: str,
    ):
        tid = UUID(str(temple_id))
        today_data = await OfferingService.get_today_reconciliation(db, temple_id)
        expected = today_data["total_cash"]
        variance = actual_collected - expected

        recon = OfferingReconciliation(
            temple_id=tid,
            reconciliation_date=_utcnow(),
            total_offerings_count=today_data["total_offerings_count"],
            total_amount=today_data["total_amount"],
            total_cash=today_data["total_cash"],
            total_upi=today_data["total_upi"],
            total_card=today_data["total_card"],
            total_other=today_data["total_other"],
            pending_balance=today_data["pending_balance"],
            expected_total=expected,
            actual_collected=actual_collected,
            variance=variance,
            category_breakdown=today_data["category_breakdown"],
            notes=notes,
            status="CLOSED",
            closed_by=closed_by,
            closed_at=_utcnow(),
        )
        db.add(recon)
        await db.commit()
        await db.refresh(recon)
        return recon

    @staticmethod
    async def get_reconciliation_history(
        db: AsyncSession, temple_id: str, limit: int = 30
    ):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(OfferingReconciliation)
            .filter(OfferingReconciliation.temple_id == tid)
            .order_by(OfferingReconciliation.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    # ================================================================
    #  DONOR SEARCH (devotees table)
    # ================================================================
    @staticmethod
    async def search_donors(db: AsyncSession, temple_id: str, query: str):
        from app.models.domain import Devotee

        tid = UUID(str(temple_id))
        pattern = f"%{query}%"
        result = await db.execute(
            select(Devotee)
            .filter(
                Devotee.temple_id == tid,
                or_(
                    Devotee.phone.ilike(pattern),
                    Devotee.first_name.ilike(pattern),
                    Devotee.last_name.ilike(pattern),
                ),
            )
            .limit(10)
        )
        devotees = result.scalars().all()
        return [
            {
                "id": str(d.id),
                "name": f"{d.first_name} {d.last_name or ''}".strip(),
                "phone": d.phone,
            }
            for d in devotees
        ]
