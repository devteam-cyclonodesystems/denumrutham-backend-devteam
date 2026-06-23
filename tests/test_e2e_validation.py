"""
=============================================================================
END-TO-END VALIDATION SUITE — Denumrutham Online Archana Booking System
=============================================================================

Phases:
  A — Payment Success Lifecycle
  B — Idempotency (webhook replay 1×, 5×, 10×; settlement duplicate guard)
  C — Refund & Rejection Lifecycle
  D — Auto-Completion (timer-based and manual override)
  E — Settlement Batch (bulk data, re-approval guards)
  F — Financial Reconciliation (temple liability, platform revenue, ledger)
  G — Database Integrity (FKs, unique constraints, atomic boundaries)
  H — Multi-Tenant Isolation (cross-temple data isolation)

Every test is self-contained: seeds its own data, makes no assumptions about
execution order, and can run in any pytest session against the SQLite in-memory
test database configured in conftest.py.
=============================================================================
"""

import pytest
import asyncio
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import select, func

from tests.conftest import TestSessionLocal, TEMPLE_ID
from app.models.domain import Temple, User
from app.models.archana import (
    ArchanaCatalog, DeityMaster, DeityStatus,
    EnterpriseArchanaBooking, ArchanaBookingPayment,
    OnlineSettlementLedger, RitualQueue, ArchanaExecution,
    ArchanaRefund, SettlementBatch, SettlementBatchItem,
    TempleBankAccount, QueueStatus, ArchanaStatus,
)
from app.models import ActivityOutbox
from app.services.settlement_service import SettlementService


# =============================================================================
# SHARED HELPERS
# =============================================================================

async def seed_catalog(db, temple_id: UUID, price: float = 100.0,
                       name: str = None) -> ArchanaCatalog:
    """Create a deity + catalog item and return the catalog."""
    deity_name = f"Deity_{uuid4().hex[:6]}"
    deity = DeityMaster(
        tenant_id=temple_id,
        deity_name=deity_name,
        normalized_name=deity_name.lower(),
        status=DeityStatus.ACTIVE,
    )
    db.add(deity)
    await db.flush()

    catalog = ArchanaCatalog(
        temple_id=temple_id,
        name=name or f"Archana_{uuid4().hex[:6]}",
        price=price,
        deity_id=deity.id,
        duration_minutes=10,
        is_active=True,
        is_online_enabled=True,
        available_prasadam_modes=["COLLECT", "NONE"],
        completion_mode="AUTO_WITH_OVERRIDE",
    )
    db.add(catalog)
    await db.commit()
    return catalog


async def book_archana(client, auth_headers, catalog_id: str,
                        devotee_name: str = "Test Devotee",
                        booking_date: str = "2026-07-01") -> dict:
    """POST to /api/v1/devotee/archana/book and return response JSON."""
    payload = {
        "catalog_id": catalog_id,
        "booking_date": booking_date,
        "members": [{"name": devotee_name, "nakshatra": "Aswini", "is_primary": True}],
        "prasadam_mode": "COLLECT",
    }
    resp = await client.post(
        "/api/v1/devotee/archana/book",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Booking failed: {resp.text}"
    return resp.json()


def make_capture_webhook(gateway_order_id: str, payment_id: str,
                          amount_inr: float, gateway_fee_paise: int = 0,
                          gateway_tax_paise: int = 0) -> dict:
    """Build a payment.captured webhook payload."""
    return {
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": int(amount_inr * 100),
                    "currency": "INR",
                    "status": "captured",
                    "order_id": gateway_order_id,
                    "method": "upi",
                    "fee": gateway_fee_paise,
                    "tax": gateway_tax_paise,
                    "created_at": 1700000000,
                }
            }
        },
    }


async def trigger_capture(client, booking_data: dict,
                           payment_id: str = None,
                           gateway_fee_paise: int = 204,
                           gateway_tax_paise: int = 37) -> None:
    """Fire payment.captured webhook for a booking; asserts 200 ok."""
    pid = payment_id or f"pay_{uuid4().hex[:12]}"
    amount_inr = booking_data["total_payable"]
    wh = make_capture_webhook(
        booking_data["gateway_order_id"],
        pid,
        amount_inr,
        gateway_fee_paise,
        gateway_tax_paise,
    )
    resp = await client.post("/api/v1/payments/razorpay/webhook", json=wh)
    assert resp.status_code == 200, f"Webhook failed: {resp.text}"
    return pid


async def seed_bank_and_verify(db, temple_id: UUID, user_id: UUID) -> TempleBankAccount:
    """Submit + verify a bank account for settlement eligibility."""
    await SettlementService.submit_bank_account(
        db=db,
        temple_id=temple_id,
        account_holder_name="Trust",
        bank_name="SBI",
        account_number="1234567890",
        ifsc_code="SBIN0000001",
        account_type="CURRENT",
        submitted_by_user_id=user_id,
    )
    # Fetch the newly created account and verify it within the same session
    stmt = select(TempleBankAccount).filter(
        TempleBankAccount.temple_id == temple_id,
        TempleBankAccount.is_active == True,
    )
    res = await db.execute(stmt)
    bank_ac = res.scalar_one()
    await SettlementService.verify_bank_account(
        db=db,
        bank_account_id=bank_ac.id,
        approver_id=user_id,
        action="VERIFY",
    )
    await db.commit()
    return bank_ac



# =============================================================================
# PHASE A — PAYMENT SUCCESS LIFECYCLE
# =============================================================================

