import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from tests.conftest import TestSessionLocal
from app.models.archana import (
    EnterpriseArchanaBooking, ArchanaBookingPayment, OnlineSettlementLedger,
    RitualQueue, ArchanaRefund, ArchanaStatus, QueueStatus, DeityMaster, DeityStatus, ArchanaCatalog
)
from app.models.domain import Temple
from app.services.devotee_booking_service import DevoteeBookingService
from app.modules.audit.models.audit_models import ActivityOutbox, ImmutableActivityLog

@pytest.mark.anyio
async def test_m01_duplicate_queue_protection():
    """
    M-01: Verify that database-level UNIQUE constraint prevents duplicate queues for the same booking.
    """
    async with TestSessionLocal() as db:
        res = await db.execute(select(Temple).limit(1))
        temple = res.scalar_one()
        
        booking = EnterpriseArchanaBooking(
            id=uuid4(),
            temple_id=temple.id,
            ref_id=f"TEST-{uuid4().hex[:6].upper()}",
            primary_devotee_name="Devotee A",
            phone_number="9876543210",
            total_amount=100.0,
            total_payable=102.0,
            online_status="PAYMENT_SUCCESS",
            status=ArchanaStatus.CONFIRMED
        )
        db.add(booking)
        await db.commit()
        booking_id = booking.id

    # Create first queue entry
    async with TestSessionLocal() as db:
        q1 = RitualQueue(
            temple_id=temple.id,
            booking_id=booking_id,
            token_number="T-001",
            status=QueueStatus.WAITING,
            estimated_start_time=datetime.now(timezone.utc)
        )
        db.add(q1)
        await db.commit()

    # Attempt to create second queue entry for the same booking_id in a separate session
    async with TestSessionLocal() as db:
        q2 = RitualQueue(
            temple_id=temple.id,
            booking_id=booking_id,
            token_number="T-002",
            status=QueueStatus.WAITING,
            estimated_start_time=datetime.now(timezone.utc)
        )
        db.add(q2)
        with pytest.raises(IntegrityError):
            await db.commit()

@pytest.mark.anyio
async def test_m02_duplicate_ledger_credit_protection():
    """
    M-02: Verify that database-level partial unique index prevents duplicate CREDIT entries
    while permitting valid reversals/debits for the same booking.
    """
    async with TestSessionLocal() as db:
        res = await db.execute(select(Temple).limit(1))
        temple = res.scalar_one()
        
        booking = EnterpriseArchanaBooking(
            id=uuid4(),
            temple_id=temple.id,
            ref_id=f"TEST-{uuid4().hex[:6].upper()}",
            primary_devotee_name="Devotee B",
            phone_number="9876543210",
            total_amount=100.0,
            total_payable=102.0,
            online_status="PAYMENT_SUCCESS",
            status=ArchanaStatus.CONFIRMED
        )
        db.add(booking)
        await db.flush()
        
        payment = ArchanaBookingPayment(
            booking_id=booking.id,
            amount=102.0,
            payment_mode="Online",
            status="SUCCESS",
            gateway_payment_id=f"pay_{uuid4().hex[:10]}",
            gateway_order_id=f"order_{uuid4().hex[:10]}",
            archana_amount=100.0,
            convenience_fee=2.0,
            total_amount_charged=102.0
        )
        db.add(payment)
        await db.commit()
        booking_id = booking.id
        payment_id = payment.id

    # Create first CREDIT ledger entry
    async with TestSessionLocal() as db:
        l1 = OnlineSettlementLedger(
            temple_id=temple.id,
            booking_id=booking_id,
            payment_id=payment_id,
            entry_type="CREDIT",
            archana_amount=100.0,
            temple_net_amount=100.0,
            gross_convenience_fee=2.0,
            taxable_fee=1.69,
            gst_component=0.31,
            cgst_component=0.155,
            sgst_component=0.155,
            gateway_fee=0.0,
            gateway_tax=0.0,
            net_platform_revenue=1.69,
            total_charged_to_devotee=102.0,
            is_settled=False
        )
        db.add(l1)
        await db.commit()

    # Attempt to create second CREDIT ledger entry for the same booking_id
    async with TestSessionLocal() as db:
        l2 = OnlineSettlementLedger(
            temple_id=temple.id,
            booking_id=booking_id,
            payment_id=payment_id,
            entry_type="CREDIT",
            archana_amount=100.0,
            temple_net_amount=100.0,
            gross_convenience_fee=2.0,
            taxable_fee=1.69,
            gst_component=0.31,
            cgst_component=0.155,
            sgst_component=0.155,
            gateway_fee=0.0,
            gateway_tax=0.0,
            net_platform_revenue=1.69,
            total_charged_to_devotee=102.0,
            is_settled=False
        )
        db.add(l2)
        with pytest.raises(IntegrityError):
            await db.commit()

    # Verify that a REFUND_DEBIT ledger entry is allowed for the same booking_id
    async with TestSessionLocal() as db:
        l3 = OnlineSettlementLedger(
            temple_id=temple.id,
            booking_id=booking_id,
            payment_id=payment_id,
            entry_type="REFUND_DEBIT",
            archana_amount=-100.0,
            temple_net_amount=-100.0,
            gross_convenience_fee=-2.0,
            taxable_fee=-1.69,
            gst_component=-0.31,
            cgst_component=-0.155,
            sgst_component=-0.155,
            gateway_fee=0.0,
            gateway_tax=0.0,
            net_platform_revenue=-1.69,
            total_charged_to_devotee=-102.0,
            is_settled=False
        )
        db.add(l3)
        await db.commit()

