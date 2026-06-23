import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone
from sqlalchemy import select
from app.services.platform_fee_engine import PlatformFeeEngine
from app.models.archana import ArchanaCatalog, EnterpriseArchanaBooking, DeityMaster, DeityStatus
from app.models.domain import Temple
from app.modules.temple_management.models.temple_models import TempleApprovalStatus
from tests.conftest import TestSessionLocal

@pytest.mark.anyio
async def test_platform_fee_calculations():
    """
    Test platform fee engine calculations and GST splits.
    """
    # 2% rate, min ₹2.00, max ₹10.00
    async with TestSessionLocal() as db:
        # 1. Below min threshold (₹50 * 2% = ₹1 -> should clamp to min ₹2)
        fee50 = await PlatformFeeEngine.calculate_fee(db, 50.0)
        assert fee50["gross_convenience_fee"] == 2.0
        assert fee50["taxable_fee"] + fee50["gst_component"] == 2.0
        assert fee50["cgst_component"] + fee50["sgst_component"] == fee50["gst_component"]
        assert fee50["total_payable"] == 52.0
        
        # 2. At min threshold (₹100 * 2% = ₹2 -> should clamp to min ₹2)
        fee100 = await PlatformFeeEngine.calculate_fee(db, 100.0)
        assert fee100["gross_convenience_fee"] == 2.0
        assert fee100["total_payable"] == 102.0

        # 3. Inside range (₹200 * 2% = ₹4 -> should be ₹4)
        fee200 = await PlatformFeeEngine.calculate_fee(db, 200.0)
        assert fee200["gross_convenience_fee"] == 4.0
        assert fee200["total_payable"] == 204.0

        # 4. At max threshold (₹500 * 2% = ₹10 -> should be ₹10)
        fee500 = await PlatformFeeEngine.calculate_fee(db, 500.0)
        assert fee500["gross_convenience_fee"] == 10.0
        assert fee500["total_payable"] == 510.0

        # 5. Above max threshold (₹1000 * 2% = ₹20 -> should clamp to max ₹10)
        fee1000 = await PlatformFeeEngine.calculate_fee(db, 1000.0)
        assert fee1000["gross_convenience_fee"] == 10.0
        assert fee1000["total_payable"] == 1010.0


@pytest.mark.anyio
async def test_devotee_online_archana_booking_lifecycle(client, auth_headers):
    """
    Test end-to-end devotee online booking flow.
    """
    async with TestSessionLocal() as db:
        # 1. Fetch the default temple seeded in conftest
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        
        # 2. Seed Deity
        deity = DeityMaster(
            tenant_id=temple.id,
            deity_name="Lord Shiva",
            normalized_name="lord shiva",
            status=DeityStatus.ACTIVE
        )
        db.add(deity)
        await db.flush()

        # 3. Seed online enabled Archana catalog item
        catalog = ArchanaCatalog(
            temple_id=temple.id,
            name="Special Archana",
            price=150.0,
            deity_id=deity.id,
            duration_minutes=15,
            is_active=True,
            is_online_enabled=True,
            available_prasadam_modes=["COLLECT", "NONE"],
            completion_mode="AUTO_WITH_OVERRIDE"
        )
        db.add(catalog)
        await db.commit()

        catalog_id = str(catalog.id)

    # 4. Call devotee booking endpoint
    payload = {
        "catalog_id": catalog_id,
        "booking_date": "2026-06-25",
        "members": [
            {"name": "Devotee One", "nakshatra": "Aswini", "is_primary": True},
            {"name": "Devotee Two", "nakshatra": "Bharani", "is_primary": False}
        ],
        "prasadam_mode": "COLLECT"
    }

    resp = await client.post(
        "/api/v1/devotee/archana/book",
        json=payload,
        headers=auth_headers
    )
    
    assert resp.status_code == 200, resp.text
    data = resp.json()
    
    assert "booking_id" in data
    assert data["ref_id"].startswith("AR-")
    assert data["archana_amount"] == 300.0  # 150 * 2 members
    assert data["convenience_fee"] == 6.0    # 300 * 2% = 6.0
    assert data["total_payable"] == 306.0
    assert data["gateway_order_id"].startswith("order_mock_")
    
    # Verify DB state
    async with TestSessionLocal() as db:
        from sqlalchemy.orm import selectinload
        booking_id = UUID(data["booking_id"])
        book_stmt = select(EnterpriseArchanaBooking).filter(
            EnterpriseArchanaBooking.id == booking_id
        ).options(selectinload(EnterpriseArchanaBooking.members))
        book_res = await db.execute(book_stmt)
        booking = book_res.scalar_one()
        
        assert booking.online_status == "PAYMENT_PENDING"
        assert booking.booking_channel == "ONLINE"
        assert booking.total_payable == 306.0
        assert len(booking.members) == 2