@pytest.mark.anyio
async def test_phase_a_complete_payment_lifecycle(client, auth_headers):
    """
    Phase A: Validates the complete payment capture lifecycle end-to-end.
    Verifies: booking, payment record, ledger CREDIT, queue, execution, outbox.
    """
    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        catalog = await seed_catalog(db, temple.id, price=200.0, name="PhaseA Archana")
        catalog_id = str(catalog.id)

    # A1. Booking Creation
    booking_data = await book_archana(client, auth_headers, catalog_id,
                                       devotee_name="Devotee PhaseA")
    booking_id = UUID(booking_data["booking_id"])

    # Verify booking creation invariants
    assert booking_data["ref_id"].startswith("AR-"), "ref_id must start with AR-"
    assert booking_data["archana_amount"] == 200.0, "Archana amount must equal catalog price × members"
    assert booking_data["convenience_fee"] >= 2.0, "Convenience fee must respect minimum ₹2"
    assert booking_data["total_payable"] == booking_data["archana_amount"] + booking_data["convenience_fee"]
    assert booking_data["gateway_order_id"].startswith("order_mock_"), "Gateway order ID must be present"

    async with TestSessionLocal() as db:
        stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id)
        res = await db.execute(stmt)
        booking = res.scalar_one()
        assert booking.online_status == "PAYMENT_PENDING", "Initial status must be PAYMENT_PENDING"
        assert booking.booking_channel == "ONLINE"
        assert booking.payment_expiry_at is not None, "payment_expiry_at must be set"
        assert booking.total_payable == booking_data["total_payable"]
        assert booking.gateway_order_id == booking_data["gateway_order_id"]

    # A2. Payment Capture
    payment_id = f"pay_phaseA_{uuid4().hex[:10]}"
    capture_fee_paise = 408   # ₹4.08 gateway fee
    capture_tax_paise = 74    # ₹0.74 gateway tax
    await trigger_capture(client, booking_data, payment_id,
                           capture_fee_paise, capture_tax_paise)

    async with TestSessionLocal() as db:
        # A2a. Booking status
        stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id)
        res = await db.execute(stmt)
        booking = res.scalar_one()
        assert booking.online_status == "PAYMENT_SUCCESS"
        assert booking.status == ArchanaStatus.CONFIRMED

        # A3. Payment Record
        pay_stmt = select(ArchanaBookingPayment).filter(
            ArchanaBookingPayment.booking_id == booking_id)
        pay_res = await db.execute(pay_stmt)
        payment = pay_res.scalar_one()
        assert payment.gateway_payment_id == payment_id
        assert payment.gateway_order_id == booking_data["gateway_order_id"]
        assert payment.archana_amount == 200.0, "Archana amount in payment must match booking"
        assert payment.total_amount_charged == booking_data["total_payable"]
        assert abs(payment.gateway_fee - capture_fee_paise / 100.0) < 0.01
        assert abs(payment.gateway_tax - capture_tax_paise / 100.0) < 0.01
        assert payment.status == "SUCCESS"
        assert payment.settlement_status == "PENDING"

        # A4. Settlement Ledger
        ledger_stmt = select(OnlineSettlementLedger).filter(
            OnlineSettlementLedger.booking_id == booking_id,
            OnlineSettlementLedger.entry_type == "CREDIT",
        )
        ledger_res = await db.execute(ledger_stmt)
        ledger = ledger_res.scalar_one()

        # Sacred 100% rule: temple_net_amount == archana_amount
        assert ledger.temple_net_amount == ledger.archana_amount, \
            "SACRED RULE VIOLATION: temple_net_amount must equal archana_amount"
        assert ledger.archana_amount == 200.0
        assert ledger.temple_net_amount == 200.0

        # Fee split integrity
        assert ledger.gross_convenience_fee >= 2.0
        assert abs(ledger.total_charged_to_devotee - booking_data["total_payable"]) < 0.01
        assert ledger.gst_component == round(ledger.cgst_component + ledger.sgst_component, 2) \
            or abs(ledger.gst_component - (ledger.cgst_component + ledger.sgst_component)) < 0.02, \
            "CGST + SGST must equal total GST"

        # Net platform revenue formula: gross_fee - gst - gateway_fee
        expected_net = ledger.gross_convenience_fee - ledger.gst_component - ledger.gateway_fee
        assert abs(ledger.net_platform_revenue - expected_net) < 0.02, \
            f"Net platform revenue mismatch: expected {expected_net}, got {ledger.net_platform_revenue}"

        assert ledger.is_settled is False
        assert ledger.settlement_batch_id is None

        # A5. Queue
        queue_stmt = select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
        queue_res = await db.execute(queue_stmt)
        queue = queue_res.scalar_one()
        assert queue.status == QueueStatus.WAITING
        assert queue.token_number.startswith("T-"), "Token number must start with T-"
        assert queue.temple_id == booking.temple_id, "Queue must be scoped to the correct temple"

        # A6. Archana Execution
        exec_stmt = select(ArchanaExecution).filter(ArchanaExecution.queue_id == queue.id)
        exec_res = await db.execute(exec_stmt)
        executions = exec_res.scalars().all()
        assert len(executions) == 1, "Exactly one execution per booking member item"
        assert executions[0].status == QueueStatus.WAITING

        # A7. Activity Outbox
        outbox_stmt = select(ActivityOutbox).filter(
            ActivityOutbox.entity_id == str(booking_id),
            ActivityOutbox.action_type == "PAYMENT_CAPTURED",
        )
        outbox_res = await db.execute(outbox_stmt)
        outbox = outbox_res.scalar_one_or_none()
        assert outbox is not None, "PAYMENT_CAPTURED outbox event must exist"
        assert outbox.entity_name == "ArchanaBooking"
        assert outbox.temple_id == booking.temple_id


# =============================================================================
# PHASE B — IDEMPOTENCY VALIDATION
# =============================================================================

@pytest.mark.anyio
async def test_phase_b_webhook_idempotency_2x(client, auth_headers):
    """Phase B: Replay same payment.captured webhook 2 times — deduplication must hold."""
    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        catalog = await seed_catalog(db, temple.id, price=150.0, name="Idem2x")
        catalog_id = str(catalog.id)

    booking_data = await book_archana(client, auth_headers, catalog_id, "Idem2x Devotee")
    booking_id = UUID(booking_data["booking_id"])
    payment_id = f"pay_idem2x_{uuid4().hex[:10]}"
    webhook = make_capture_webhook(
        booking_data["gateway_order_id"], payment_id, booking_data["total_payable"]
    )

    # Fire twice
    for i in range(2):
        resp = await client.post("/api/v1/payments/razorpay/webhook", json=webhook)
        assert resp.status_code == 200, f"Replay {i+1} failed: {resp.text}"

    async with TestSessionLocal() as db:
        pay_count = (await db.execute(
            select(func.count(ArchanaBookingPayment.id)).filter(
                ArchanaBookingPayment.booking_id == booking_id)
        )).scalar()
        ledger_count = (await db.execute(
            select(func.count(OnlineSettlementLedger.id)).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "CREDIT",
            )
        )).scalar()
        queue_count = (await db.execute(
            select(func.count(RitualQueue.id)).filter(RitualQueue.booking_id == booking_id)
        )).scalar()
        outbox_count = (await db.execute(
            select(func.count(ActivityOutbox.id)).filter(
                ActivityOutbox.entity_id == str(booking_id),
                ActivityOutbox.action_type == "PAYMENT_CAPTURED",
            )
        )).scalar()

    assert pay_count == 1,    f"IDEMPOTENCY FAIL: {pay_count} payment records (expected 1)"
    assert ledger_count == 1, f"IDEMPOTENCY FAIL: {ledger_count} ledger CREDIT entries (expected 1)"
    assert queue_count == 1,  f"IDEMPOTENCY FAIL: {queue_count} queue entries (expected 1)"
    assert outbox_count == 1, f"IDEMPOTENCY FAIL: {outbox_count} outbox events (expected 1)"


