import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from tests.conftest import TEMPLE_ID, TestSessionLocal
from app.models.domain import (
    User,
    TempleOwnershipHistory,
    Subscription,
    SubscriptionEvent,
    TempleClaimRequest,
    OperationalStateAudit,
    AuditLog
)

@pytest.mark.asyncio
async def test_governance_timeline_lifecycle(
    client: AsyncClient,
    superadmin_auth_headers: dict,
    auth_headers: dict
):
    # 1. Seed different timeline events in a clean transaction
    async with TestSessionLocal() as session:
        # Resolve the superadmin user so we can link events to them
        from sqlalchemy.future import select
        user_res = await session.execute(select(User).filter(User.user_id == "superadmin_test@temple"))
        superadmin_user = user_res.scalars().first()
        assert superadmin_user is not None
        admin_id = superadmin_user.id

        # Clear existing logs for this temple to make tests deterministic
        await session.execute(
            OperationalStateAudit.__table__.delete().where(OperationalStateAudit.temple_id == TEMPLE_ID)
        )
        await session.execute(
            TempleOwnershipHistory.__table__.delete().where(TempleOwnershipHistory.temple_id == TEMPLE_ID)
        )
        await session.execute(
            TempleClaimRequest.__table__.delete().where(TempleClaimRequest.temple_id == TEMPLE_ID)
        )
        await session.execute(
            AuditLog.__table__.delete().where(AuditLog.temple_id == TEMPLE_ID)
        )

        # A. Seed Ownership History (INFO)
        ow = TempleOwnershipHistory(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            previous_management_mode="DIRECTORY_ONLY",
            new_management_mode="GOVERNED",
            previous_subscription_plan="FREE",
            new_subscription_plan="GOVERNED_STANDARD",
            changed_by=admin_id,
            reason="Approved claim Mode change",
            changed_at=datetime.now(timezone.utc)
        )
        session.add(ow)

        # B. Seed Subscription & Event (CRITICAL & WARNING)
        sub = Subscription(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            subscription_plan="GOVERNED_STANDARD",
            status="CANCELLED",
            created_at=datetime.now(timezone.utc)
        )
        session.add(sub)
        await session.flush()

        se_critical = SubscriptionEvent(
            id=uuid.uuid4(),
            subscription_id=sub.id,
            event_name="subscription.cancelled",
            previous_status="ACTIVE",
            new_status="CANCELLED",
            payload_snapshot={},
            received_at=datetime.now(timezone.utc)
        )
        session.add(se_critical)

        se_warning = SubscriptionEvent(
            id=uuid.uuid4(),
            subscription_id=sub.id,
            event_name="subscription.past_due",
            previous_status="ACTIVE",
            new_status="PAST_DUE",
            payload_snapshot={},
            received_at=datetime.now(timezone.utc)
        )
        session.add(se_warning)

        # C. Seed Claims Request (INFO / WARNING)
        claim = TempleClaimRequest(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            claimant_id=admin_id,
            status="REJECTED",
            target_management_mode="GOVERNED",
            target_subscription_plan="GOVERNED_STANDARD",
            trial_duration_days=30,
            claimant_notes="Proof attached",
            reviewed_by=admin_id,
            rejection_reason="Incomplete proof of address",
            reviewed_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc)
        )
        session.add(claim)

        # D. Seed Website Review Cycles in AuditLog (INFO / WARNING)
        web_audit = AuditLog(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            user_id=admin_id,
            role="SUPER_ADMIN",
            module_name="digital_experience",
            action="REJECT_WEBSITE_REVIEW",
            action_type="UPDATE",
            details="Rejected because primary color is too bright",
            created_at=datetime.now(timezone.utc)
        )
        session.add(web_audit)

        # E. Seed Governance state transition (CRITICAL / WARNING / INFO)
        state_audit = OperationalStateAudit(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            old_state="ACTIVE",
            new_state="SUSPENDED",
            changed_by=admin_id,
            reason="Violation of terms",
            created_at=datetime.now(timezone.utc)
        )
        session.add(state_audit)

        await session.commit()

    # 2. Query endpoint as SuperAdmin (Authorized)
    resp = await client.get(
        f"/api/v1/superadmin/temples/{TEMPLE_ID}/governance-timeline",
        headers=superadmin_auth_headers
    )
    assert resp.status_code == 200, f"Expected 200, got: {resp.text}"
    data = resp.json()
    assert "events" in data
    assert "total" in data
    events = data["events"]
    assert len(events) > 0

    # 3. Verify Refinement 1: Category Mappings & Filtering
    # Assert we can query distinct filters
    resp_billing = await client.get(
        f"/api/v1/superadmin/temples/{TEMPLE_ID}/governance-timeline?event_type=BILLING",
        headers=superadmin_auth_headers
    )
    assert resp_billing.status_code == 200
    billing_events = resp_billing.json()["events"]
    assert all(e["event_type"] == "BILLING" for e in billing_events)
    assert len(billing_events) == 2

    resp_ownership = await client.get(
        f"/api/v1/superadmin/temples/{TEMPLE_ID}/governance-timeline?event_type=OWNERSHIP",
        headers=superadmin_auth_headers
    )
    assert resp_ownership.status_code == 200
    ownership_events = resp_ownership.json()["events"]
    assert all(e["event_type"] == "OWNERSHIP" for e in ownership_events)
    assert len(ownership_events) == 1

    # 4. Verify Refinement 2: Source Reference Metadata
    for ev in events:
        assert "source_table" in ev
        assert "source_id" in ev
        assert ev["source_table"] in (
            "temple_ownership_history",
            "subscription_events",
            "temple_claim_requests",
            "audit_logs",
            "operational_state_audits"
        )
        assert len(ev["source_id"]) > 0

    # 5. Verify Refinement 3: Severity levels
    severities = [e["severity"] for e in events]
    assert "CRITICAL" in severities  # from CANCELLED subscription status & SUSPENDED state
    assert "WARNING" in severities   # from PAST_DUE & claim rejection & website rejection
    assert "INFO" in severities      # from ownership mode update & claim submission

    # 6. Verify Refinement 4: Pagination Support
    resp_page = await client.get(
        f"/api/v1/superadmin/temples/{TEMPLE_ID}/governance-timeline?page=1&page_size=2",
        headers=superadmin_auth_headers
    )
    assert resp_page.status_code == 200
    page_data = resp_page.json()
    assert len(page_data["events"]) == 2
    assert page_data["total"] == data["total"]

    # 7. Verify username resolution
    # Check that changed_by_name matches the seeded user name/email/ID
    for ev in events:
        if ev["changed_by"] == str(admin_id):
            assert ev["changed_by_name"] == superadmin_user.name or superadmin_user.email or superadmin_user.user_id

    # 8. Verify Authentication Boundary (Non-SuperAdmin should be rejected)
    resp_forbidden = await client.get(
        f"/api/v1/superadmin/temples/{TEMPLE_ID}/governance-timeline",
        headers=auth_headers
    )
    assert resp_forbidden.status_code == 403
