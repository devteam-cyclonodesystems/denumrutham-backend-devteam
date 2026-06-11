"""
Shared fixtures for the TMS backend test suite.

Uses an in-process SQLite async database so tests run without
needing PostgreSQL or Docker.
"""
import asyncio
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

# Override database engine and sessionmaker globally BEFORE any other imports can capture the Postgres engine
import app.core.database.database
app.core.database.database.engine = test_engine
app.core.database.database.AsyncSessionLocal = TestSessionLocal

import app.core.database
app.core.database.engine = test_engine
app.core.database.AsyncSessionLocal = TestSessionLocal

from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.domain import Temple, User

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Disable rate limiting for tests
from app.core.limiter import limiter
limiter.enabled = False

from app.main import app


# ---------------------------------------------------------------------------
# Create / drop tables once per session
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Override get_db so every route uses the test database
# ---------------------------------------------------------------------------
async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

app.dependency_overrides[get_db] = override_get_db


# ---------------------------------------------------------------------------
# Seed data: one temple + one admin user
# ---------------------------------------------------------------------------
TEMPLE_ID = uuid.uuid4()
ADMIN_USER_ID = "superadmin@temple"
ADMIN_PASSWORD = "admin@123"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def seed_data(setup_database):
    async with TestSessionLocal() as session:
        temple = Temple(
            id=TEMPLE_ID,
            name="Test Temple",
            domain="test",
            status="APPROVED",
            management_mode="SELF_MANAGED",
        )
        session.add(temple)
        await session.commit()

        # Seed global permissions and default roles for testing
        from app.services.staff_service import StaffService
        await StaffService.seed_global_permissions(session)
        await StaffService.seed_default_temple_roles(session, TEMPLE_ID)

        admin = User(
            user_id=ADMIN_USER_ID,
            password_hash=get_password_hash(ADMIN_PASSWORD),
            role="ADMIN",
            temple_id=TEMPLE_ID,
        )
        session.add(admin)

        superadmin = User(
            user_id="superadmin_test@temple",
            password_hash=get_password_hash("superadmin@123"),
            role="SUPERADMIN",
            temple_id=TEMPLE_ID,
        )
        session.add(superadmin)
        await session.flush()

        from app.models.rbac import Role, UserRole
        from sqlalchemy.future import select
        role_res = await session.execute(
            select(Role).filter(Role.temple_id == TEMPLE_ID, Role.name == "Manager")
        )
        manager_role = role_res.scalars().first()
        if manager_role:
            ur = UserRole(
                user_id=admin.id,
                role_id=manager_role.id,
                temple_id=TEMPLE_ID
            )
            session.add(ur)
        
        await session.commit()


# ---------------------------------------------------------------------------
# Async HTTP client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helper: get a valid admin JWT
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def admin_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": ADMIN_USER_ID, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["data"]["access_token"]


@pytest_asyncio.fixture
def auth_headers(admin_token: str):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def superadmin_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "superadmin_test@temple", "password": "superadmin@123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["data"]["access_token"]


@pytest_asyncio.fixture
def superadmin_auth_headers(superadmin_token: str):
    return {"Authorization": f"Bearer {superadmin_token}"}