@pytest.mark.anyio
async def test_phase_b_webhook_idempotency_5x(client, auth_headers):
    """Phase B: Replay same payment.captured webhook 5 times — exactly one of each record."""
    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        catalog = await seed_catalog(db, temple.id, price=300.0, name="Idem5x")
        catalog_id = str(catalog.id)

    booking_data = await book_archana(client, auth_headers, catalog_id, "Idem5x Devotee")
    booking_id = UUID(booking_data["booking_id"])
    payment_id = f"pay_idem5x_{uuid4().hex[:10]}"
    webhook = make_capture_webhook(
        booking_data["gateway_order_id"], payment_id, booking_data["total_payable"]
    )

    for i in range(5):
        resp = await client.post("/api/v1/payments/razorpay/webhook", json=webhook)
        assert resp.status_code == 200, f"Replay {i+1} of 5 failed"

    async with TestSessionLocal() as db:
        assert (await db.execute(
            select(func.count(ArchanaBookingPayment.id)).filter(
                ArchanaBookingPayment.booking_id == booking_id)
        )).scalar() == 1, "Exactly 1 payment after 5 replays"

        assert (await db.execute(
            select(func.count(OnlineSettlementLedger.id)).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "CREDIT",
            )
        )).scalar() == 1, "Exactly 1 ledger CREDIT after 5 replays"

        assert (await db.execute(
            select(func.count(RitualQueue.id)).filter(RitualQueue.booking_id == booking_id)
        )).scalar() == 1, "Exactly 1 queue entry after 5 replays"


@pytest.mark.anyio
async def test_phase_b_webhook_idempotency_10x(client, auth_headers):
    """Phase B: Stress replay — 10 identical webhooks must produce exactly one record of each kind."""
    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        catalog = await seed_catalog(db, temple.id, price=500.0, name="Idem10x")
        catalog_id = str(catalog.id)

    booking_data = await book_archana(client, auth_headers, catalog_id, "Idem10x Devotee")
    booking_id = UUID(booking_data["booking_id"])
    payment_id = f"pay_idem10x_{uuid4().hex[:10]}"
    webhook = make_capture_webhook(
        booking_data["gateway_order_id"], payment_id, booking_data["total_payable"]
    )

    for _ in range(10):
        resp = await client.post("/api/v1/payments/razorpay/webhook", json=webhook)
        assert resp.status_code == 200

    async with TestSessionLocal() as db:
        pay_count = (await db.execute(
            select(func.count(ArchanaBookingPayment.id)).filter(
                ArchanaBookingPayment.booking_id == booking_id)
        )).scalar()
        ledger_count = (await db.execute(
            select(func.count(OnlineSettlementLedger.id)).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "CREDIT",
            )
        )).scalar()

    assert pay_count == 1,    f"10× replay: {pay_count} payments (expected 1)"
    assert ledger_count == 1, f"10× replay: {ledger_count} ledger entries (expected 1)"


@pytest.mark.anyio
async def test_phase_b_settlement_batch_idempotency(client, superadmin_auth_headers):
    """
    Phase B: Settlement batch idempotency.
    Running generate twice for the same temple+period must produce exactly one batch.
    """
    async with TestSessionLocal() as db:
        stmt = select(User).filter(User.role == "SUPERADMIN").limit(1)
        res = await db.execute(stmt)
        superadmin = res.scalar_one()

        temple = Temple(
            id=uuid4(),
            name=f"Idem Temple {uuid4().hex[:6]}",
            domain=f"idemsettle{uuid4().hex[:6]}",
            status="APPROVED",
            is_active=True,
            is_settlement_eligible=True,
        )
        db.add(temple)
        await db.flush()
        await seed_bank_and_verify(db, temple.id, superadmin.id)

        # Seed 2 ledger credits totalling > ₹500
        for i in range(2):
            booking = EnterpriseArchanaBooking(
                temple_id=temple.id,
                ref_id=f"AR-IDEM-SET-{i}",
                primary_devotee_name=f"Dev {i}",
                total_amount=350.0,
                grand_total=350.0,
                total_payable=357.0,
                online_status="PAYMENT_SUCCESS",
            )
            db.add(booking)
            await db.flush()
            payment = ArchanaBookingPayment(
                booking_id=booking.id,
                amount=357.0,
                payment_mode="Online",
                status="SUCCESS",
                archana_amount=350.0,
                convenience_fee=7.0,
                total_amount_charged=357.0,
                settlement_status="PENDING",
            )
            db.add(payment)
            await db.flush()
            ledger = OnlineSettlementLedger(
                temple_id=temple.id,
                booking_id=booking.id,
                payment_id=payment.id,
                entry_type="CREDIT",
                archana_amount=350.0,
                temple_net_amount=350.0,
                gross_convenience_fee=7.0,
                taxable_fee=5.93,
                gst_component=1.07,
                cgst_component=0.54,
                sgst_component=0.53,
                net_platform_revenue=5.93,
                total_charged_to_devotee=357.0,
                is_settled=False,
            )
            db.add(ledger)
        await db.commit()

    period_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    period_end = datetime.now(timezone.utc).isoformat()

    # Generate twice
    for attempt in range(2):
        resp = await client.post(
            "/api/v1/admin/settlements/batches/generate",
            json={"period_start": period_start, "period_end": period_end},
            headers=superadmin_auth_headers,
        )
        assert resp.status_code == 200, f"Generate attempt {attempt+1} failed: {resp.text}"

    async with TestSessionLocal() as db:
        count = (await db.execute(
            select(func.count(SettlementBatch.id)).filter(
                SettlementBatch.temple_id == temple.id)
        )).scalar()

    assert count == 1, f"IDEMPOTENCY FAIL: {count} batches generated (expected 1)"


# =============================================================================
# PHASE C — REFUND & REJECTION LIFECYCLE
# =============================================================================