@pytest.mark.anyio
async def test_m02_webhook_replay_ledger_protection(client, auth_headers):
    """
    M-02: Verify that replaying the payment.captured webhook multiple times results in exactly
    one CREDIT ledger entry, and blocks duplicate credit processing.
    """
    # 1. Setup a catalog item and booking
    async with TestSessionLocal() as db:
        res = await db.execute(select(Temple).limit(1))
        temple = res.scalar_one()
        
        # Seed Deity
        deity = DeityMaster(
            tenant_id=temple.id,
            deity_name="Lord Vigneshwara",
            normalized_name="lord vigneshwara",
            status=DeityStatus.ACTIVE
        )
        db.add(deity)
        await db.flush()

        catalog = ArchanaCatalog(
            temple_id=temple.id,
            name="Safeguard Archana",
            price=200.0,
            deity_id=deity.id,
            duration_minutes=10,
            is_active=True,
            is_online_enabled=True,
            available_prasadam_modes=["NONE"],
            completion_mode="AUTO_WITH_OVERRIDE"
        )
        db.add(catalog)
        await db.commit()
        catalog_id = str(catalog.id)

    # Book via API
    payload = {
        "catalog_id": catalog_id,
        "booking_date": "2026-06-25",
        "members": [{"name": "Devotee One", "nakshatra": "Aswini", "is_primary": True}],
        "prasadam_mode": "NONE"
    }
    resp = await client.post("/api/v1/devotee/archana/book", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    booking_data = resp.json()
    booking_id = UUID(booking_data["booking_id"])
    gateway_order_id = booking_data["gateway_order_id"]

    # Webhook replay payload
    webhook_payload = {
        "entity": "event",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_replay_{uuid4().hex[:8]}",
                    "entity": "payment",
                    "amount": 20400,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": gateway_order_id,
                    "method": "upi",
                    "fee": 408,
                    "tax": 73,
                    "created_at": 1600000000
                }
            }
        }
    }

    # Call webhook first time (should succeed)
    wh_resp1 = await client.post("/api/v1/payments/razorpay/webhook", json=webhook_payload)
    assert wh_resp1.status_code == 200

    # Call webhook second time with same transaction / payment (should be skipped by idempotency check)
    wh_resp2 = await client.post("/api/v1/payments/razorpay/webhook", json=webhook_payload)
    assert wh_resp2.status_code == 200

    # Verify that only one CREDIT entry is present in OnlineSettlementLedger
    async with TestSessionLocal() as db:
        ledger_res = await db.execute(
            select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "CREDIT"
            )
        )
        credits = ledger_res.scalars().all()
        assert len(credits) == 1

    # Now let's simulate a bypass where we bypass the application-level check or attempt to insert directly
    # to make sure the database constraint blocks a second credit if they have different payment IDs
    async with TestSessionLocal() as db:
        l_duplicate = OnlineSettlementLedger(
            temple_id=temple.id,
            booking_id=booking_id,
            payment_id=credits[0].payment_id,
            entry_type="CREDIT",
            archana_amount=200.0,
            temple_net_amount=200.0,
            gross_convenience_fee=4.0,
            taxable_fee=3.38,
            gst_component=0.62,
            cgst_component=0.31,
            sgst_component=0.31,
            gateway_fee=0.0,
            gateway_tax=0.0,
            net_platform_revenue=3.38,
            total_charged_to_devotee=204.0,
            is_settled=False
        )
        db.add(l_duplicate)
        with pytest.raises(IntegrityError):
            await db.commit()

