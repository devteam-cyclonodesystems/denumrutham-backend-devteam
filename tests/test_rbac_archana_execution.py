import pytest
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.domain import User, Temple
from app.models.rbac import Role, UserRole
from app.models.archana import EnterpriseArchanaBooking, ArchanaExecution, QueueStatus

@pytest.fixture(scope="module")
def temple_id():
    # Reuse TEMPLE_ID from conftest if needed, or define the same uuid
    from tests.conftest import TEMPLE_ID
    return TEMPLE_ID

async def create_test_user_with_role(db, username, password, role_name, temple_id):
    # Check if user already exists
    existing = await db.execute(select(User).filter(User.user_id == username))
    user = existing.scalars().first()
    if not user:
        user = User(
            user_id=username,
            name=username.split("@")[0].capitalize(),
            email=username,
            password_hash=get_password_hash(password),
            role="STAFF",
            status="ACTIVE",
            temple_id=temple_id,
            onboarding_method="ADMIN_CREATED",
            approval_status="APPROVED",
            force_password_change=False
        )
        db.add(user)
        await db.flush()

        role_res = await db.execute(
            select(Role).filter(Role.temple_id == temple_id, Role.name == role_name)
        )
        role = role_res.scalars().first()
        if role:
            ur = UserRole(
                user_id=user.id,
                role_id=role.id,
                temple_id=temple_id
            )
            db.add(ur)
            await db.flush()
        await db.commit()
    return user

@pytest.mark.asyncio
async def test_rbac_archana_execution_workflow(client: AsyncClient, auth_headers, temple_id):
    async with AsyncSessionLocal() as session:
        # Create Priest User
        priest_user = await create_test_user_with_role(
            session, "test_priest@temple.com", "Priest@123", "Priest", temple_id
        )
        # Create Counter Staff User
        counter_user = await create_test_user_with_role(
            session, "test_counter@temple.com", "Counter@123", "Counter Staff", temple_id
        )

    # Login as Priest to get token
    priest_login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "test_priest@temple.com", "password": "Priest@123"},
    )
    assert priest_login_resp.status_code == 200
    priest_token = priest_login_resp.json()["data"]["access_token"]
    priest_headers = {"Authorization": f"Bearer {priest_token}"}

    # Login as Counter Staff to get token
    counter_login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "test_counter@temple.com", "password": "Counter@123"},
    )
    assert counter_login_resp.status_code == 200
    counter_token = counter_login_resp.json()["data"]["access_token"]
    counter_headers = {"Authorization": f"Bearer {counter_token}"}

    # Manager is auth_headers
    manager_headers = auth_headers

    # 1. Create Deity and Catalog item to create a booking
    deity_resp = await client.post(
        "/api/v1/archana-bookings/deities",
        json={"deity_name": "Shiva"},
        headers=manager_headers,
    )
    assert deity_resp.status_code == 200
    deity_id = deity_resp.json()["data"]["id"]

    catalog_resp = await client.post(
        "/api/v1/archana-bookings/catalog/create",
        json={
            "name": "Panchamrutham",
            "price": 150.0,
            "deity_id": deity_id,
            "duration_minutes": 15,
            "is_active": True,
        },
        params={"auto_approve": "true"},
        headers=manager_headers,
    )
    assert catalog_resp.status_code == 200
    catalog_id = catalog_resp.json()["data"]["id"]

    # 2. Create an immediate booking (which automatically places it in the ritual queue / Waiting state)
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    booking_resp = await client.post(
        "/api/v1/archana-bookings",
        json={
            "primary_devotee_name": "Ramesh Kumar",
            "phone_number": "9999888877",
            "ritual_time": past_time,
            "members": [
                {
                    "name": "Ramesh Kumar",
                    "nakshatra": "Aswathy",
                    "is_primary": True,
                    "items": [{"service_id": catalog_id, "quantity": 1}],
                }
            ],
        },
        headers=manager_headers,
    )
    assert booking_resp.status_code == 200
    booking_data = booking_resp.json()["data"]
    queue_entry_id = booking_data["queue_entry"]["id"]
    
    # Query execution_id from database using queue_entry_id
    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.queue_id == uuid.UUID(queue_entry_id))
        )
        execution_record = exec_res.scalars().first()
        assert execution_record is not None
        execution_id = str(execution_record.id)

    # Verify status is Waiting
    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == uuid.UUID(execution_id))
        )
        execution = exec_res.scalar_one()
        assert execution.status == QueueStatus.WAITING
        assert execution.started_by_user_id is None
        assert execution.priest_id is None

    # --- API Permission Enforcement Validation ---

    # 3. Counter Staff tries to start execution -> Should be 403 Forbidden
    counter_start_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/start",
        json={},
        headers=counter_headers,
    )
    assert counter_start_resp.status_code == 403

    # 4. Priest tries to start execution -> Should be 200 OK
    priest_start_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/start",
        json={},
        headers=priest_headers,
    )
    assert priest_start_resp.status_code == 200

    # 5. Database Verification (Phase 5)
    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == uuid.UUID(execution_id))
        )
        execution = exec_res.scalar_one()
        assert execution.status == QueueStatus.IN_PROGRESS
        assert execution.started_by_user_id == priest_user.id
        assert execution.start_time is not None
        assert execution.priest_id is None # No employee dependency

    # 6. Counter Staff tries to complete execution -> Should be 403 Forbidden
    counter_complete_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/complete",
        json={},
        headers=counter_headers,
    )
    assert counter_complete_resp.status_code == 403

    # 7. Priest tries to complete execution -> Should be 200 OK
    priest_complete_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/complete",
        json={},
        headers=priest_headers,
    )
    assert priest_complete_resp.status_code == 200

    # 8. Database Verification for Completion (Phase 5)
    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == uuid.UUID(execution_id))
        )
        execution = exec_res.scalar_one()
        assert execution.status == QueueStatus.COMPLETED
        assert execution.completed_by_user_id == priest_user.id
        assert execution.completed_at is not None

    # --- Start Selected (Waiting List / Grouped Start) Test ---

    # 9. Create another immediate booking
    booking_resp2 = await client.post(
        "/api/v1/archana-bookings",
        json={
            "primary_devotee_name": "Suresh Kumar",
            "phone_number": "9999888876",
            "ritual_time": past_time,
            "members": [
                {
                    "name": "Suresh Kumar",
                    "nakshatra": "Aswathy",
                    "is_primary": True,
                    "items": [{"service_id": catalog_id, "quantity": 1}],
                }
            ],
        },
        headers=manager_headers,
    )
    assert booking_resp2.status_code == 200
    booking_data2 = booking_resp2.json()["data"]
    queue_entry_id2 = booking_data2["queue_entry"]["id"]
    
    # Query execution_id from database using queue_entry_id
    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.queue_id == uuid.UUID(queue_entry_id2))
        )
        execution_record2 = exec_res.scalars().first()
        assert execution_record2 is not None
        execution_id2 = str(execution_record2.id)

    # Counter staff tries to start selected -> 403 Forbidden
    counter_bulk_start_resp = await client.post(
        "/api/v1/archana-bookings/executions/start-selected",
        json={"execution_ids": [execution_id2]},
        headers=counter_headers,
    )
    assert counter_bulk_start_resp.status_code == 403

    # Priest tries to start selected -> 200 OK
    priest_bulk_start_resp = await client.post(
        "/api/v1/archana-bookings/executions/start-selected",
        json={"execution_ids": [execution_id2]},
        headers=priest_headers,
    )
    assert priest_bulk_start_resp.status_code == 200

    # Verification of bulk start
    async with AsyncSessionLocal() as session:
        exec_res2 = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == uuid.UUID(execution_id2))
        )
        execution2 = exec_res2.scalar_one()
        assert execution2.status == QueueStatus.IN_PROGRESS
        assert execution2.started_by_user_id == priest_user.id
        assert execution2.priest_id is None