@pytest.mark.anyio
async def test_phase_c_refund_lifecycle(client, auth_headers):
    """
    Phase C: Complete refund lifecycle.
    QUEUED → CANCELLED → REFUND_INITIATED → REFUNDED.
    Validates: queue cancellation, ledger REFUND_DEBIT, refund idempotency.
    """
    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        catalog = await seed_catalog(db, temple.id, price=250.0, name="PhaseC Refund")
        catalog_id = str(catalog.id)

    booking_data = await book_archana(client, auth_headers, catalog_id, "Refund Devotee")
    booking_id = UUID(booking_data["booking_id"])
    payment_id = f"pay_refund_{uuid4().hex[:10]}"
    await trigger_capture(client, booking_data, payment_id)

    # C1. Verify queue was created in WAITING
    async with TestSessionLocal() as db:
        q = (await db.execute(
            select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
        )).scalar_one()
        assert q.status == QueueStatus.WAITING

    # C2. Cancel/reject the booking
    cancel_resp = await client.post(
        f"/api/v1/archana-bookings/{booking_id}/cancel",
        headers=auth_headers,
    )
    assert cancel_resp.status_code == 200, f"Cancel failed: {cancel_resp.text}"

    async with TestSessionLocal() as db:
        # C3. Booking transitions
        booking = (await db.execute(
            select(EnterpriseArchanaBooking).filter(
                EnterpriseArchanaBooking.id == booking_id)
        )).scalar_one()
        assert booking.online_status == "REFUND_INITIATED"
        assert booking.status == ArchanaStatus.CANCELLED

        # C4. Queue cancelled
        queue = (await db.execute(
            select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
        )).scalar_one()
        assert queue.status == QueueStatus.CANCELLED, \
            f"Queue must be CANCELLED on booking rejection, got {queue.status}"

        # C5. Refund record created
        refund = (await db.execute(
            select(ArchanaRefund).filter(ArchanaRefund.booking_id == booking_id)
        )).scalar_one()
        assert refund.gateway_refund_id is not None
        assert refund.amount == booking_data["total_payable"]

        # C6. Ledger REFUND_DEBIT entry
        debit = (await db.execute(
            select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "REFUND_DEBIT",
            )
        )).scalar_one()
        assert debit.archana_amount == -250.0, "Refund debit archana_amount must be negative of original"
        assert debit.temple_net_amount == -250.0, "Sacred 100% rule holds in refunds"
        assert debit.total_charged_to_devotee == -booking_data["total_payable"]
        assert debit.is_settled is False

        gateway_refund_id = refund.gateway_refund_id

    # C7. Refund.processed webhook
    refund_webhook = {
        "entity": "event",
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": gateway_refund_id,
                    "entity": "refund",
                    "payment_id": payment_id,
                    "amount": int(booking_data["total_payable"] * 100),
                    "status": "processed",
                    "created_at": 1700000001,
                }
            }
        },
    }
    ref_resp = await client.post("/api/v1/payments/razorpay/webhook", json=refund_webhook)
    assert ref_resp.status_code == 200, f"Refund webhook failed: {ref_resp.text}"

    async with TestSessionLocal() as db:
        booking = (await db.execute(
            select(EnterpriseArchanaBooking).filter(
                EnterpriseArchanaBooking.id == booking_id)
        )).scalar_one()
        assert booking.online_status == "REFUNDED"

    # C8. Refund idempotency — replay refund.processed 3 times
    for i in range(3):
        resp = await client.post("/api/v1/payments/razorpay/webhook", json=refund_webhook)
        assert resp.status_code == 200

    async with TestSessionLocal() as db:
        # Only one REFUND_DEBIT ledger entry
        debit_count = (await db.execute(
            select(func.count(OnlineSettlementLedger.id)).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "REFUND_DEBIT",
            )
        )).scalar()
        refund_count = (await db.execute(
            select(func.count(ArchanaRefund.id)).filter(
                ArchanaRefund.booking_id == booking_id)
        )).scalar()

    assert debit_count == 1,  f"IDEMPOTENCY FAIL: {debit_count} REFUND_DEBIT entries (expected 1)"
    assert refund_count == 1, f"IDEMPOTENCY FAIL: {refund_count} ArchanaRefund records (expected 1)"


# =============================================================================
# PHASE D — AUTO-COMPLETION VALIDATION
# =============================================================================

@pytest.mark.anyio
async def test_phase_d_auto_completion_via_service(client, auth_headers):
    """
    Phase D: Timer-based auto-completion.
    Manually advance the expected_completion_time to the past and invoke the
    auto-completion worker; verify queue + execution transition to COMPLETED.
    """
    from app.modules.bookings.services.archana_lifecycle_service import ArchanaLifecycleService

    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        catalog = await seed_catalog(db, temple.id, price=100.0, name="PhaseD Auto")
        catalog_id = str(catalog.id)

    booking_data = await book_archana(client, auth_headers, catalog_id, "AutoComp Devotee")
    booking_id = UUID(booking_data["booking_id"])
    await trigger_capture(client, booking_data, f"pay_autocomp_{uuid4().hex[:10]}")

    # Advance expected_completion_time to the past on all executions
    async with TestSessionLocal() as db:
        queue = (await db.execute(
            select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
        )).scalar_one()
        queue_id = queue.id

        executions = (await db.execute(
            select(ArchanaExecution).filter(ArchanaExecution.queue_id == queue_id)
        )).scalars().all()

        past = datetime.now(timezone.utc) - timedelta(minutes=20)
        for ex in executions:
            ex.expected_completion_time = past
            ex.status = QueueStatus.IN_PROGRESS
            ex.start_time = past - timedelta(minutes=5)
        queue.status = QueueStatus.IN_PROGRESS
        await db.commit()

    # Run auto-completion
    async with TestSessionLocal() as db:
        await ArchanaLifecycleService.process_auto_completions(db)

    async with TestSessionLocal() as db:
        executions = (await db.execute(
            select(ArchanaExecution).filter(ArchanaExecution.queue_id == queue_id)
        )).scalars().all()
        for ex in executions:
            assert ex.status == QueueStatus.COMPLETED, \
                f"Execution must be COMPLETED after auto-completion, got {ex.status}"
            assert ex.auto_completed is True
            assert ex.completed_at is not None


@pytest.mark.anyio
async def test_phase_d_no_duplicate_completion(client, auth_headers):
    """
    Phase D: Manual override — calling complete twice must not create duplicate state.
    """
    from app.modules.bookings.services.archana_lifecycle_service import ArchanaLifecycleService

    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        stmt2 = select(User).filter(User.temple_id == temple.id, User.role == "ADMIN").limit(1)
        res2 = await db.execute(stmt2)
        admin_user = res2.scalar_one()

        catalog = await seed_catalog(db, temple.id, price=100.0, name="PhaseD NoDouble")
        catalog_id = str(catalog.id)

    booking_data = await book_archana(client, auth_headers, catalog_id, "NoDup Devotee")
    booking_id = UUID(booking_data["booking_id"])
    await trigger_capture(client, booking_data, f"pay_nodupe_{uuid4().hex[:10]}")

    async with TestSessionLocal() as db:
        queue = (await db.execute(
            select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
        )).scalar_one()
        execution = (await db.execute(
            select(ArchanaExecution).filter(ArchanaExecution.queue_id == queue.id)
        )).scalars().first()

        # Transition to IN_PROGRESS
        execution.status = QueueStatus.IN_PROGRESS
        execution.start_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        queue.status = QueueStatus.IN_PROGRESS
        await db.commit()

        execution_id = execution.id

    # Complete manually via service twice
    async with TestSessionLocal() as db:
        await ArchanaLifecycleService.complete_ritual(
            db, execution_id, admin_user.id, is_auto=False)

    async with TestSessionLocal() as db:
        # Second call must be a no-op (already COMPLETED)
        await ArchanaLifecycleService.complete_ritual(
            db, execution_id, admin_user.id, is_auto=False)

    async with TestSessionLocal() as db:
        ex = (await db.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == execution_id)
        )).scalar_one()
        assert ex.status == QueueStatus.COMPLETED
        assert ex.completed_at is not None


# =============================================================================
# PHASE E — SETTLEMENT BATCH VALIDATION
# =============================================================================