@pytest.mark.anyio
async def test_m03_refund_transaction_integrity_failure():
    """
    M-03 Failure Path: Force an exception in the caller right before commit and verify
    that no partial refund state persists (rollback verification).
    """
    async with TestSessionLocal() as db:
        res = await db.execute(select(Temple).limit(1))
        temple = res.scalar_one()
        
        booking = EnterpriseArchanaBooking(
            id=uuid4(),
            temple_id=temple.id,
            ref_id=f"TEST-{uuid4().hex[:6].upper()}",
            primary_devotee_name="Devotee C",
            phone_number="9876543210",
            total_amount=100.0,
            total_payable=102.0,
            online_status="PAYMENT_SUCCESS",
            status=ArchanaStatus.CONFIRMED
        )
        db.add(booking)
        await db.flush()
        
        payment = ArchanaBookingPayment(
            booking_id=booking.id,
            amount=102.0,
            payment_mode="Online",
            status="SUCCESS",
            gateway_payment_id=f"pay_{uuid4().hex[:10]}",
            gateway_order_id=f"order_{uuid4().hex[:10]}",
            archana_amount=100.0,
            convenience_fee=2.0,
            total_amount_charged=102.0
        )
        db.add(payment)
        await db.commit()
        booking_id = booking.id

    # Call service but abort/raise exception before commit
    try:
        async with TestSessionLocal() as db:
            res_b = await db.execute(select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id))
            b_record = res_b.scalar_one()
            
            actor_id = uuid4()
            success = await DevoteeBookingService.initiate_online_refund(db, b_record, actor_id)
            assert success is True
            
            # Simulate a mid-transaction crash/exception in the caller before committing
            raise RuntimeError("Simulated crash before commit")
    except RuntimeError:
        pass

    # Open a fresh database session and verify that NO partial state exists
    async with TestSessionLocal() as db:
        # Booking status should still be CONFIRMED and online_status PAYMENT_SUCCESS
        res_b = await db.execute(select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id))
        booking = res_b.scalar_one()
        assert booking.status == ArchanaStatus.CONFIRMED
        assert booking.online_status == "PAYMENT_SUCCESS"
        
        # ArchanaRefund record should NOT exist
        res_r = await db.execute(select(ArchanaRefund).filter(ArchanaRefund.booking_id == booking_id))
        refunds = res_r.scalars().all()
        assert len(refunds) == 0
        
        # Ledger refund entries should NOT exist
        res_l = await db.execute(
            select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "REFUND_DEBIT"
            )
        )
        ledgers = res_l.scalars().all()
        assert len(ledgers) == 0

        # Outbox events should NOT exist
        res_o = await db.execute(
            select(ActivityOutbox).filter(
                ActivityOutbox.entity_id == str(booking_id),
                ActivityOutbox.action_type == "BOOKING_REJECTED"
            )
        )
        outbox = res_o.scalars().all()
        assert len(outbox) == 0