async def create_custom_role_with_permissions(db, role_name, permission_keys, temple_id):
    from app.models.rbac import Role, Permission, RolePermission
    role = Role(
        temple_id=temple_id,
        name=role_name,
        description=f"Test role for {role_name}",
        is_active=True
    )
    db.add(role)
    await db.flush()

    for p_key in permission_keys:
        perm_res = await db.execute(
            select(Permission).filter(Permission.resource_key == p_key)
        )
        perm = perm_res.scalars().first()
        if not perm:
            perm = Permission(
                temple_id=None,
                resource_type=p_key.split(":")[0],
                resource_key=p_key,
                description=f"Test {p_key}"
            )
            db.add(perm)
            await db.flush()
        
        rp = RolePermission(
            role_id=role.id,
            permission_id=perm.id,
            access_level="full"
        )
        db.add(rp)
    await db.commit()
    return role

@pytest.mark.asyncio
async def test_strict_permission_boundaries_and_legacy_payloads(client: AsyncClient, auth_headers, temple_id):
    async with AsyncSessionLocal() as session:
        # Create start-only role and user
        start_only_role = await create_custom_role_with_permissions(
            session, "Start Only Role", ["dashboard:view", "archana:view_queue", "archana:start_ritual"], temple_id
        )
        start_only_user = User(
            user_id="start_only@temple.com",
            name="Start Only",
            email="start_only@temple.com",
            password_hash=get_password_hash("StartOnly@123"),
            role="STAFF",
            status="ACTIVE",
            temple_id=temple_id,
            onboarding_method="ADMIN_CREATED",
            approval_status="APPROVED",
            force_password_change=False
        )
        session.add(start_only_user)
        await session.flush()
        ur1 = UserRole(user_id=start_only_user.id, role_id=start_only_role.id, temple_id=temple_id)
        session.add(ur1)

        # Create complete-only role and user
        complete_only_role = await create_custom_role_with_permissions(
            session, "Complete Only Role", ["dashboard:view", "archana:view_queue", "archana:complete_ritual"], temple_id
        )
        complete_only_user = User(
            user_id="complete_only@temple.com",
            name="Complete Only",
            email="complete_only@temple.com",
            password_hash=get_password_hash("CompleteOnly@123"),
            role="STAFF",
            status="ACTIVE",
            temple_id=temple_id,
            onboarding_method="ADMIN_CREATED",
            approval_status="APPROVED",
            force_password_change=False
        )
        session.add(complete_only_user)
        await session.flush()
        ur2 = UserRole(user_id=complete_only_user.id, role_id=complete_only_role.id, temple_id=temple_id)
        session.add(ur2)
        await session.commit()

    # Login both
    login1_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "start_only@temple.com", "password": "StartOnly@123"},
    )
    assert login1_resp.status_code == 200
    token1 = login1_resp.json()["data"]["access_token"]
    headers_start = {"Authorization": f"Bearer {token1}"}

    login2_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "complete_only@temple.com", "password": "CompleteOnly@123"},
    )
    assert login2_resp.status_code == 200
    token2 = login2_resp.json()["data"]["access_token"]
    headers_complete = {"Authorization": f"Bearer {token2}"}

    manager_headers = auth_headers

    # 1. Create Deity and Catalog item to create a booking
    deity_resp = await client.post(
        "/api/v1/archana-bookings/deities",
        json={"deity_name": "Ganesha_Test"},
        headers=manager_headers,
    )
    assert deity_resp.status_code == 200
    deity_id = deity_resp.json()["data"]["id"]

    catalog_resp = await client.post(
        "/api/v1/archana-bookings/catalog/create",
        json={
            "name": "Ganapathi Homam Test",
            "price": 250.0,
            "deity_id": deity_id,
            "duration_minutes": 20,
            "is_active": True,
        },
        params={"auto_approve": "true"},
        headers=manager_headers,
    )
    assert catalog_resp.status_code == 200
    catalog_id = catalog_resp.json()["data"]["id"]

    # 2. Create immediate booking
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    booking_resp = await client.post(
        "/api/v1/archana-bookings",
        json={
            "primary_devotee_name": "Devotee Kumar",
            "phone_number": "9999555544",
            "ritual_time": past_time,
            "members": [
                {
                    "name": "Devotee Kumar",
                    "nakshatra": "Aswathy",
                    "is_primary": True,
                    "items": [{"service_id": catalog_id, "quantity": 1}],
                }
            ],
        },
        headers=manager_headers,
    )
    assert booking_resp.status_code == 200
    booking_data = booking_resp.json()["data"]
    queue_entry_id = booking_data["queue_entry"]["id"]

    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.queue_id == uuid.UUID(queue_entry_id))
        )
        execution_record = exec_res.scalars().first()
        execution_id = str(execution_record.id)

    # Test permissions:
    # 3. Complete-only user tries to start ritual -> Should be 403 Forbidden
    complete_only_start_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/start",
        json={"priest_id": str(uuid.uuid4())}, # Invalid priest_id
        headers=headers_complete,
    )
    assert complete_only_start_resp.status_code == 403

    # 4. Start-only user starts ritual with legacy payload (invalid priest_id) -> Should succeed (200 OK)
    legacy_priest_id = str(uuid.uuid4())
    start_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/start",
        json={"priest_id": legacy_priest_id},
        headers=headers_start,
    )
    assert start_resp.status_code == 200

    # 5. Database assertions for start
    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == uuid.UUID(execution_id))
        )
        execution = exec_res.scalar_one()
        assert execution.status == QueueStatus.IN_PROGRESS
        assert execution.started_by_user_id == start_only_user.id
        assert execution.start_time is not None
        assert execution.priest_id is None # Option B: ignored entirely and written as NULL

    # 6. Start-only user tries to complete ritual -> Should be 403 Forbidden
    start_only_complete_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/complete",
        json={},
        headers=headers_start,
    )
    assert start_only_complete_resp.status_code == 403

    # 7. Complete-only user completes ritual -> Should succeed (200 OK)
    complete_resp = await client.post(
        f"/api/v1/archana-bookings/executions/{execution_id}/complete",
        json={},
        headers=headers_complete,
    )
    assert complete_resp.status_code == 200

    # 8. Database assertions for completion
    async with AsyncSessionLocal() as session:
        exec_res = await session.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == uuid.UUID(execution_id))
        )
        execution = exec_res.scalar_one()
        assert execution.status == QueueStatus.COMPLETED
        assert execution.completed_by_user_id == complete_only_user.id
        assert execution.completed_at is not None
