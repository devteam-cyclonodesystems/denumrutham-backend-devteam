import pytest
import pytest_asyncio
import uuid
from uuid import uuid4, UUID
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import delete

from tests.conftest import TestSessionLocal
from app.models.domain import Temple, StateMaster, DistrictMaster, User
from app.modules.governance.models.governance_models import (
    TempleSuggestion, TempleSuggestionContact, TempleSuggestionImage,
    TempleSuggestionAudit, TempleSuggestionStatus, Notification
)
from app.core.security import get_password_hash
from app.models.system_rbac import SystemRole
from app.scripts.seed_system_rbac import seed_system_rbac
from app.modules.auth.services.permission_service import invalidate_all_cache
from app.modules.temple_management.models.temple_models import TempleImage

@pytest_asyncio.fixture(autouse=True)
async def setup_permissions_for_suggestions(setup_database):
    """Seed system roles/permissions and assign SUPER_ADMIN system role to superadmin_test user."""
    async with TestSessionLocal() as session:
        await seed_system_rbac(session)

        # Get SUPER_ADMIN role
        role_res = await session.execute(select(SystemRole).filter(SystemRole.name == "SUPER_ADMIN"))
        super_admin_role = role_res.scalars().first()
        assert super_admin_role is not None

        # Assign SUPER_ADMIN role to superadmin_test@temple user
        user_res = await session.execute(select(User).filter(User.user_id == "superadmin_test@temple"))
        user = user_res.scalars().first()
        if user:
            user.system_role_id = super_admin_role.id
            await session.commit()
        
        # Clear permission cache to make sure has_permission loads fresh assignments
        invalidate_all_cache()


@pytest_asyncio.fixture(autouse=True)
async def clear_suggestions_db():
    """Clean up suggestions and ensure devotee user exists."""
    async with TestSessionLocal() as session:
        # Delete suggestion data
        await session.execute(delete(TempleSuggestionAudit))
        await session.execute(delete(TempleSuggestionImage))
        await session.execute(delete(TempleSuggestionContact))
        await session.execute(delete(TempleSuggestion))
        await session.execute(delete(Notification))
        await session.execute(delete(Temple).filter(Temple.creation_source == "DEVOTEE_SUGGESTION"))
        
        # Ensure test devotee user exists
        res = await session.execute(select(User).filter(User.user_id == "devotee_suggestor@temple.org"))
        devotee = res.scalars().first()
        if not devotee:
            devotee = User(
                id=uuid4(),
                user_id="devotee_suggestor@temple.org",
                password_hash=get_password_hash("devotee@123"),
                role="DEVOTEE",
                status="ACTIVE",
                is_active=True
            )
            session.add(devotee)

        # Ensure second devotee user exists to bypass rate limits in subsequent submissions
        res2 = await session.execute(select(User).filter(User.user_id == "devotee_suggestor2@temple.org"))
        devotee2 = res2.scalars().first()
        if not devotee2:
            devotee2 = User(
                id=uuid4(),
                user_id="devotee_suggestor2@temple.org",
                password_hash=get_password_hash("devotee@123"),
                role="DEVOTEE",
                status="ACTIVE",
                is_active=True
            )
            session.add(devotee2)
        await session.commit()