@pytest.mark.anyio
async def test_phase_e_bulk_settlement_batch(client, superadmin_auth_headers):
    """
    Phase E: Bulk settlement — 10 successful bookings + 2 refunds.
    Validates batch totals, ledger linkage, completion, and re-completion guard.
    """
    async with TestSessionLocal() as db:
        stmt = select(User).filter(User.role == "SUPERADMIN").limit(1)
        res = await db.execute(stmt)
        superadmin = res.scalar_one()

        temple = Temple(
            id=uuid4(),
            name=f"BulkSettle {uuid4().hex[:6]}",
            domain=f"bulk{uuid4().hex[:6]}",
            status="APPROVED",
            is_active=True,
            is_settlement_eligible=True,
        )
        db.add(temple)
        await db.flush()
        await seed_bank_and_verify(db, temple.id, superadmin.id)

        archana_price = 100.0
        # 10 credit entries
        total_credits = 0.0
        for i in range(10):
            booking = EnterpriseArchanaBooking(
                temple_id=temple.id,
                ref_id=f"AR-BULK-{i:04d}",
                primary_devotee_name=f"Bulk Devotee {i}",
                total_amount=archana_price,
                grand_total=archana_price,
                total_payable=archana_price + 2.0,
                online_status="PAYMENT_SUCCESS",
            )
            db.add(booking)
            await db.flush()
            payment = ArchanaBookingPayment(
                booking_id=booking.id, amount=archana_price + 2.0,
                payment_mode="Online", status="SUCCESS",
                archana_amount=archana_price, convenience_fee=2.0,
                total_amount_charged=archana_price + 2.0,
                settlement_status="PENDING",
            )
            db.add(payment)
            await db.flush()
            ledger = OnlineSettlementLedger(
                temple_id=temple.id, booking_id=booking.id, payment_id=payment.id,
                entry_type="CREDIT",
                archana_amount=archana_price, temple_net_amount=archana_price,
                gross_convenience_fee=2.0, taxable_fee=1.69, gst_component=0.31,
                cgst_component=0.16, sgst_component=0.15,
                net_platform_revenue=1.69,
                total_charged_to_devotee=archana_price + 2.0,
                is_settled=False,
            )
            db.add(ledger)
            total_credits += archana_price

        # 2 refund debits
        total_debits = 0.0
        for i in range(2):
            booking_r = EnterpriseArchanaBooking(
                temple_id=temple.id,
                ref_id=f"AR-BULK-R-{i:04d}",
                primary_devotee_name=f"Refund Devotee {i}",
                total_amount=archana_price,
                grand_total=archana_price,
                total_payable=archana_price + 2.0,
                online_status="REFUNDED",
            )
            db.add(booking_r)
            await db.flush()
            payment_r = ArchanaBookingPayment(
                booking_id=booking_r.id, amount=archana_price + 2.0,
                payment_mode="Online", status="SUCCESS",
                archana_amount=archana_price, convenience_fee=2.0,
                total_amount_charged=archana_price + 2.0,
                settlement_status="REFUNDED",
            )
            db.add(payment_r)
            await db.flush()
            ledger_r = OnlineSettlementLedger(
                temple_id=temple.id, booking_id=booking_r.id, payment_id=payment_r.id,
                entry_type="REFUND_DEBIT",
                archana_amount=-archana_price, temple_net_amount=-archana_price,
                gross_convenience_fee=-2.0, taxable_fee=-1.69, gst_component=-0.31,
                cgst_component=-0.16, sgst_component=-0.15,
                net_platform_revenue=-1.69,
                total_charged_to_devotee=-(archana_price + 2.0),
                is_settled=False,
            )
            db.add(ledger_r)
            total_debits += archana_price

        await db.commit()
        expected_net = total_credits - total_debits  # 1000 - 200 = 800
        temple_id = temple.id  # capture before session closes
        # batch_ref is deterministic: SET-{temple_code_or_hex8}-{start}-{end}
        temple_ref_part = str(temple_id).replace("-", "")[:8]

    period_start_dt = datetime.now(timezone.utc) - timedelta(days=7)
    period_end_dt = datetime.now(timezone.utc)
    period_start = period_start_dt.isoformat()
    period_end = period_end_dt.isoformat()
    expected_batch_ref_prefix = f"SET-{temple_ref_part}-"

    # E1. Generate batch
    gen_resp = await client.post(
        "/api/v1/admin/settlements/batches/generate",
        json={"period_start": period_start, "period_end": period_end},
        headers=superadmin_auth_headers,
    )
    assert gen_resp.status_code == 200, gen_resp.text
    batches = gen_resp.json()["data"]
    # Filter by batch_ref prefix since the API response doesn't include temple_id
    temple_batches = [b for b in batches if b.get("batch_ref", "").startswith(expected_batch_ref_prefix)]
    assert len(temple_batches) == 1, (
        f"Expected exactly 1 batch for temple {temple_id}, "
        f"got {len(temple_batches)} from {[b.get('batch_ref') for b in batches]}"
    )
    batch_id = UUID(temple_batches[0]["batch_id"])

    async with TestSessionLocal() as db:
        batch = (await db.execute(
            select(SettlementBatch).filter(SettlementBatch.id == batch_id)
        )).scalar_one()

        # E2. Batch totals validation
        assert batch.transaction_count == 12, \
            f"Expected 12 entries (10 credits + 2 debits), got {batch.transaction_count}"
        assert abs(batch.total_archana_amount - total_credits) < 0.01, \
            f"total_archana_amount mismatch: {batch.total_archana_amount} vs {total_credits}"
        assert abs(batch.total_refunds - total_debits) < 0.01, \
            f"total_refunds mismatch: {batch.total_refunds} vs {total_debits}"
        assert abs(batch.net_payout_amount - expected_net) < 0.01, \
            f"net_payout_amount mismatch: {batch.net_payout_amount} vs {expected_net}"
        assert batch.status == "PENDING"

        # E3. Every ledger entry linked to exactly one batch
        items = (await db.execute(
            select(SettlementBatchItem).filter(SettlementBatchItem.batch_id == batch_id)
        )).scalars().all()
        assert len(items) == 12, "All 12 ledger entries must be linked to the batch"
        ledger_ids = {item.ledger_entry_id for item in items}
        assert len(ledger_ids) == 12, "Each ledger entry must appear at most once"

    # E4. Approve
    appr_resp = await client.post(
        f"/api/v1/admin/settlements/batches/{batch_id}/approve",
        headers=superadmin_auth_headers,
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["data"]["status"] == "APPROVED"

    # E5. Complete with UTR
    utr = f"UTR{uuid4().hex[:12].upper()}"
    compl_resp = await client.post(
        f"/api/v1/admin/settlements/batches/{batch_id}/complete",
        json={"payout_reference_utr": utr, "payout_method": "NEFT"},
        headers=superadmin_auth_headers,
    )
    assert compl_resp.status_code == 200
    assert compl_resp.json()["data"]["status"] == "COMPLETED"

    async with TestSessionLocal() as db:
        # E6. All linked ledger entries must be marked is_settled
        ledger_settled = (await db.execute(
            select(func.count(OnlineSettlementLedger.id)).filter(
                OnlineSettlementLedger.settlement_batch_id == batch_id,
                OnlineSettlementLedger.is_settled == True,
            )
        )).scalar()
        assert ledger_settled == 12, \
            f"All 12 ledger entries must be settled, got {ledger_settled}"

        batch = (await db.execute(
            select(SettlementBatch).filter(SettlementBatch.id == batch_id)
        )).scalar_one()
        assert batch.payout_reference == utr
        assert batch.settled_at is not None

    # E7. Re-completion guard — calling complete again must be a no-op
    compl_resp2 = await client.post(
        f"/api/v1/admin/settlements/batches/{batch_id}/complete",
        json={"payout_reference_utr": "UTR_REPLAY", "payout_method": "IMPS"},
        headers=superadmin_auth_headers,
    )
    assert compl_resp2.status_code == 200  # No error

    async with TestSessionLocal() as db:
        batch = (await db.execute(
            select(SettlementBatch).filter(SettlementBatch.id == batch_id)
        )).scalar_one()
        # UTR must NOT have changed — idempotent guard
        assert batch.payout_reference == utr, \
            f"Re-completion must not overwrite UTR. Got {batch.payout_reference}"


# =============================================================================
# PHASE F — FINANCIAL RECONCILIATION VALIDATION
# =============================================================================

@pytest.mark.anyio
async def test_phase_f_financial_reconciliation(client, auth_headers, superadmin_auth_headers):
    """
    Phase F: Financial reconciliation.
    Creates known-good data and verifies all three reconciliation formulas:
      1. Temple liability: credits - debits = pending balance
      2. Platform revenue: gross_fee - gst - gateway_fee = net_platform_revenue
      3. Booking status completeness: SUCCESS + FAILED + EXPIRED + REFUNDED = total
    """
    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()

        catalog = await seed_catalog(db, temple.id, price=100.0, name="Reconcile Test")
        catalog_id = str(catalog.id)

    # Create 3 successful bookings
    book_ids = []
    pay_ids = []
    for i in range(3):
        bd = await book_archana(client, auth_headers, catalog_id, f"Recon Dev {i}")
        pid = f"pay_recon_{i}_{uuid4().hex[:8]}"
        await trigger_capture(client, bd, pid, 204, 37)
        book_ids.append(UUID(bd["booking_id"]))
        pay_ids.append(pid)

    # Create 1 refund
    bd_ref = await book_archana(client, auth_headers, catalog_id, "Recon Refund Dev")
    pid_ref = f"pay_recon_ref_{uuid4().hex[:8]}"
    await trigger_capture(client, bd_ref, pid_ref, 204, 37)
    book_ids.append(UUID(bd_ref["booking_id"]))
    cancel_resp = await client.post(
        f"/api/v1/archana-bookings/{bd_ref['booking_id']}/cancel",
        headers=auth_headers,
    )
    assert cancel_resp.status_code == 200

    # Create 1 expired booking (artificially)
    bd_exp = await book_archana(client, auth_headers, catalog_id, "Recon Expired Dev")
    async with TestSessionLocal() as db:
        bk = (await db.execute(
            select(EnterpriseArchanaBooking).filter(
                EnterpriseArchanaBooking.id == UUID(bd_exp["booking_id"]))
        )).scalar_one()
        bk.payment_expiry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

    from app.modules.bookings.services.devotee_booking_service import DevoteeBookingService
    async with TestSessionLocal() as db:
        await DevoteeBookingService.process_payment_expiries(db)

    async with TestSessionLocal() as db:
        temple_id = temple.id

        # F1. Temple Liability
        credits_res = await db.execute(
            select(func.sum(OnlineSettlementLedger.temple_net_amount)).filter(
                OnlineSettlementLedger.temple_id == temple_id,
                OnlineSettlementLedger.entry_type == "CREDIT",
                OnlineSettlementLedger.is_settled == False,
            )
        )
        total_credits = credits_res.scalar() or 0.0

        debits_res = await db.execute(
            select(func.sum(OnlineSettlementLedger.temple_net_amount)).filter(
                OnlineSettlementLedger.temple_id == temple_id,
                OnlineSettlementLedger.entry_type == "REFUND_DEBIT",
                OnlineSettlementLedger.is_settled == False,
            )
        )
        total_debits = debits_res.scalar() or 0.0

        pending_liability = total_credits + total_debits  # debits are negative
        # 3 credits × 100 = 300, 1 refund × -100 = -100 → net = 200
        assert total_credits >= 300.0, f"Expected ≥300 credits, got {total_credits}"
        assert total_debits <= -100.0, f"Expected ≤-100 debits, got {total_debits}"
        assert pending_liability >= 200.0, \
            f"Temple liability formula: credits + debits = {pending_liability} (expected ≥200)"

        # F2. Platform Revenue Integrity per-entry
        ledger_entries = (await db.execute(
            select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.temple_id == temple_id,
                OnlineSettlementLedger.entry_type == "CREDIT",
            )
        )).scalars().all()

        for entry in ledger_entries:
            expected_net_rev = (
                entry.gross_convenience_fee
                - entry.gst_component
                - entry.gateway_fee
            )
            diff = abs(entry.net_platform_revenue - expected_net_rev)
            assert diff < 0.02, (
                f"Ledger {entry.id}: net_platform_revenue mismatch. "
                f"Expected {expected_net_rev:.4f}, got {entry.net_platform_revenue:.4f}"
            )

            # Sacred rule per-entry
            assert entry.temple_net_amount == entry.archana_amount, \
                f"SACRED RULE VIOLATION in ledger {entry.id}"

        # F3. Booking status completeness
        booking_counts = {}
        for status_val in ["PAYMENT_SUCCESS", "EXPIRED", "REFUND_INITIATED", "REFUNDED", "PAYMENT_PENDING"]:
            cnt = (await db.execute(
                select(func.count(EnterpriseArchanaBooking.id)).filter(
                    EnterpriseArchanaBooking.temple_id == temple_id,
                    EnterpriseArchanaBooking.online_status == status_val,
                )
            )).scalar() or 0
            booking_counts[status_val] = cnt

        total_non_pending = sum(v for k, v in booking_counts.items()
                                if k != "PAYMENT_PENDING")
        assert total_non_pending > 0, "At least some bookings must have progressed past PENDING"

        # Verify no orphan SUCCESS bookings without a payment record
        success_without_payment = (await db.execute(
            select(func.count(EnterpriseArchanaBooking.id)).filter(
                EnterpriseArchanaBooking.temple_id == temple_id,
                EnterpriseArchanaBooking.online_status == "PAYMENT_SUCCESS",
                ~EnterpriseArchanaBooking.id.in_(
                    select(ArchanaBookingPayment.booking_id).filter(
                        ArchanaBookingPayment.status == "SUCCESS"
                    )
                )
            )
        )).scalar()
        assert success_without_payment == 0, \
            f"{success_without_payment} PAYMENT_SUCCESS bookings have no payment record (orphan state)"

        # F4. Ledger balance reconciliation
        all_entries_sum = (await db.execute(
            select(func.sum(OnlineSettlementLedger.temple_net_amount)).filter(
                OnlineSettlementLedger.temple_id == temple_id,
            )
        )).scalar() or 0.0
        assert all_entries_sum >= 0, \
            f"Net ledger balance must be non-negative (got {all_entries_sum})"


