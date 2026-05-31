import pytest
import uuid
from decimal import Decimal
from unittest.mock import patch
from httpx import AsyncClient
from sqlalchemy.future import select
from app.models.domain import HallBooking, Temple, User
from app.modules.bookings.models.booking_models import RefundHistory, Hall
from app.modules.bookings.models.hall_booking import PaymentLedger
from app.modules.governance.models.governance_models import ApprovalRequest
from app.core.database import AsyncSessionLocal
from tests.conftest import TEMPLE_ID

@pytest.mark.asyncio
async def test_hall_bookings_refund_governance_lifecycle(client: AsyncClient, auth_headers: dict):
    """Test full refund governance workflow including request, locks, approvals, and timeline tracking."""
    # 1. Create a Hall venue and booking directly in the db for the test
    async with AsyncSessionLocal() as session:
        # Create a Hall
        hall = Hall(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            name="Sanskrit Hall",
            capacity=200,
            price_per_day=5000.0,
            status="active"
        )
        session.add(hall)
        await session.flush()
        
        # Create a HallBooking
        booking = HallBooking(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            hall_id=hall.id,
            customer_name="John Doe",
            date="2026-06-10",
            end_date="2026-06-12",
            purpose="Wedding Reception",
            amount=10000.0,
            discount_amount=1000.0,
            amount_paid=9000.0,
            payment_status="SUCCESS",
            status="confirmed",
            ref_number="HB-TEST-01"
        )
        session.add(booking)
        await session.flush()
        
        # Create PaymentLedger
        ledger = PaymentLedger(
            temple_id=TEMPLE_ID,
            booking_id=booking.id,
            total_amount=9000.0,  # Net amount after discount
            paid_amount=9000.0,
            due_amount=0.0,
            refunded_amount=0.0,
            status="COMPLETED"
        )
        session.add(ledger)
        await session.commit()
        
        booking_id = str(booking.id)

    # 2. Submit a refund request (Partial refund of 3000.00)
    refund_payload = {
        "booking_id": booking_id,
        "amount": 3000.0,
        "refund_method": "UPI",
        "refund_status": "Partial",
        "reason": "Event shortened"
    }
    
    resp = await client.post("/api/v1/manager/hall-bookings/refunds", json=refund_payload, headers=auth_headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert "approval_request_id" in res_data
    approval_id = res_data["approval_request_id"]
    
    # 3. Verify locks are active on the booking
    # Try to modify the booking details via PUT (should fail)
    put_resp = await client.put(
        f"/api/v1/manager/hall-bookings/{booking_id}",
        json={"customer_name": "New Name"},
        headers=auth_headers
    )
    assert put_resp.status_code == 400
    assert "locked" in put_resp.json()["error"]["message"].lower()
    
    # Try to cancel the booking (should fail)
    cancel_resp = await client.patch(
        f"/api/v1/manager/hall-bookings/{booking_id}/cancel",
        headers=auth_headers
    )
    assert cancel_resp.status_code == 400
    assert "locked" in cancel_resp.json()["error"]["message"].lower()

    # Try to request another refund (should fail)
    dup_resp = await client.post("/api/v1/manager/hall-bookings/refunds", json=refund_payload, headers=auth_headers)
    assert dup_resp.status_code == 400
    assert "pending approval" in dup_resp.json()["error"]["message"].lower()

    # 4. View manager queue for pending requests
    pending_resp = await client.get("/api/v1/manager/hall-bookings/refund-requests", headers=auth_headers)
    assert pending_resp.status_code == 200
    pending_list = pending_resp.json()
    assert any(req["id"] == approval_id for req in pending_list)

    # 5. Process approval (Reject it first to test clean release and re-request)
    reject_resp = await client.post(
        f"/api/v1/manager/hall-bookings/refund-requests/{approval_id}/process",
        json={"status": "rejected", "remarks": "Need manager call first"},
        headers=auth_headers
    )
    assert reject_resp.status_code == 200
    
    # Verify booking locks are released and status set to REJECTED
    async with AsyncSessionLocal() as session:
        booking_stmt = select(HallBooking).filter(HallBooking.id == uuid.UUID(booking_id))
        booking_res = await session.execute(booking_stmt)
        booking_db = booking_res.scalar_one()
        assert booking_db.refund_status == "REJECTED"
        assert booking_db.has_pending_refund is False

    # 6. Re-submit the refund request (Full refund of 9000.0)
    refund_payload["amount"] = 9000.0
    refund_payload["refund_status"] = "Full"
    refund_payload["reason"] = "Event fully cancelled"
    
    resp = await client.post("/api/v1/manager/hall-bookings/refunds", json=refund_payload, headers=auth_headers)
    assert resp.status_code == 200
    new_approval_id = resp.json()["approval_request_id"]
    
    # 7. Process approval (Approve it now)
    approve_resp = await client.post(
        f"/api/v1/manager/hall-bookings/refund-requests/{new_approval_id}/process",
        json={"status": "approved", "remarks": "Approved by board"},
        headers=auth_headers
    )
    assert approve_resp.status_code == 200
    
    # 8. Verify post-execution updates on the booking, ledger, and history
    async with AsyncSessionLocal() as session:
        # Booking checks
        booking_stmt = select(HallBooking).filter(HallBooking.id == uuid.UUID(booking_id))
        booking_res = await session.execute(booking_stmt)
        booking_db = booking_res.scalar_one()
        assert booking_db.refund_status == "COMPLETED"
        assert booking_db.status == "cancelled"
        assert booking_db.payment_status == "REFUNDED"
        assert booking_db.amount_paid == 0.0
        
        # Ledger checks
        ledger_stmt = select(PaymentLedger).filter(PaymentLedger.booking_id == uuid.UUID(booking_id))
        ledger_res = await session.execute(ledger_stmt)
        ledger_db = ledger_res.scalar_one()
        assert ledger_db.refunded_amount == 9000.0
        assert ledger_db.paid_amount == 0.0
        assert ledger_db.status == "REFUNDED"
        
        # Refund history record checks
        hist_stmt = select(RefundHistory).filter(RefundHistory.approval_request_id == uuid.UUID(new_approval_id))
        hist_res = await session.execute(hist_stmt)
        hist_db = hist_res.scalar_one()
        assert hist_db.status == "COMPLETED"
        assert hist_db.refund_amount == Decimal("9000.00")
        assert hist_db.amount_paid_before == Decimal("9000.00")
        assert hist_db.amount_paid_after == Decimal("0.00")
        assert hist_db.balance_before == Decimal("0.00")  # (9000 contract - 9000 paid)
        assert hist_db.balance_after == Decimal("9000.00")  # (9000 contract - 0 paid)

@pytest.mark.asyncio
async def test_hall_bookings_refund_execution_failure_recovery(client: AsyncClient, auth_headers: dict):
    """Test that a database exception during refund execution triggers transactional rollback, resets locks, and logs execution_failed."""
    # 1. Create a Hall venue and booking directly in the db
    async with AsyncSessionLocal() as session:
        hall = Hall(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            name="Execution Failure Hall",
            capacity=100,
            price_per_day=4000.0,
            status="active"
        )
        session.add(hall)
        await session.flush()
        
        booking = HallBooking(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            hall_id=hall.id,
            customer_name="Jane Doe",
            date="2026-06-15",
            end_date="2026-06-16",
            purpose="Seminar",
            amount=4000.0,
            discount_amount=0.0,
            amount_paid=4000.0,
            payment_status="SUCCESS",
            status="confirmed",
            ref_number="HB-TEST-FAIL"
        )
        session.add(booking)
        await session.commit()
        booking_id = str(booking.id)

    # 2. Submit refund request
    refund_payload = {
        "booking_id": booking_id,
        "amount": 2000.0,
        "refund_method": "Cash",
        "refund_status": "Partial",
        "reason": "Test failure rollback"
    }
    
    resp = await client.post("/api/v1/manager/hall-bookings/refunds", json=refund_payload, headers=auth_headers)
    assert resp.status_code == 200
    approval_id = resp.json()["approval_request_id"]

    # 3. Approve it, but patch HallService.process_refund to raise a Database/Ledger write failure
    with patch("app.services.hall_service.HallService.process_refund", side_effect=Exception("Database lock error or connection timed out")):
        with pytest.raises(Exception, match="Database lock error"):
            await client.post(
                f"/api/v1/manager/hall-bookings/refund-requests/{approval_id}/process",
                json={"status": "approved", "remarks": "Approving failure case"},
                headers=auth_headers
            )

    # 4. Verify failure recovery: booking locks are reset to NONE/False, request is marked execution_failed, and RefundHistory is FAILED
    async with AsyncSessionLocal() as session:
        # Check booking is unlocked
        booking_stmt = select(HallBooking).filter(HallBooking.id == uuid.UUID(booking_id))
        booking_res = await session.execute(booking_stmt)
        booking_db = booking_res.scalar_one()
        assert booking_db.refund_status == "NONE"
        assert booking_db.has_pending_refund is False
        
        # Check ApprovalRequest is execution_failed
        req_stmt = select(ApprovalRequest).filter(ApprovalRequest.id == uuid.UUID(approval_id))
        req_res = await session.execute(req_stmt)
        req_db = req_res.scalar_one()
        assert req_db.status == "execution_failed"
        assert "Database lock error" in req_db.remarks
        
        # Check RefundHistory is FAILED
        hist_stmt = select(RefundHistory).filter(RefundHistory.approval_request_id == uuid.UUID(approval_id))
        hist_res = await session.execute(hist_stmt)
        hist_db = hist_res.scalar_one()
        assert hist_db.status == "FAILED"
        assert "Database lock error" in hist_db.failure_reason
        assert hist_db.failure_code == "EXECUTION_EXCEPTION"

@pytest.mark.asyncio
async def test_hall_bookings_refund_tenant_enforcement(client: AsyncClient, auth_headers: dict):
    """Test that requests for another temple's bookings or approvals are strictly blocked with 403 validation error."""
    # 1. Create a different temple and user/booking
    other_temple_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        other_temple = Temple(id=other_temple_id, name="Other Temple", domain="other")
        session.add(other_temple)
        
        hall = Hall(
            id=uuid.uuid4(),
            temple_id=other_temple_id,
            name="Other Temple Hall",
            capacity=150,
            price_per_day=3000.0,
            status="active"
        )
        session.add(hall)
        await session.flush()
        
        booking = HallBooking(
            id=uuid.uuid4(),
            temple_id=other_temple_id,
            hall_id=hall.id,
            customer_name="Other Cust",
            date="2026-07-01",
            end_date="2026-07-02",
            purpose="Drama",
            amount=3000.0,
            discount_amount=0.0,
            amount_paid=3000.0,
            payment_status="SUCCESS",
            status="confirmed",
            ref_number="HB-OTHER"
        )
        session.add(booking)
        await session.commit()
        booking_id = str(booking.id)

    # 2. Attempt to request a refund for other temple's booking using our current auth headers (which are for TEMPLE_ID)
    refund_payload = {
        "booking_id": booking_id,
        "amount": 1000.0,
        "refund_method": "Card",
        "refund_status": "Partial",
        "reason": "Hack attempt"
    }
    
    resp = await client.post("/api/v1/manager/hall-bookings/refunds", json=refund_payload, headers=auth_headers)
    assert resp.status_code == 404

    # 3. Attempt to fetch details of booking_id directly on direct timeline GET endpoint
    timeline_resp = await client.get(f"/api/v1/manager/hall-bookings/{booking_id}/refund-history", headers=auth_headers)
    assert timeline_resp.status_code == 403
