import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_archana_booking_lifecycle(client: AsyncClient, auth_headers):
    # 0. Create a Deity first
    deity_resp = await client.post(
        "/api/v1/archana-bookings/deities",
        json={"deity_name": "Ganesha"},
        headers=auth_headers,
    )
    assert deity_resp.status_code == 200
    deity_id = deity_resp.json()["data"]["id"]

    # 1. Create a catalog item
    catalog_resp = await client.post(
        "/api/v1/archana-bookings/catalog/create",
        json={
            "name": "Special Archana",
            "price": 250.0,
            "deity_id": deity_id,
            "duration_minutes": 10,
            "description": "Special pooja for testing",
            "is_active": True,
        },
        params={"auto_approve": "true"},
        headers=auth_headers,
    )
    assert catalog_resp.status_code == 200
    catalog_id = catalog_resp.json()["data"]["id"]

    # 2. Create a future booking (1 day in the future)
    future_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    future_booking_resp = await client.post(
        "/api/v1/archana-bookings",
        json={
            "primary_devotee_name": "John Doe",
            "phone_number": "1234567890",
            "ritual_time": future_time,
            "members": [
                {
                    "name": "John Doe",
                    "nakshatra": "Rohini",
                    "is_primary": True,
                    "items": [{"service_id": catalog_id, "quantity": 1}],
                }
            ],
        },
        headers=auth_headers,
    )
    assert future_booking_resp.status_code == 200
    future_booking = future_booking_resp.json()["data"]
    assert future_booking["status"] == "CONFIRMED"
    assert future_booking["queue_entry"] is None

    # 3. Create an immediate booking (now / no ritual_time or past ritual_time)
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    immediate_booking_resp = await client.post(
        "/api/v1/archana-bookings",
        json={
            "primary_devotee_name": "Jane Smith",
            "phone_number": "9876543210",
            "ritual_time": past_time,
            "members": [
                {
                    "name": "Jane Smith",
                    "nakshatra": "Krittika",
                    "is_primary": True,
                    "items": [{"service_id": catalog_id, "quantity": 1}],
                }
            ],
        },
        headers=auth_headers,
    )
    assert immediate_booking_resp.status_code == 200
    immediate_booking = immediate_booking_resp.json()["data"]
    assert immediate_booking["status"] == "CONFIRMED"
    assert immediate_booking["queue_entry"] is not None
    assert immediate_booking["queue_entry"]["token_number"].startswith("T-")

    # 4. Check list response and computed statuses
    list_resp = await client.get("/api/v1/archana-bookings", headers=auth_headers)
    assert list_resp.status_code == 200
    bookings_list = list_resp.json()["data"]
    
    # Verify that future booking is computed as "Upcoming" and immediate booking is "Waiting"
    future_in_list = next(b for b in bookings_list if b["id"] == future_booking["id"])
    immediate_in_list = next(b for b in bookings_list if b["id"] == immediate_booking["id"])
    
    assert future_in_list["computed_status"] == "Upcoming"
    assert immediate_in_list["computed_status"] == "Waiting"


@pytest.mark.asyncio
async def test_timezone_stabilization_and_promotion(client: AsyncClient, auth_headers):
    # 1. Create a Deity first
    deity_resp = await client.post(
        "/api/v1/archana-bookings/deities",
        json={"deity_name": "Murugan"},
        headers=auth_headers,
    )
    assert deity_resp.status_code == 200
    deity_id = deity_resp.json()["data"]["id"]

    # 2. Create catalog item
    catalog_resp = await client.post(
        "/api/v1/archana-bookings/catalog/create",
        json={
            "name": "Pooja Test",
            "price": 100.0,
            "deity_id": deity_id,
            "duration_minutes": 5,
            "is_active": True,
        },
        params={"auto_approve": "true"},
        headers=auth_headers,
    )
    assert catalog_resp.status_code == 200
    catalog_id = catalog_resp.json()["data"]["id"]

    # 3. Create a booking with a timezone-naive datetime (representing 2026-05-22 16:58:00)
    booking_resp = await client.post(
        "/api/v1/archana-bookings",
        json={
            "primary_devotee_name": "Devotee One",
            "phone_number": "9999999999",
            "ritual_time": "2026-05-22T16:58:00",
            "members": [
                {
                    "name": "Devotee One",
                    "nakshatra": "Anuradha",
                    "is_primary": True,
                    "items": [{"service_id": catalog_id, "quantity": 1}],
                }
            ],
        },
        headers=auth_headers,
    )
    assert booking_resp.status_code == 200
    booking_data = booking_resp.json()["data"]
    booking_id = booking_data["id"]

    # Verify that:
    # 1. IST Serialization: Stored database UTC returns as "2026-05-22T16:58:00+05:30" in the API response.
    assert booking_data["ritual_time"] == "2026-05-22T16:58:00+05:30"

    # 2. Naive Input Localization: The datetime was saved in the database converted to UTC (2026-05-22 11:28:00+00:00).
    from app.core.database import AsyncSessionLocal
    from app.models.archana import EnterpriseArchanaBooking
    from sqlalchemy import select
    from uuid import UUID
    
    async with AsyncSessionLocal() as session:
        db_res = await session.execute(
            select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == UUID(booking_id))
        )
        db_booking = db_res.scalar_one()
        assert db_booking.ritual_time is not None
        db_time = db_booking.ritual_time
        if db_time.tzinfo is None:
            db_time = db_time.replace(tzinfo=timezone.utc)
        
        # Convert to UTC for assertion
        utc_time = db_time.astimezone(timezone.utc)
        assert utc_time.year == 2026
        assert utc_time.month == 5
        assert utc_time.day == 22
        assert utc_time.hour == 11
        assert utc_time.minute == 28
        assert utc_time.second == 0

    # 3. Queue Promotion: Let's test that the promote_matured_bookings service promotes matured bookings.
    future_dt_ist = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))) + timedelta(minutes=10)
    future_time_str = future_dt_ist.isoformat()
    
    future_resp = await client.post(
        "/api/v1/archana-bookings",
        json={
            "primary_devotee_name": "Devotee Two",
            "ritual_time": future_time_str,
            "members": [
                {
                    "name": "Devotee Two",
                    "items": [{"service_id": catalog_id, "quantity": 1}],
                }
            ],
        },
        headers=auth_headers,
    )
    assert future_resp.status_code == 200
    future_booking_data = future_resp.json()["data"]
    assert future_booking_data["queue_entry"] is None

    # Update in DB to be in the past
    past_dt_utc = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with AsyncSessionLocal() as session:
        db_res = await session.execute(
            select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == UUID(future_booking_data["id"]))
        )
        db_booking = db_res.scalar_one()
        db_booking.ritual_time = past_dt_utc
        await session.commit()

    # Verify that calling details endpoint promotes it and yields a queue entry
    details_resp = await client.get(
        f"/api/v1/archana-bookings/{future_booking_data['id']}/details",
        headers=auth_headers,
    )
    assert details_resp.status_code == 200
    details_data = details_resp.json()["data"]
    assert details_data["queue"] is not None
    assert details_data["queue"]["token_number"] is not None
    assert details_data["computed_status"] == "Waiting"