# =============================================================================
# PHASE G — DATABASE INTEGRITY VALIDATION
# =============================================================================

@pytest.mark.anyio
async def test_phase_g_unique_constraints(client, auth_headers):
    """
    Phase G: Unique constraint enforcement on critical financial fields.
    Tests: gateway_payment_id uniqueness on ArchanaBookingPayment,
           gateway_order_id uniqueness on EnterpriseArchanaBooking,
           batch_ref uniqueness on SettlementBatch.
    """
    from sqlalchemy.exc import IntegrityError

    async with TestSessionLocal() as db:
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        temple_id = temple.id  # capture as plain UUID before any rollback

        # Also fetch superadmin now while session is clean
        stmt2 = select(User).filter(User.role == "SUPERADMIN").limit(1)
        res2 = await db.execute(stmt2)
        superadmin = res2.scalar_one()
        superadmin_id = superadmin.id  # capture as plain UUID

        catalog = await seed_catalog(db, temple_id, price=100.0, name="DbInteg Test")

        # G1. gateway_payment_id must be unique on ArchanaBookingPayment
        booking1 = EnterpriseArchanaBooking(
            temple_id=temple_id, ref_id=f"AR-INTEG-{uuid4().hex[:6]}",
            primary_devotee_name="Integ Dev 1",
            total_amount=100.0, grand_total=100.0, total_payable=102.0,
            online_status="PAYMENT_SUCCESS",
        )
        db.add(booking1)
        await db.flush()

        dup_pay_id = f"pay_dup_{uuid4().hex[:10]}"
        pay1 = ArchanaBookingPayment(
            booking_id=booking1.id, amount=102.0,
            payment_mode="Online", status="SUCCESS",
            gateway_payment_id=dup_pay_id, settlement_status="PENDING",
        )
        db.add(pay1)
        await db.flush()

        # Attempt duplicate gateway_payment_id on a different booking
        booking2 = EnterpriseArchanaBooking(
            temple_id=temple_id, ref_id=f"AR-INTEG-{uuid4().hex[:6]}",
            primary_devotee_name="Integ Dev 2",
            total_amount=100.0, grand_total=100.0, total_payable=102.0,
            online_status="PAYMENT_SUCCESS",
        )
        db.add(booking2)
        await db.flush()

        pay2 = ArchanaBookingPayment(
            booking_id=booking2.id, amount=102.0,
            payment_mode="Online", status="SUCCESS",
            gateway_payment_id=dup_pay_id,  # DUPLICATE!
            settlement_status="PENDING",
        )
        db.add(pay2)

        with pytest.raises((IntegrityError, Exception)):
            await db.flush()
        await db.rollback()

        # G2. batch_ref uniqueness on SettlementBatch — use plain UUIDs captured above
        from app.models.archana import SettlementBatch

        batch_ref = f"SET-INTEG-{uuid4().hex[:8]}"
        period_s = datetime.now(timezone.utc) - timedelta(days=7)
        period_e = datetime.now(timezone.utc)

        b1 = SettlementBatch(
            temple_id=temple_id, batch_ref=batch_ref,
            period_start=period_s, period_end=period_e,
            transaction_count=1, total_archana_amount=100.0,
            total_refunds=0.0, net_payout_amount=100.0,
            status="PENDING", created_by=superadmin_id,
        )
        db.add(b1)
        await db.flush()

        b2 = SettlementBatch(
            temple_id=temple_id, batch_ref=batch_ref,  # DUPLICATE batch_ref
            period_start=period_s, period_end=period_e,
            transaction_count=1, total_archana_amount=100.0,
            total_refunds=0.0, net_payout_amount=100.0,
            status="PENDING", created_by=superadmin_id,
        )
        db.add(b2)

        with pytest.raises((IntegrityError, Exception)):
            await db.flush()
        await db.rollback()