@pytest.mark.asyncio
async def test_temple_suggestion_lifecycle(client, superadmin_auth_headers):
    # 1. Login Devotees
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "devotee_suggestor@temple.org", "password": "devotee@123"},
    )
    assert login_resp.status_code == 200
    devotee_token = login_resp.json()["data"]["access_token"]
    devotee_headers = {"Authorization": f"Bearer {devotee_token}"}

    login_resp2 = await client.post(
        "/api/v1/auth/login",
        data={"username": "devotee_suggestor2@temple.org", "password": "devotee@123"},
    )
    assert login_resp2.status_code == 200
    devotee_token2 = login_resp2.json()["data"]["access_token"]
    devotee2_headers = {"Authorization": f"Bearer {devotee_token2}"}

    # 2. Setup State and District
    async with TestSessionLocal() as session:
        state = StateMaster(
            id=uuid4(),
            name="Karnataka",
            slug="karnataka",
            code="KA"
        )
        session.add(state)
        await session.flush()
        
        district = DistrictMaster(
            id=uuid4(),
            state_id=state.id,
            name="Bengaluru",
            slug="bengaluru",
            code="BLR"
        )
        session.add(district)
        
        # Add an approved temple for duplicate check validation
        existing_temple = Temple(
            id=uuid4(),
            name="Sri Someshwara Temple",
            domain="someshwara-temple",
            management_mode="DIRECTORY_ONLY",
            is_active=True,
            status="APPROVED",
            state_id=state.id,
            district_id=district.id,
            pincode="560008"
        )
        session.add(existing_temple)
        await session.commit()
        
        state_id = state.id
        district_id = district.id
        existing_temple_id = existing_temple.id

    # 3. Test duplicate check API
    dup_resp = await client.post(
        "/api/v1/temple-suggestions/check-duplicates",
        json={
            "name": "Sri Someshwara Temple",
            "district_id": str(district_id),
            "pincode": "560008"
        },
        headers=devotee_headers
    )
    assert dup_resp.status_code == 200
    matches = dup_resp.json()
    assert len(matches) == 1
    assert matches[0]["name"] == "Sri Someshwara Temple"

    # 4. Suggest temple (Valid Submit)
    payload = {
        "name": "Kote Venkataramana Temple",
        "deity": "Venkataramana",
        "description": "Historical temple built in 1689",
        "address_line_1": "Krishnarajendra Road",
        "village_town": "Kalasipalya",
        "district_id": str(district_id),
        "state_id": str(state_id),
        "pincode": "560002",
        "latitude": 12.9628,
        "longitude": 77.5759,
        "website": "https://kotevenkataramana.org",
        "festival_info": "Annual Brahmotsava",
        "submitter_affiliation": "DEVOTEE",
        "contacts": [
            {
                "name": "Nagaraj Priest",
                "designation": "Chief Priest",
                "mobile_number": "+919876543210",
                "is_primary": True
            },
            {
                "name": "Secretary Ramesh",
                "designation": "Committee Secretary",
                "mobile_number": "+919876543211",
                "is_primary": False
            }
        ],
        "images": [
            {
                "image_url": "https://kotevenkataramana.org/photo.jpg",
                "is_primary": True
            }
        ]
    }
    
    suggest_resp = await client.post(
        "/api/v1/temple-suggestions",
        json=payload,
        headers=devotee_headers
    )
    assert suggest_resp.status_code == 201
    suggestion_data = suggest_resp.json()
    assert suggestion_data["name"] == "Kote Venkataramana Temple"
    assert "TS-" in suggestion_data["reference_number"]
    assert "-KA-" in suggestion_data["reference_number"] # State code KA mapped!
    assert suggestion_data["confidence_score"] == 100 # Maximum elements provided
    suggestion_id = suggestion_data["id"]

    # Verify submitter notification staged
    async with TestSessionLocal() as session:
        notif_stmt = select(Notification).filter(Notification.user_id == UUID(suggestion_data["submitted_by"]))
        notif = (await session.execute(notif_stmt)).scalars().first()
        assert notif is not None
        assert "TS-" in notif.message

    # 5. Test Rate Limiting (Devotee cannot suggest more than 3 per day)
    # We already suggested 1. Let's suggest 2 more.
    for i in range(2):
        payload["name"] = f"Temple Sug Rate Limit {i}"
        resp = await client.post("/api/v1/temple-suggestions", json=payload, headers=devotee_headers)
        assert resp.status_code == 201
    
    # 4th suggestion should fail with 429
    payload["name"] = "Limit Exceeded Temple"
    limit_resp = await client.post("/api/v1/temple-suggestions", json=payload, headers=devotee_headers)
    assert limit_resp.status_code == 429
    assert "Rate limit exceeded" in str(limit_resp.json())

    # 6. Admin lists suggestions
    list_resp = await client.get(
        "/api/v1/temple-suggestions/admin?status=PENDING",
        headers=superadmin_auth_headers
    )
    assert list_resp.status_code == 200
    admin_list = list_resp.json()["suggestions"]
    assert len(admin_list) >= 3

    # 7. Admin reads details
    detail_resp = await client.get(
        f"/api/v1/temple-suggestions/admin/{suggestion_id}",
        headers=superadmin_auth_headers
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["name"] == "Kote Venkataramana Temple"

    # 8. Admin edits and approves suggestion (Promotion Workflow)
    review_payload = {
        "status": "APPROVED",
        "name": "Kote Venkataramana Temple (Corrected)",
        "moderator_notes": "Verified temple coordinates via Google Maps. Approved."
    }
    review_resp = await client.post(
        f"/api/v1/temple-suggestions/admin/{suggestion_id}/review",
        json=review_payload,
        headers=superadmin_auth_headers
    )
    assert review_resp.status_code == 200
    reviewed_suggestion = review_resp.json()
    assert reviewed_suggestion["status"] == "APPROVED"
    assert reviewed_suggestion["promoted_temple_id"] is not None
    promoted_temple_id = reviewed_suggestion["promoted_temple_id"]

    # Verify promoted temple in DB
    async with TestSessionLocal() as session:
        temple_stmt = select(Temple).filter(Temple.id == UUID(promoted_temple_id))
        promoted_temple = (await session.execute(temple_stmt)).scalars().first()
        assert promoted_temple is not None
        assert promoted_temple.name == "Kote Venkataramana Temple (Corrected)"
        assert promoted_temple.management_mode == "DIRECTORY_ONLY"
        assert promoted_temple.creation_source == "DEVOTEE_SUGGESTION"
        assert promoted_temple.source_suggestion_id == UUID(suggestion_id)
        
        # Verify images promoted
        img_stmt = select(TempleImage).filter(TempleImage.temple_id == promoted_temple.id)
        promoted_images = (await session.execute(img_stmt)).scalars().all()
        assert len(promoted_images) == 1
        assert promoted_images[0].image_url == "https://kotevenkataramana.org/photo.jpg"

    # 9. Test Merge Review Workflow
    # Create another suggestion to merge
    payload["name"] = "Duplicate Suggestion Temple"
    dup_sug_resp = await client.post("/api/v1/temple-suggestions", json=payload, headers=devotee2_headers)
    assert dup_sug_resp.status_code == 201
    dup_sug_id = dup_sug_resp.json()["id"]

    merge_payload = {
        "status": "MERGED",
        "merged_temple_id": str(existing_temple_id),
        "moderator_notes": "Merging duplicate entry."
    }
    merge_resp = await client.post(
        f"/api/v1/temple-suggestions/admin/{dup_sug_id}/review",
        json=merge_payload,
        headers=superadmin_auth_headers
    )
    assert merge_resp.status_code == 200
    merged_suggestion = merge_resp.json()
    assert merged_suggestion["status"] == "MERGED"
    assert merged_suggestion["merged_temple_id"] == str(existing_temple_id)

    # 10. Test Rejection Workflow
    payload["name"] = "Fictional Temple Request"
    rej_sug_resp = await client.post("/api/v1/temple-suggestions", json=payload, headers=devotee2_headers)
    assert rej_sug_resp.status_code == 201
    rej_sug_id = rej_sug_resp.json()["id"]

    reject_payload = {
        "status": "REJECTED",
        "rejection_reason": "Incomplete verification details provided.",
        "moderator_notes": "Rejected."
    }
    reject_resp = await client.post(
        f"/api/v1/temple-suggestions/admin/{rej_sug_id}/review",
        json=reject_payload,
        headers=superadmin_auth_headers
    )
    assert reject_resp.status_code == 200
    rejected_suggestion = reject_resp.json()
    assert rejected_suggestion["status"] == "REJECTED"
    assert rejected_suggestion["rejection_reason"] == "Incomplete verification details provided."
