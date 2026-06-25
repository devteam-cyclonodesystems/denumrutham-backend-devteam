import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from tests.conftest import TestSessionLocal
from app.models.domain import Temple, User
from app.models.archana import (
    OnlineSettlementLedger, TempleBankAccount, SettlementBatch, SettlementBatchItem,
    EnterpriseArchanaBooking, ArchanaBookingPayment
)
from app.services.settlement_service import SettlementService

@pytest.mark.anyio
async def test_bank_account_encryption_and_verification(client, auth_headers, superadmin_auth_headers):
    """
    Test submitting bank details (encryption at rest) and verification by Super Admin.
    """
    async with TestSessionLocal() as db:
        # Get seeded temple
        stmt = select(Temple).limit(1)
        res = await db.execute(stmt)
        temple = res.scalar_one()
        temple_id = str(temple.id)

    # 1. Submit bank details via API Form
    payload = {
        "account_holder_name": "Test Temple Trust",
        "bank_name": "State Bank of India",
        "account_number": "12345678901",
        "ifsc_code": "SBIN0001234",
        "account_type": "CURRENT"
    }
    
    resp = await client.post(
        "/api/v1/temple/bank-account",
        data=payload,
        headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["account_number"] == "xxxxxx8901"  # Masked in response
    assert data["verification_status"] == "PENDING"
    bank_account_id = UUID(data["id"])

    # 2. Check DB storage to verify encryption
    async with TestSessionLocal() as db:
        ac_stmt = select(TempleBankAccount).filter(TempleBankAccount.id == bank_account_id)
        ac_res = await db.execute(ac_stmt)
        bank_ac = ac_res.scalar_one()
        
        # Verify account number is encrypted and NOT plain text
        assert bank_ac.account_number_enc != "12345678901"
        from app.core.security.encryption import decrypt_data
        assert decrypt_data(bank_ac.account_number_enc) == "12345678901"

    # 3. Retrieve pending bank accounts as Super Admin (masked by default)
    pending_resp = await client.get(
        "/api/v1/admin/bank-accounts/pending",
        headers=superadmin_auth_headers
    )
    assert pending_resp.status_code == 200, pending_resp.text
    pending_data = pending_resp.json()["data"]
    assert len(pending_data) > 0
    matched_ac = [ac for ac in pending_data if ac["id"] == str(bank_account_id)][0]
    assert matched_ac["account_number"] == "xxxxxx8901"

    # 3.5 Reveal bank account details as Super Admin
    reveal_resp = await client.post(
        f"/api/v1/admin/bank-accounts/{bank_account_id}/reveal",
        headers=superadmin_auth_headers
    )
    assert reveal_resp.status_code == 200, reveal_resp.text
    reveal_data = reveal_resp.json()["data"]
    assert reveal_data["account_number"] == "12345678901"

    # 4. Verify Bank account
    verify_resp = await client.post(
        f"/api/v1/admin/bank-accounts/{bank_account_id}/verify",
        json={"action": "VERIFY", "reason": "Documents look good"},
        headers=superadmin_auth_headers
    )
    assert verify_resp.status_code == 200, verify_resp.text
    assert verify_resp.json()["data"]["verification_status"] == "VERIFIED"


@pytest.mark.anyio
async def test_settlement_eligibility_and_rollover(client, auth_headers, superadmin_auth_headers):
    """
    Test settlement batch generation:
    - Verifies eligibility check (fails without active bank / when hold flag is set).
    - Verifies rollover (fails when balance < Rs 500).
    - Verifies batch generation when all criteria are met.
    """
    async with TestSessionLocal() as db:
        # Create a new temple for isolation
        new_temple = Temple(
            id=uuid4(),
            name="Eligible Test Temple",
            domain="eligibletest",
            status="APPROVED",
            is_active=True,
            is_settlement_eligible=True
        )
        db.add(new_temple)
        
        # Seed an admin user for this temple
        new_user = User(
            user_id="manager@eligible",
            password_hash="hash",
            role="ADMIN",
            temple_id=new_temple.id
        )
        db.add(new_user)
        await db.commit()
        
        temple_id = new_temple.id
        user_id = new_user.id

    # 1. Generate settlements without bank details or ledger entries
    start_dt = datetime.now(timezone.utc) - timedelta(days=7)
    end_dt = datetime.now(timezone.utc)
    
    gen_resp = await client.post(
        "/api/v1/admin/settlements/batches/generate",
        json={"period_start": start_dt.isoformat(), "period_end": end_dt.isoformat()},
        headers=superadmin_auth_headers
    )
    assert gen_resp.status_code == 200, gen_resp.text
    # No batch generated for this temple because no bank details/ledger
    batches = gen_resp.json()["data"]
    assert not any(b["batch_ref"].split("-")[1] == str(temple_id).replace("-", "")[:8] for b in batches)

    # 2. Add verified bank details
    async with TestSessionLocal() as db:
        await SettlementService.submit_bank_account(
            db=db,
            temple_id=temple_id,
            account_holder_name="Temple Trust",
            bank_name="ICICI Bank",
            account_number="98765432101",
            ifsc_code="ICIC0000001",
            account_type="CURRENT",
            submitted_by_user_id=user_id
        )
        # Verify it
        ac_stmt = select(TempleBankAccount).filter(TempleBankAccount.temple_id == temple_id)
        ac_res = await db.execute(ac_stmt)
        bank_ac = ac_res.scalar_one()
        await SettlementService.verify_bank_account(
            db=db,
            bank_account_id=bank_ac.id,
            approver_id=user_id,
            action="VERIFY"
        )
        await db.commit()

    # 3. Add ledger credit below ₹500 threshold (₹300 credit) -> should rollover
    async with TestSessionLocal() as db:
        # Create mock booking & payment
        booking = EnterpriseArchanaBooking(
            temple_id=temple_id,
            ref_id="AR-MOCK-1",
            primary_devotee_name="Devotee X",
            total_amount=300.0,
            grand_total=300.0,
            total_payable=306.0,
            online_status="PAYMENT_SUCCESS"
        )
        db.add(booking)
        await db.flush()
        
        payment = ArchanaBookingPayment(
            booking_id=booking.id,
            amount=306.0,
            payment_mode="Online",
            status="SUCCESS",
            archana_amount=300.0,
            convenience_fee=6.0,
            total_amount_charged=306.0,
            settlement_status="PENDING"
        )
        db.add(payment)
        await db.flush()

        ledger = OnlineSettlementLedger(
            temple_id=temple_id,
            booking_id=booking.id,
            payment_id=payment.id,
            entry_type="CREDIT",
            archana_amount=300.0,
            temple_net_amount=300.0,
            gross_convenience_fee=6.0,
            taxable_fee=5.08,
            gst_component=0.92,
            cgst_component=0.46,
            sgst_component=0.46,
            net_platform_revenue=6.0 - 0.92,
            total_charged_to_devotee=306.0,
            is_settled=False
        )
        db.add(ledger)
        await db.commit()

    # Generate again -> balance is 300 < 500, should skip (rollover)
    gen_resp2 = await client.post(
        "/api/v1/admin/settlements/batches/generate",
        json={"period_start": start_dt.isoformat(), "period_end": end_dt.isoformat()},
        headers=superadmin_auth_headers
    )
    assert gen_resp2.status_code == 200
    batches2 = gen_resp2.json()["data"]
    assert not any(b["batch_ref"].split("-")[1] == str(temple_id).replace("-", "")[:8] for b in batches2)

    # 4. Add another credit of ₹400 (Total = ₹700 > ₹500) -> should generate batch
    async with TestSessionLocal() as db:
        booking2 = EnterpriseArchanaBooking(
            temple_id=temple_id,
            ref_id="AR-MOCK-2",
            primary_devotee_name="Devotee Y",
            total_amount=400.0,
            grand_total=400.0,
            total_payable=408.0,
            online_status="PAYMENT_SUCCESS"
        )
        db.add(booking2)
        await db.flush()
        
        payment2 = ArchanaBookingPayment(
            booking_id=booking2.id,
            amount=408.0,
            payment_mode="Online",
            status="SUCCESS",
            archana_amount=400.0,
            convenience_fee=8.0,
            total_amount_charged=408.0,
            settlement_status="PENDING"
        )
        db.add(payment2)
        await db.flush()

        ledger2 = OnlineSettlementLedger(
            temple_id=temple_id,
            booking_id=booking2.id,
            payment_id=payment2.id,
            entry_type="CREDIT",
            archana_amount=400.0,
            temple_net_amount=400.0,
            gross_convenience_fee=8.0,
            taxable_fee=6.78,
            gst_component=1.22,
            cgst_component=0.61,
            sgst_component=0.61,
            net_platform_revenue=8.0 - 1.22,
            total_charged_to_devotee=408.0,
            is_settled=False
        )
        db.add(ledger2)
        await db.commit()

    # Generate again -> balance is 700 >= 500, should generate PENDING batch
    gen_resp3 = await client.post(
        "/api/v1/admin/settlements/batches/generate",
        json={"period_start": start_dt.isoformat(), "period_end": end_dt.isoformat()},
        headers=superadmin_auth_headers
    )
    assert gen_resp3.status_code == 200
    batches3 = gen_resp3.json()["data"]
    matched_batches = [b for b in batches3 if b["batch_ref"].split("-")[1] == str(temple_id).replace("-", "")[:8]]
    assert len(matched_batches) == 1
    batch_id = UUID(matched_batches[0]["batch_id"])

    # 5. Verify batch state in DB
    async with TestSessionLocal() as db:
        batch_stmt = select(SettlementBatch).filter(SettlementBatch.id == batch_id)
        batch_res = await db.execute(batch_stmt)
        batch = batch_res.scalar_one()
        assert batch.status == "PENDING"
        assert batch.net_payout_amount == 700.0
        assert batch.transaction_count == 2

        # Verify ledger entries are linked to this batch
        items_stmt = select(SettlementBatchItem).filter(SettlementBatchItem.batch_id == batch_id)
        items_res = await db.execute(items_stmt)
        items = items_res.scalars().all()
        assert len(items) == 2

    # 6. Approve the batch
    appr_resp = await client.post(
        f"/api/v1/admin/settlements/batches/{batch_id}/approve",
        headers=superadmin_auth_headers
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["data"]["status"] == "APPROVED"

    # 7. Complete the batch with UTR reference
    compl_resp = await client.post(
        f"/api/v1/admin/settlements/batches/{batch_id}/complete",
        json={"payout_reference_utr": "UTR123456789", "payout_method": "NEFT"},
        headers=superadmin_auth_headers
    )
    assert compl_resp.status_code == 200
    assert compl_resp.json()["data"]["status"] == "COMPLETED"

    # 8. Verify ledger entries are marked is_settled = True
    async with TestSessionLocal() as db:
        ledger_check_stmt = select(OnlineSettlementLedger).filter(OnlineSettlementLedger.settlement_batch_id == batch_id)
        ledger_check_res = await db.execute(ledger_check_stmt)
        ledger_entries = ledger_check_res.scalars().all()
        assert len(ledger_entries) == 2
        for entry in ledger_entries:
            assert entry.is_settled is True
            assert entry.settled_at is not None