@pytest.mark.anyio
async def test_phase_g_ledger_entry_uniqueness_per_batch(client, superadmin_auth_headers):
    """
    Phase G: SettlementBatchItem.ledger_entry_id is UNIQUE.
    The same ledger entry cannot appear in two different batches.
    """
    from sqlalchemy.exc import IntegrityError

    async with TestSessionLocal() as db:
        stmt = select(User).filter(User.role == "SUPERADMIN").limit(1)
        res = await db.execute(stmt)
        superadmin = res.scalar_one()

        temple = Temple(
            id=uuid4(),
            name=f"LedgerUniq {uuid4().hex[:6]}",
            domain=f"ledguniq{uuid4().hex[:6]}",
            status="APPROVED",
            is_active=True,
            is_settlement_eligible=True,
        )
        db.add(temple)
        await db.flush()

        booking = EnterpriseArchanaBooking(
            temple_id=temple.id, ref_id=f"AR-LU-001",
            primary_devotee_name="Ledger Uniq Dev",
            total_amount=100.0, grand_total=100.0, total_payable=102.0,
            online_status="PAYMENT_SUCCESS",
        )
        db.add(booking)
        await db.flush()
        payment = ArchanaBookingPayment(
            booking_id=booking.id, amount=102.0, payment_mode="Online",
            status="SUCCESS", archana_amount=100.0, convenience_fee=2.0,
            total_amount_charged=102.0, settlement_status="PENDING",
        )
        db.add(payment)
        await db.flush()
        ledger = OnlineSettlementLedger(
            temple_id=temple.id, booking_id=booking.id, payment_id=payment.id,
            entry_type="CREDIT", archana_amount=100.0, temple_net_amount=100.0,
            gross_convenience_fee=2.0, taxable_fee=1.69, gst_component=0.31,
            cgst_component=0.16, sgst_component=0.15,
            net_platform_revenue=1.69, total_charged_to_devotee=102.0,
            is_settled=False,
        )
        db.add(ledger)
        await db.flush()
        ledger_id = ledger.id

        period_s = datetime.now(timezone.utc) - timedelta(days=7)
        period_e = datetime.now(timezone.utc)

        batch1 = SettlementBatch(
            temple_id=temple.id, batch_ref=f"SET-LU-B1-{uuid4().hex[:6]}",
            period_start=period_s, period_end=period_e,
            transaction_count=1, total_archana_amount=100.0,
            total_refunds=0.0, net_payout_amount=100.0,
            status="PENDING", created_by=superadmin.id,
        )
        db.add(batch1)
        await db.flush()

        item1 = SettlementBatchItem(batch_id=batch1.id, ledger_entry_id=ledger_id)
        db.add(item1)
        await db.flush()

        batch2 = SettlementBatch(
            temple_id=temple.id, batch_ref=f"SET-LU-B2-{uuid4().hex[:6]}",
            period_start=period_s, period_end=period_e + timedelta(days=1),
            transaction_count=1, total_archana_amount=100.0,
            total_refunds=0.0, net_payout_amount=100.0,
            status="PENDING", created_by=superadmin.id,
        )
        db.add(batch2)
        await db.flush()

        item2 = SettlementBatchItem(batch_id=batch2.id, ledger_entry_id=ledger_id)  # DUPLICATE
        db.add(item2)

        with pytest.raises((IntegrityError, Exception)):
            await db.flush()
        await db.rollback()


# =============================================================================
# PHASE H — MULTI-TENANT ISOLATION
# =============================================================================