@pytest.mark.anyio
async def test_razorpay_webhook_processing(client, auth_headers):
    """
    Test receipt of Razorpay webhook payment.captured event:
    - Verifies booking and payment state updates.
    - Verifies append of CREDIT ledger entry.
    - Verifies creation of RitualQueue and ArchanaExecution records.
    - Verifies idempotency (deduplicates duplicate event calls).
    """
    from sqlalchemy import func
    async with TestSessionLocal() as db:
        # Seed temple
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        
        # Seed Deity
        deity = DeityMaster(
            tenant_id=temple.id,
            deity_name="Lord Ganesha",
            normalized_name="lord ganesha",
            status=DeityStatus.ACTIVE
        )
        db.add(deity)
        await db.flush()

        # Seed online enabled Archana catalog item
        catalog = ArchanaCatalog(
            temple_id=temple.id,
            name="Ganesha Pooja",
            price=250.0,
            deity_id=deity.id,
            duration_minutes=20,
            is_active=True,
            is_online_enabled=True,
            available_prasadam_modes=["COLLECT", "NONE"],
            completion_mode="AUTO_WITH_OVERRIDE"
        )
        db.add(catalog)
        await db.commit()
        catalog_id = str(catalog.id)

    # 1. Create a booking
    payload = {
        "catalog_id": catalog_id,
        "booking_date": "2026-06-25",
        "members": [
            {"name": "Devotee A", "nakshatra": "Aswini", "is_primary": True}
        ],
        "prasadam_mode": "COLLECT"
    }

    resp = await client.post(
        "/api/v1/devotee/archana/book",
        json=payload,
        headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    booking_data = resp.json()
    booking_id = UUID(booking_data["booking_id"])
    gateway_order_id = booking_data["gateway_order_id"]

    # 2. Trigger webhook callback for payment.captured
    webhook_payload = {
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_capture123",
                    "entity": "payment",
                    "amount": 25500,  # 250 + 2% (₹5) platform fee = 255 INR = 25500 paise
                    "currency": "INR",
                    "status": "captured",
                    "order_id": gateway_order_id,
                    "method": "upi",
                    "fee": 510,       # 2% gateway fee = ₹5.10
                    "tax": 92,        # 18% tax on gateway fee = ₹0.92
                    "created_at": 1600000000
                }
            }
        }
    }

    webhook_resp = await client.post(
        "/api/v1/payments/razorpay/webhook",
        json=webhook_payload
    )
    assert webhook_resp.status_code == 200, webhook_resp.text
    assert webhook_resp.json() == {"status": "ok"}

    # 3. Verify DB state after payment capture
    async with TestSessionLocal() as db:
        from app.models.archana import (
            ArchanaBookingPayment, OnlineSettlementLedger, RitualQueue, ArchanaExecution
        )
        from app.models import ActivityOutbox
        
        # Verify Booking Status
        book_stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id)
        book_res = await db.execute(book_stmt)
        booking = book_res.scalar_one()
        assert booking.online_status == "PAYMENT_SUCCESS"
        assert booking.status.name == "CONFIRMED"

        # Verify Payment Record
        pay_stmt = select(ArchanaBookingPayment).filter(ArchanaBookingPayment.booking_id == booking_id)
        pay_res = await db.execute(pay_stmt)
        payment = pay_res.scalar_one()
        assert payment.gateway_payment_id == "pay_test_capture123"
        assert payment.gateway_order_id == gateway_order_id
        assert payment.total_amount_charged == 255.0
        assert payment.archana_amount == 250.0
        assert payment.convenience_fee == 5.0
        assert payment.gateway_fee == 5.10
        assert payment.gateway_tax == 0.92

        # Verify Ledger entry
        ledger_stmt = select(OnlineSettlementLedger).filter(OnlineSettlementLedger.booking_id == booking_id)
        ledger_res = await db.execute(ledger_stmt)
        ledger = ledger_res.scalar_one()
        assert ledger.entry_type == "CREDIT"
        assert ledger.archana_amount == 250.0
        assert ledger.temple_net_amount == 250.0  # Sacred 100% rule
        assert ledger.gross_convenience_fee == 5.0
        assert ledger.total_charged_to_devotee == 255.0
        assert ledger.is_settled is False

        # Verify Ritual Queue entry
        queue_stmt = select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
        queue_res = await db.execute(queue_stmt)
        queue = queue_res.scalar_one()
        assert queue.status.name == "WAITING"
        assert queue.token_number.startswith("T-")

        # Verify Archana Execution
        exec_stmt = select(ArchanaExecution).filter(ArchanaExecution.queue_id == queue.id)
        exec_res = await db.execute(exec_stmt)
        executions = exec_res.scalars().all()
        assert len(executions) == 1
        assert executions[0].status.name == "WAITING"

        # Verify ActivityOutbox event
        outbox_stmt = select(ActivityOutbox).filter(
            ActivityOutbox.entity_id == str(booking_id),
            ActivityOutbox.action_type == "PAYMENT_CAPTURED"
        )
        outbox_res = await db.execute(outbox_stmt)
        outbox_event = outbox_res.scalar_one_or_none()
        assert outbox_event is not None
        assert outbox_event.entity_name == "ArchanaBooking"

    # 4. Webhook Idempotency Check: send the same webhook event again
    webhook_resp2 = await client.post(
        "/api/v1/payments/razorpay/webhook",
        json=webhook_payload
    )
    assert webhook_resp2.status_code == 200, webhook_resp2.text
    
    # Assert no duplicate payment record, ledger entry, or queue entry was created
    async with TestSessionLocal() as db:
        from app.models.archana import (
            ArchanaBookingPayment, OnlineSettlementLedger, RitualQueue
        )
        pay_count = await db.execute(
            select(func.count(ArchanaBookingPayment.id)).filter(ArchanaBookingPayment.booking_id == booking_id)
        )
        assert pay_count.scalar() == 1
        
        ledger_count = await db.execute(
            select(func.count(OnlineSettlementLedger.id)).filter(OnlineSettlementLedger.booking_id == booking_id)
        )
        assert ledger_count.scalar() == 1

        queue_count = await db.execute(
            select(func.count(RitualQueue.id)).filter(RitualQueue.booking_id == booking_id)
        )
        assert queue_count.scalar() == 1