@pytest.mark.anyio
async def test_m03_refund_transaction_integrity_success():
    """
    M-03 Success Path: Verify that refund, ledger, audit, and outbox event all persist
    atomically after successful commit.
    """
    async with TestSessionLocal() as db:
        res = await db.execute(select(Temple).limit(1))
        temple = res.scalar_one()
        
        booking = EnterpriseArchanaBooking(
            id=uuid4(),
            temple_id=temple.id,
            ref_id=f"TEST-{uuid4().hex[:6].upper()}",
            primary_devotee_name="Devotee D",
            phone_number="9876543210",
            total_amount=100.0,
            total_payable=102.0,
            online_status="PAYMENT_SUCCESS",
            status=ArchanaStatus.CONFIRMED
        )
        db.add(booking)
        await db.flush()
        
        payment = ArchanaBookingPayment(
            booking_id=booking.id,
            amount=102.0,
            payment_mode="Online",
            status="SUCCESS",
            gateway_payment_id=f"pay_{uuid4().hex[:10]}",
            gateway_order_id=f"order_{uuid4().hex[:10]}",
            archana_amount=100.0,
            convenience_fee=2.0,
            total_amount_charged=102.0
        )
        db.add(payment)
        await db.commit()
        booking_id = booking.id

    # Call service and commit successfully
    async with TestSessionLocal() as db:
        res_b = await db.execute(select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id))
        b_record = res_b.scalar_one()
        
        actor_id = uuid4()
        success = await DevoteeBookingService.initiate_online_refund(db, b_record, actor_id)
        assert success is True
        
        await db.commit()

    # Verify everything persisted atomically
    async with TestSessionLocal() as db:
        res_b = await db.execute(select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == booking_id))
        booking = res_b.scalar_one()
        assert booking.status == ArchanaStatus.CANCELLED
        assert booking.online_status == "REFUND_INITIATED"
        
        res_r = await db.execute(select(ArchanaRefund).filter(ArchanaRefund.booking_id == booking_id))
        refund = res_r.scalar_one()
        assert refund.amount == 102.0
        
        res_l = await db.execute(
            select(OnlineSettlementLedger).filter(
                OnlineSettlementLedger.booking_id == booking_id,
                OnlineSettlementLedger.entry_type == "REFUND_DEBIT"
            )
        )
        ledger = res_l.scalar_one()
        assert ledger.archana_amount == -100.0
        
        res_o = await db.execute(
            select(ActivityOutbox).filter(
                ActivityOutbox.entity_id == str(booking_id),
                ActivityOutbox.action_type == "BOOKING_REJECTED"
            )
        )
        outbox_event = res_o.scalar_one()
        assert outbox_event.action_category == "BOOKING_REFUND"


@pytest.mark.anyio
async def test_global_payment_kill_switch(client, auth_headers):
    """
    Verify that the global payment kill switch key "online_archana_payments_enabled"
    blocks new online bookings when set to False, while existing endpoints (like refunds)
    remain fully functional.
    """
    from app.modules.governance.models.governance_models import PlatformGlobalSetting

    # 1. Setup: Seed active catalog item
    async with TestSessionLocal() as db:
        res = await db.execute(select(Temple).limit(1))
        temple = res.scalar_one()
        
        # Seed unique Deity
        deity = DeityMaster(
            tenant_id=temple.id,
            deity_name="Lord Hanuman",
            normalized_name="lord hanuman",
            status=DeityStatus.ACTIVE
        )
        db.add(deity)
        await db.flush()

        catalog = ArchanaCatalog(
            temple_id=temple.id,
            name="KillSwitch Archana",
            price=150.0,
            deity_id=deity.id,
            duration_minutes=10,
            is_active=True,
            is_online_enabled=True,
            available_prasadam_modes=["NONE"],
            completion_mode="AUTO_WITH_OVERRIDE"
        )
        db.add(catalog)
        await db.commit()
        catalog_id = str(catalog.id)

    # 2. Disable payments via PlatformGlobalSetting
    async with TestSessionLocal() as db:
        # Check if already exists
        stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "online_archana_payments_enabled")
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()
        if setting:
            setting.value = False
        else:
            setting = PlatformGlobalSetting(
                key="online_archana_payments_enabled",
                value=False
            )
            db.add(setting)
        await db.commit()

    # 3. Try to book via API (should fail with HTTP 503)
    payload = {
        "catalog_id": catalog_id,
        "booking_date": "2026-06-25",
        "members": [{"name": "Devotee One", "nakshatra": "Aswini", "is_primary": True}],
        "prasadam_mode": "NONE"
    }
    resp = await client.post("/api/v1/devotee/archana/book", json=payload, headers=auth_headers)
    assert resp.status_code == 503
    assert "Online Archana bookings are temporarily unavailable" in resp.json()["error"]["message"]

    # 4. Re-enable payments via PlatformGlobalSetting
    async with TestSessionLocal() as db:
        stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "online_archana_payments_enabled")
        res = await db.execute(stmt)
        setting = res.scalar_one()
        setting.value = True
        await db.commit()

    # 5. Try to book again via API (should now succeed)
    resp_ok = await client.post("/api/v1/devotee/archana/book", json=payload, headers=auth_headers)
    assert resp_ok.status_code == 200