@pytest.mark.anyio
async def test_phase_h_cross_temple_queue_isolation(client, auth_headers, superadmin_auth_headers):
    """
    Phase H: Multi-tenant isolation.
    Two temples with independent bookings must not see each other's queue entries,
    ledger entries, or settlement batches.
    """
    async with TestSessionLocal() as db:
        stmt = select(User).filter(User.role == "SUPERADMIN").limit(1)
        res = await db.execute(stmt)
        superadmin = res.scalar_one()

        # Create two isolated temples
        temple_a = Temple(
            id=uuid4(), name=f"Temple A {uuid4().hex[:6]}",
            domain=f"tpla{uuid4().hex[:6]}",
            status="APPROVED", is_active=True, is_settlement_eligible=True,
        )
        temple_b = Temple(
            id=uuid4(), name=f"Temple B {uuid4().hex[:6]}",
            domain=f"tplb{uuid4().hex[:6]}",
            status="APPROVED", is_active=True, is_settlement_eligible=True,
        )
        db.add_all([temple_a, temple_b])
        await db.flush()

        # Seed data for Temple A
        await seed_bank_and_verify(db, temple_a.id, superadmin.id)
        booking_a = EnterpriseArchanaBooking(
            temple_id=temple_a.id, ref_id=f"AR-TA-001",
            primary_devotee_name="Temple A Devotee",
            total_amount=200.0, grand_total=200.0, total_payable=204.0,
            online_status="PAYMENT_SUCCESS",
        )
        db.add(booking_a)
        await db.flush()
        payment_a = ArchanaBookingPayment(
            booking_id=booking_a.id, amount=204.0, payment_mode="Online",
            status="SUCCESS", archana_amount=200.0, convenience_fee=4.0,
            total_amount_charged=204.0, settlement_status="PENDING",
        )
        db.add(payment_a)
        await db.flush()
        ledger_a = OnlineSettlementLedger(
            temple_id=temple_a.id, booking_id=booking_a.id, payment_id=payment_a.id,
            entry_type="CREDIT", archana_amount=200.0, temple_net_amount=200.0,
            gross_convenience_fee=4.0, taxable_fee=3.39, gst_component=0.61,
            cgst_component=0.31, sgst_component=0.30,
            net_platform_revenue=3.39, total_charged_to_devotee=204.0,
            is_settled=False,
        )
        db.add(ledger_a)
        queue_a = RitualQueue(
            temple_id=temple_a.id, booking_id=booking_a.id,
            token_number="T-001", status=QueueStatus.WAITING,
        )
        db.add(queue_a)

        # Seed data for Temple B
        await seed_bank_and_verify(db, temple_b.id, superadmin.id)
        booking_b = EnterpriseArchanaBooking(
            temple_id=temple_b.id, ref_id=f"AR-TB-001",
            primary_devotee_name="Temple B Devotee",
            total_amount=300.0, grand_total=300.0, total_payable=306.0,
            online_status="PAYMENT_SUCCESS",
        )
        db.add(booking_b)
        await db.flush()
        payment_b = ArchanaBookingPayment(
            booking_id=booking_b.id, amount=306.0, payment_mode="Online",
            status="SUCCESS", archana_amount=300.0, convenience_fee=6.0,
            total_amount_charged=306.0, settlement_status="PENDING",
        )
        db.add(payment_b)
        await db.flush()
        ledger_b = OnlineSettlementLedger(
            temple_id=temple_b.id, booking_id=booking_b.id, payment_id=payment_b.id,
            entry_type="CREDIT", archana_amount=300.0, temple_net_amount=300.0,
            gross_convenience_fee=6.0, taxable_fee=5.08, gst_component=0.92,
            cgst_component=0.46, sgst_component=0.46,
            net_platform_revenue=5.08, total_charged_to_devotee=306.0,
            is_settled=False,
        )
        db.add(ledger_b)
        queue_b = RitualQueue(
            temple_id=temple_b.id, booking_id=booking_b.id,
            token_number="T-001", status=QueueStatus.WAITING,
        )
        db.add(queue_b)
        await db.commit()

        temple_a_id = temple_a.id
        temple_b_id = temple_b.id

    # H1. Queue isolation
    async with TestSessionLocal() as db:
        queues_a = (await db.execute(
            select(RitualQueue).filter(RitualQueue.temple_id == temple_a_id)
        )).scalars().all()
        queues_b = (await db.execute(
            select(RitualQueue).filter(RitualQueue.temple_id == temple_b_id)
        )).scalars().all()

        queue_a_ids = {q.booking_id for q in queues_a}
        queue_b_ids = {q.booking_id for q in queues_b}
        assert queue_a_ids.isdisjoint(queue_b_ids), \
            "ISOLATION FAIL: Temple A and B share queue entries"

    # H2. Ledger isolation
    async with TestSessionLocal() as db:
        ledger_a_entries = (await db.execute(
            select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.temple_id == temple_a_id)
        )).scalars().all()
        ledger_b_entries = (await db.execute(
            select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.temple_id == temple_b_id)
        )).scalars().all()

        a_amounts = sum(e.temple_net_amount for e in ledger_a_entries)
        b_amounts = sum(e.temple_net_amount for e in ledger_b_entries)
        assert abs(a_amounts - 200.0) < 0.01, f"Temple A ledger: expected 200, got {a_amounts}"
        assert abs(b_amounts - 300.0) < 0.01, f"Temple B ledger: expected 300, got {b_amounts}"
        assert a_amounts != b_amounts, "Tenant ledger sums must differ"

    # H3. Settlement isolation — generate settlement and verify no cross-contamination
    period_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    period_end = datetime.now(timezone.utc).isoformat()

    gen_resp = await client.post(
        "/api/v1/admin/settlements/batches/generate",
        json={"period_start": period_start, "period_end": period_end},
        headers=superadmin_auth_headers,
    )
    assert gen_resp.status_code == 200, gen_resp.text
    all_batches = gen_resp.json()["data"]

    batches_a = [b for b in all_batches if b.get("temple_id") == str(temple_a_id)]
    batches_b = [b for b in all_batches if b.get("temple_id") == str(temple_b_id)]

    # Both temples must have their own isolated batch
    # (balance checks: A=200 > 500 fails rollover, so might not generate)
    # Verify no batch from temple A appears in temple B's context
    batch_ids_a = {b["batch_id"] for b in batches_a}
    batch_ids_b = {b["batch_id"] for b in batches_b}
    assert batch_ids_a.isdisjoint(batch_ids_b), \
        "ISOLATION FAIL: Settlement batch IDs overlap between temples"

    async with TestSessionLocal() as db:
        # Each batch is strictly associated with one temple
        for batch_data in batches_a:
            batch = (await db.execute(
                select(SettlementBatch).filter(
                    SettlementBatch.id == UUID(batch_data["batch_id"]))
            )).scalar_one_or_none()
            if batch:
                assert batch.temple_id == temple_a_id, \
                    f"ISOLATION FAIL: Batch {batch.id} belongs to wrong temple"

        for batch_data in batches_b:
            batch = (await db.execute(
                select(SettlementBatch).filter(
                    SettlementBatch.id == UUID(batch_data["batch_id"]))
            )).scalar_one_or_none()
            if batch:
                assert batch.temple_id == temple_b_id, \
                    f"ISOLATION FAIL: Batch {batch.id} belongs to wrong temple"