@pytest.mark.anyio
async def test_payment_expiry_worker(client, auth_headers):
    """
    Test that payment expiry background worker successfully scans and expires
    bookings whose payment window has elapsed.
    """
    from datetime import datetime, timezone, timedelta
    from app.services.devotee_booking_service import DevoteeBookingService
    from app.models import ActivityOutbox

    async with TestSessionLocal() as db:
        # Seed temple
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        
        # Seed Deity
        deity = DeityMaster(
            tenant_id=temple.id,
            deity_name="Lord Murugan",
            normalized_name="lord murugan",
            status=DeityStatus.ACTIVE
        )
        db.add(deity)
        await db.flush()

        # Seed online enabled Archana catalog item
        catalog = ArchanaCatalog(
            temple_id=temple.id,
            name="Murugan Pooja",
            price=120.0,
            deity_id=deity.id,
            duration_minutes=10,
            is_active=True,
            is_online_enabled=True,
            available_prasadam_modes=["COLLECT", "NONE"],
            completion_mode="AUTO_WITH_OVERRIDE"
        )
        db.add(catalog)
        await db.commit()
        catalog_id = str(catalog.id)

    # 1. Create a booking
    payload = {
        "catalog_id": catalog_id,
        "booking_date": "2026-06-25",
        "members": [
            {"name": "Devotee B", "nakshatra": "Aswini", "is_primary": True}
        ],
        "prasadam_mode": "COLLECT"
    }

    resp = await client.post(
        "/api/v1/devotee/archana/book",
        json=payload,
        headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    booking_data = resp.json()
    booking_id = UUID(booking_data["booking_id"])

    # 2. Artificially expire the booking's payment_expiry_at time
    async with TestSessionLocal() as db:
        stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id)
        res = await db.execute(stmt)
        booking = res.scalar_one()
        booking.payment_expiry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

    # 3. Call process_payment_expiries directly
    async with TestSessionLocal() as db:
        await DevoteeBookingService.process_payment_expiries(db)

    # 4. Verify booking has expired in DB and outbox event is created
    async with TestSessionLocal() as db:
        stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id)
        res = await db.execute(stmt)
        booking = res.scalar_one()
        assert booking.online_status == "EXPIRED"

        # Verify ActivityOutbox event
        outbox_stmt = select(ActivityOutbox).filter(
            ActivityOutbox.entity_id == str(booking_id),
            ActivityOutbox.action_type == "PAYMENT_EXPIRED"
        )
        outbox_res = await db.execute(outbox_stmt)
        outbox_event = outbox_res.scalar_one_or_none()
        assert outbox_event is not None
        assert outbox_event.entity_name == "ArchanaBooking"


