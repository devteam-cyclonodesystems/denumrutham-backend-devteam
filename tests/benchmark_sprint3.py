import asyncio
import time
import uuid
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Setup in-memory SQLite
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

# Override database globally before importing app
import app.core.database.database
app.core.database.database.engine = test_engine
app.core.database.database.AsyncSessionLocal = TestSessionLocal

import app.core.database
app.core.database.engine = test_engine
app.core.database.AsyncSessionLocal = TestSessionLocal

from app.core.database import Base, get_db
from app.models.domain import (
    Temple,
    TempleService,
    StoreProduct,
    ServiceRecommendation,
    PlatformAdvertisement,
)
from app.main import app
from app.core.limiter import limiter
limiter.enabled = False

# Override dependency
async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

app.dependency_overrides[get_db] = override_get_db

TEMPLE_ID = uuid.uuid4()
SERVICE_ID = uuid.uuid4()
PRODUCT_ID = uuid.uuid4()
AD_ID = uuid.uuid4()

async def seed_data():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with TestSessionLocal() as session:
        # Seed temple
        temple = Temple(
            id=TEMPLE_ID,
            name="Benchmark Temple",
            domain="benchmark-temple",
            status="APPROVED",
            is_active=True
        )
        session.add(temple)
        
        # Seed service
        service = TempleService(
            id=SERVICE_ID,
            temple_id=TEMPLE_ID,
            service_name="Benchmark Pooja",
            service_type="ARCHANA",
            price=150.0,
            active=True
        )
        session.add(service)
        
        # Seed product
        product = StoreProduct(
            id=PRODUCT_ID,
            temple_id=TEMPLE_ID,
            name="Benchmark Prasadam",
            category="Food",
            unit="box",
            unit_price=50.0,
            is_active=True
        )
        session.add(product)
        
        # Seed recommendation
        rec = ServiceRecommendation(
            temple_id=TEMPLE_ID,
            source_service_id=SERVICE_ID,
            source_product_id=None,
            recommendation_source_type="SERVICE",
            recommended_service_id=None,
            recommended_product_id=PRODUCT_ID,
            display_order=1,
            is_active=True
        )
        session.add(rec)
        
        # Seed advertisement
        now = datetime.now(timezone.utc)
        ad = PlatformAdvertisement(
            id=AD_ID,
            placement="HEADER_LEADERBOARD",
            media_type="IMAGE",
            media_urls=["https://url1.com"],
            target_url="https://target.com",
            start_date=now,
            end_date=now + timedelta(days=1),
            is_active=True
        )
        session.add(ad)
        
        await session.commit()

async def benchmark_resolver(client: AsyncClient, n_requests: int):
    url = f"/api/v1/public/temples/benchmark-temple/recommendations?service_id={SERVICE_ID}"
    latencies = []
    
    for _ in range(n_requests):
        start = time.perf_counter()
        resp = await client.get(url)
        latency = (time.perf_counter() - start) * 1000 # in ms
        assert resp.status_code == 200, f"Resolver failed with {resp.status_code}"
        latencies.append(latency)
    return latencies

async def benchmark_telemetry(client: AsyncClient, n_requests: int):
    url = "/api/v1/public/advertisements/events"
    latencies = []
    
    for i in range(n_requests):
        payload = {
            "advertisement_id": str(AD_ID),
            "advertisement_type": "PLATFORM",
            "event_type": "CLICK",
            "visitor_hash": f"visitor-{i}",
            "session_id": "session-1"
        }
        start = time.perf_counter()
        resp = await client.post(url, json=payload)
        latency = (time.perf_counter() - start) * 1000 # in ms
        assert resp.status_code == 200, f"Telemetry failed with {resp.status_code}"
        latencies.append(latency)
    return latencies

async def main():
    print("Seeding benchmark data...")
    await seed_data()
    
    transport = ASGITransport(app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Warmup
        print("Warming up endpoints...")
        await client.get(f"/api/v1/public/temples/benchmark-temple/recommendations?service_id={SERVICE_ID}")
        await client.post("/api/v1/public/advertisements/events", json={
            "advertisement_id": str(AD_ID),
            "advertisement_type": "PLATFORM",
            "event_type": "CLICK",
            "visitor_hash": "warmup-visitor",
            "session_id": "session-1"
        })
        
        # 1. Benchmark Resolver
        print("Benchmarking Recommendations Resolver (100 requests)...")
        resolver_latencies = await benchmark_resolver(client, 100)
        
        # 2. Benchmark Telemetry Logging
        print("Benchmarking Telemetry Logging (100 requests)...")
        telemetry_latencies = await benchmark_telemetry(client, 100)
        
    # Print metrics
    def print_metrics(name: str, latencies: list, target_mean: float):
        if not latencies:
            print(f"No latencies recorded for {name}!")
            return
            
        mean = sum(latencies) / len(latencies)
        sorted_lat = sorted(latencies)
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        max_val = max(latencies)
        status = "PASSED" if mean < target_mean else "FAILED"
        
        print(f"\n================ {name} PERFORMANCE ================")
        print(f"Mean Latency: {mean:.2f} ms (Target: < {target_mean} ms) - {status}")
        print(f"95th Percentile: {p95:.2f} ms")
        print(f"Max Latency: {max_val:.2f} ms")
        
        if mean >= target_mean:
            print(f"WARNING: SLA breach on {name}!")

    print_metrics("Recommendations Resolver", resolver_latencies, 200.0)
    print_metrics("Telemetry Analytics Logger", telemetry_latencies, 50.0)
    
    # Clean up DB connections to allow clean exit
    await test_engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