@pytest.mark.anyio
async def test_temple_rejection_and_refund(client, auth_headers):
    """
    Test temple rejection of a booking before execution:
    - Initiates online refund.
    - Transitions booking online_status to REFUND_INITIATED.
    - Appends a REFUND_DEBIT entry to the ledger.
    - Verifies subsequent refund.processed webhook updates status to REFUNDED.
    """
    async with TestSessionLocal() as db:
        # Seed temple
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        
        # Seed Deity
        deity = DeityMaster(
            tenant_id=temple.id,
            deity_name="Lord Krishna",
            normalized_name="lord krishna",
            status=DeityStatus.ACTIVE
        )
        db.add(deity)
        await db.flush()

        # Seed online enabled Archana catalog item
        catalog = ArchanaCatalog(
            temple_id=temple.id,
            name="Krishna Pooja",
            price=200.0,
            deity_id=deity.id,
            duration_minutes=15,
            is_active=True,
            is_online_enabled=True,
            available_prasadam_modes=["COLLECT", "NONE"],
            completion_mode="AUTO_WITH_OVERRIDE"
        )
        db.add(catalog)
        await db.commit()
        catalog_id = str(catalog.id)

    # 1. Create a booking
    payload = {
        "catalog_id": catalog_id,
        "booking_date": "2026-06-25",
        "members": [
            {"name": "Devotee C", "nakshatra": "Aswini", "is_primary": True}
        ],
        "prasadam_mode": "COLLECT"
    }

    resp = await client.post(
        "/api/v1/devotee/archana/book",
        json=payload,
        headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    booking_data = resp.json()
    booking_id = UUID(booking_data["booking_id"])
    gateway_order_id = booking_data["gateway_order_id"]

    # 2. Capture the payment
    webhook_payload = {
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_refund_test_123",
                    "entity": "payment",
                    "amount": 20400,  # 200 + 2% (₹4) platform fee = 204 INR = 20400 paise
                    "currency": "INR",
                    "status": "captured",
                    "order_id": gateway_order_id,
                    "method": "upi",
                    "fee": 408,       # 2% gateway fee
                    "tax": 73,        # 18% tax on gateway fee
                    "created_at": 1600000000
                }
            }
        }
    }
    webhook_resp = await client.post(
        "/api/v1/payments/razorpay/webhook",
        json=webhook_payload
    )
    assert webhook_resp.status_code == 200, webhook_resp.text

    # 3. Reject/Cancel the booking via Manager console
    cancel_resp = await client.post(
        f"/api/v1/archana-bookings/{booking_id}/cancel",
        headers=auth_headers
    )
    assert cancel_resp.status_code == 200, cancel_resp.text

    # 4. Verify DB state after refund initiation
    async with TestSessionLocal() as db:
        from app.models.archana import (
            ArchanaRefund, OnlineSettlementLedger, ArchanaBookingPayment, RitualQueue
        )
        
        # Verify Booking Online Status is REFUND_INITIATED
        book_stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id)
        book_res = await db.execute(book_stmt)
        booking = book_res.scalar_one()
        assert booking.online_status == "REFUND_INITIATED"
        assert booking.status.name == "CANCELLED"

        # Verify Ritual Queue is CANCELLED
        queue_stmt = select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
        queue_res = await db.execute(queue_stmt)
        queue = queue_res.scalar_one()
        assert queue.status.name == "CANCELLED"

        # Verify ArchanaRefund record
        ref_stmt = select(ArchanaRefund).filter(ArchanaRefund.booking_id == booking_id)
        ref_res = await db.execute(ref_stmt)
        refund = ref_res.scalar_one()
        assert refund.gateway_refund_status in ("processed", "processed_mock") or refund.gateway_refund_id.startswith("rfnd_")
        assert refund.amount == 204.0

        # Verify OnlineSettlementLedger debit entry is created
        ledger_stmt = select(OnlineSettlementLedger).filter(
            OnlineSettlementLedger.booking_id == booking_id,
            OnlineSettlementLedger.entry_type == "REFUND_DEBIT"
        )
        ledger_res = await db.execute(ledger_stmt)
        debit_ledger = ledger_res.scalar_one()
        assert debit_ledger.archana_amount == -200.0
        assert debit_ledger.temple_net_amount == -200.0  # sacred payout reduction
        assert debit_ledger.gross_convenience_fee == -4.0
        assert debit_ledger.total_charged_to_devotee == -204.0

        gateway_refund_id = refund.gateway_refund_id

    # 5. Process refund.processed webhook to finalize state to REFUNDED
    refund_webhook_payload = {
        "entity": "event",
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": gateway_refund_id,
                    "entity": "refund",
                    "payment_id": "pay_refund_test_123",
                    "amount": 20400,
                    "status": "processed",
                    "created_at": 1600000000
                }
            }
        }
    }
    ref_webhook_resp = await client.post(
        "/api/v1/payments/razorpay/webhook",
        json=refund_webhook_payload
    )
    assert ref_webhook_resp.status_code == 200, ref_webhook_resp.text

    # Verify final status in DB
    async with TestSessionLocal() as db:
        book_stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id)
        book_res = await db.execute(book_stmt)
        booking = book_res.scalar_one()
        assert booking.online_status == "REFUNDED"


@pytest.mark.anyio
async def test_outbox_notification_delivery(client, auth_headers):
    """
    Test that when an outbox event is processed:
    - NotificationDispatcher triggers correctly.
    - Resolves templates and logs entries in notification_delivery_logs.
    """
    from app.models.archana import (
        NotificationTemplate, NotificationDeliveryLog
    )
    from app.modules.audit.services.activity_log_processor import ActivityLogProcessor
    from tests.conftest import ADMIN_USER_ID, TEMPLE_ID, ADMIN_PASSWORD
    import uuid

    try:
        async with TestSessionLocal() as db:
            # Clear any leftover outbox events from other tests to prevent database contamination
            from sqlalchemy import delete
            from app.modules.audit.models.audit_models import ActivityOutbox
            await db.execute(delete(ActivityOutbox))
            await db.commit()

            # Seed unique temple to avoid audit registry unique constraint collisions
            temple = Temple(
                id=uuid.uuid4(),
                name="Notification Test Temple",
                domain=f"notif-test-{uuid.uuid4().hex[:6]}",
                status="APPROVED",
                management_mode="SELF_MANAGED",
            )
            db.add(temple)
            from app.services.staff_service import StaffService
            await StaffService.seed_default_temple_roles(db, temple.id)

            # Seed 50 dummy bookings to shift sequential Ref ID count and avoid clash on global UNIQUE gateway_order_id
            for i in range(50):
                dummy = EnterpriseArchanaBooking(
                    id=uuid.uuid4(),
                    temple_id=temple.id,
                    ref_id=f"AR-DUMMY-{uuid.uuid4().hex[:6]}",
                    primary_devotee_name="Dummy Devotee",
                    total_amount=10.0,
                    grand_total=10.0,
                    total_payable=10.0,
                    online_status="PAYMENT_SUCCESS",
                    gateway_order_id=f"order_mock_dummy_{uuid.uuid4().hex[:8]}"
                )
                db.add(dummy)
            
            # Seed devotee user phone/email and set temple_id
            from app.models.domain import User
            user_stmt = select(User).filter(User.user_id == ADMIN_USER_ID)
            user_res = await db.execute(user_stmt)
            user = user_res.scalar_one()
            user.phone = "+919999999999"
            user.email = "devotee@example.com"
            user.temple_id = temple.id
            await db.commit()

        # Login again to get a fresh token containing the new temple_id
        login_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": ADMIN_USER_ID, "password": ADMIN_PASSWORD},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["data"]["access_token"]
        test_headers = {"Authorization": f"Bearer {token}"}

        async with TestSessionLocal() as db:
            # Seed Deity
            deity = DeityMaster(
                tenant_id=temple.id,
                deity_name="Lord Hanuman",
                normalized_name="lord hanuman",
                status=DeityStatus.ACTIVE
            )
            db.add(deity)
            await db.flush()

            # Seed online enabled Archana catalog item
            catalog = ArchanaCatalog(
                temple_id=temple.id,
                name="Hanuman Chalisa Pooja",
                price=100.0,
                deity_id=deity.id,
                duration_minutes=15,
                is_active=True,
                is_online_enabled=True,
                available_prasadam_modes=["COLLECT", "NONE"],
                completion_mode="AUTO_WITH_OVERRIDE"
            )
            db.add(catalog)

            # Seed custom NotificationTemplate for this temple
            tmpl = NotificationTemplate(
                temple_id=temple.id,
                event_code="PAYMENT_CAPTURED",
                channel="SMS",
                title_template="Pooja Confirmed",
                body_template="Dear {devotee_name}, your booking {ref_id} at {temple_name} is confirmed. Token is {token_number}.",
                is_active=True
            )
            db.add(tmpl)
            await db.commit()
            catalog_id = str(catalog.id)

        # 1. Create a booking
        payload = {
            "catalog_id": catalog_id,
            "booking_date": "2026-06-25",
            "members": [
                {"name": "Hanuman Bhakta", "nakshatra": "Aswini", "is_primary": True}
            ],
            "prasadam_mode": "COLLECT"
        }

        resp = await client.post(
            "/api/v1/devotee/archana/book",
            json=payload,
            headers=test_headers
        )
        assert resp.status_code == 200, resp.text
        booking_data = resp.json()
        booking_id = UUID(booking_data["booking_id"])
        gateway_order_id = booking_data["gateway_order_id"]

        # 2. Trigger webhook callback for payment.captured
        webhook_payload = {
            "entity": "event",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_notif_test_123",
                        "entity": "payment",
                        "amount": 10200,  # 100 + 2% platform fee = 102 INR = 10200 paise
                        "currency": "INR",
                        "status": "captured",
                        "order_id": gateway_order_id,
                        "method": "upi",
                        "fee": 204,
                        "tax": 37,
                        "created_at": 1600000000
                    }
                }
            }
        }
        webhook_resp = await client.post(
            "/api/v1/payments/razorpay/webhook",
            json=webhook_payload
        )
        assert webhook_resp.status_code == 200, webhook_resp.text

        # 3. Wait for the outbox to be processed and notification logs to be written (either by background worker or by manual fallback)
        import asyncio
        delivery_logs = []
        for _ in range(30):  # Wait up to 6 seconds
            async with TestSessionLocal() as db:
                logs_stmt = select(NotificationDeliveryLog).filter(
                    NotificationDeliveryLog.recipient_user_id != None  # filter by logged devotees
                )
                logs_res = await db.execute(logs_stmt)
                delivery_logs = logs_res.scalars().all()
                if len(delivery_logs) >= 3:
                    break
            await asyncio.sleep(0.2)

        if len(delivery_logs) < 3:
            # Fallback: manually trigger outbox processing if the background worker hasn't picked it up yet.
            # Ignore any concurrent integrity conflicts arising from double-processing races.
            try:
                async with TestSessionLocal() as db:
                    await ActivityLogProcessor.process_outbox(db)
            except Exception:
                pass

            # Final check after fallback
            async with TestSessionLocal() as db:
                logs_stmt = select(NotificationDeliveryLog).filter(
                    NotificationDeliveryLog.recipient_user_id != None
                )
                logs_res = await db.execute(logs_stmt)
                delivery_logs = logs_res.scalars().all()

        # We expect PUSH, SMS, and EMAIL delivery logs (from temple custom SMS template and global default fallbacks)
        assert len(delivery_logs) >= 3
        channels = [log.channel for log in delivery_logs]
        assert "SMS" in channels
        assert "PUSH" in channels
        assert "EMAIL" in channels
        
        for log in delivery_logs:
            assert log.status == "SENT"

    finally:
        async with TestSessionLocal() as db:
            from app.models.domain import User
            user_stmt = select(User).filter(User.user_id == ADMIN_USER_ID)
            user_res = await db.execute(user_stmt)
            user = user_res.scalar_one()
            user.temple_id = TEMPLE_ID
            await db.commit()
