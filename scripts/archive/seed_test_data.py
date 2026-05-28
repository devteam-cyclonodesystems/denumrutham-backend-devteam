"""
seed_test_data.py — Denumrutham Test Data Seeder
================================================
Creates:
  - 1 SuperAdmin user (username: superadmin / password: superadmin123)
  - 3 temples with full TempleProfile metadata
  - 1 ADMIN user per temple (templeA_admin, templeB_admin, templeC_admin)
  - Unique Poojas per temple
  - Unique Devotees per temple
  - Archana Bookings: Temple A=10, Temple B=5, Temple C=15
  - Donations: Temple A=₹50000, Temple B=₹20000, Temple C=₹100000

Usage:
    cd backend
    python seed_test_data.py
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.domain import (
    Temple, TempleProfile, User, Devotee,
    Pooja, PoojaSlot, Booking, Donation,
    InventoryItem, BookingStatus
)
from sqlalchemy import select


def utcnow():
    return datetime.now(timezone.utc)


# ─── Temple definitions ───────────────────────────────────────────────────────
TEMPLES = [
    {
        "name": "Mallottu Sree Bhadrakali Devi Temple",
        "domain": "mallottu-bhadrakali",
        "profile": {
            "description": "Ancient temple dedicated to Goddess Bhadrakali, nestled in the Thrissur district.",
            "history": "Founded over 300 years ago by the Mallottu family. One of the prominent Bhadrakali temples in Kerala.",
            "location": "Mallottu, Thrissur",
            "district": "Thrissur",
            "state": "Kerala",
            "country": "India",
            "contact_number": "+91 9876543210",
            "email": "mallottu@denumrutham.in",
            "opening_time": "05:00",
            "closing_time": "21:00",
            "upi_id": "mallottu@upi",
            "image_url": "",
        },
        "admin": {"user_id": "templeA_admin", "password": "admin123"},
        "poojas": [
            {"name": "Ganapathi Homam", "price": 1500.0},
            {"name": "Archana", "price": 50.0},
            {"name": "Deeparadhana", "price": 200.0},
        ],
        "archana_count": 10,
        "donation_total": 50000.0,
        "devotees": [
            {"first_name": "Rajan", "last_name": "Menon", "phone": "9001001001"},
            {"first_name": "Priya", "last_name": "Nair", "phone": "9001001002"},
            {"first_name": "Suresh", "last_name": "Kumar", "phone": "9001001003"},
        ],
        "inventory": [
            {"name": "Camphor (Karporam)", "stock": 200},
            {"name": "Ghee (1L)", "stock": 50},
            {"name": "Flowers (kg)", "stock": 30},
        ],
    },
    {
        "name": "Guruvayur Temple",
        "domain": "guruvayur-temple",
        "profile": {
            "description": "The most famous Vishnu temple in Kerala, often called Bhuloka Vaikuntam.",
            "history": "Believed to be over 5000 years old, dedicated to Guruvayurappan (Lord Vishnu).",
            "location": "Guruvayur, Thrissur",
            "district": "Thrissur",
            "state": "Kerala",
            "country": "India",
            "contact_number": "+91 9876543220",
            "email": "guruvayur@denumrutham.in",
            "opening_time": "03:00",
            "closing_time": "22:00",
            "upi_id": "guruvayur@upi",
            "image_url": "",
        },
        "admin": {"user_id": "templeB_admin", "password": "admin123"},
        "poojas": [
            {"name": "Usha Pooja", "price": 5000.0},
            {"name": "Udayasthamana Pooja", "price": 10000.0},
            {"name": "Archana", "price": 25.0},
        ],
        "archana_count": 5,
        "donation_total": 20000.0,
        "devotees": [
            {"first_name": "Anitha", "last_name": "Pillai", "phone": "9002002001"},
            {"first_name": "Krishnan", "last_name": "Iyer", "phone": "9002002002"},
        ],
        "inventory": [
            {"name": "Tulsi Mala", "stock": 500},
            {"name": "Sandal Paste (100g)", "stock": 100},
            {"name": "Yellow Cloth", "stock": 60},
        ],
    },
    {
        "name": "Sabarimala Sree Dharmasastha Temple",
        "domain": "sabarimala-sastha",
        "profile": {
            "description": "One of the largest Hindu pilgrimage centres in the world, located in the Western Ghats.",
            "history": "Dedicated to Lord Ayyappan (Dharmasastha). The annual Mandala-Makaravilakku pilgrimage draws millions.",
            "location": "Sabarimala, Pathanamthitta",
            "district": "Pathanamthitta",
            "state": "Kerala",
            "country": "India",
            "contact_number": "+91 9876543230",
            "email": "sabarimala@denumrutham.in",
            "opening_time": "04:00",
            "closing_time": "22:00",
            "upi_id": "sabarimala@upi",
            "image_url": "",
        },
        "admin": {"user_id": "templeC_admin", "password": "admin123"},
        "poojas": [
            {"name": "Harivarasanam", "price": 0.0},
            {"name": "Neyyabhishekam", "price": 500.0},
            {"name": "Archana", "price": 100.0},
        ],
        "archana_count": 15,
        "donation_total": 100000.0,
        "devotees": [
            {"first_name": "Babu", "last_name": "Thomas", "phone": "9003003001"},
            {"first_name": "Meena", "last_name": "Varghese", "phone": "9003003002"},
            {"first_name": "Joseph", "last_name": "Mathew", "phone": "9003003003"},
            {"first_name": "Suja", "last_name": "George", "phone": "9003003004"},
        ],
        "inventory": [
            {"name": "Irumudi Kit", "stock": 1000},
            {"name": "Coconut Oil (5L)", "stock": 200},
            {"name": "Black Dhoti", "stock": 150},
        ],
    },
]


async def create_or_skip(db, model, filter_col, filter_val, **kwargs):
    """Create a record only if it doesn't exist; return the record."""
    result = await db.execute(select(model).where(filter_col == filter_val))
    existing = result.scalars().first()
    if existing:
        print(f"  [skip] {model.__name__} already exists: {filter_val}")
        return existing
    obj = model(**kwargs)
    db.add(obj)
    return obj


async def main():
    print("=" * 60)
    print("  Denumrutham — Test Data Seeder")
    print("=" * 60)

    async with AsyncSessionLocal() as db:

        # ─── 1. SuperAdmin ──────────────────────────────────────────
        print("\n[1] Creating SuperAdmin...")
        result = await db.execute(select(User).where(User.user_id == "superadmin"))
        sa = result.scalars().first()
        if sa:
            sa.role = "SUPERADMIN"
            sa.password_hash = get_password_hash("superadmin123")
            sa.temple_id = None
            print("  [updated] superadmin upgraded to SUPERADMIN")
        else:
            sa = User(
                user_id="superadmin",
                password_hash=get_password_hash("superadmin123"),
                role="SUPERADMIN",
                temple_id=None,
            )
            db.add(sa)
            print("  [created] superadmin / superadmin123")

        await db.flush()

        # ─── 2. Temples ─────────────────────────────────────────────
        temple_ids = {}

        for tdata in TEMPLES:
            print(f"\n[Temple] {tdata['name']}")

            # Temple record
            result = await db.execute(
                select(Temple).where(Temple.domain == tdata["domain"])
            )
            temple = result.scalars().first()
            pdata = tdata.get("profile", {})
            
            temple_kwargs = {
                "name": tdata["name"],
                "domain": tdata["domain"],
                "location": pdata.get("location", ""),
                "state": pdata.get("state", ""),
                "address_line_1": pdata.get("location", ""),
                "district": pdata.get("district", ""),
                "contact_number": pdata.get("contact_number", ""),
                "email": pdata.get("email", ""),
                "description": pdata.get("description", ""),
                "status": "active"
            }

            if not temple:
                temple = Temple(**temple_kwargs)
                db.add(temple)
                await db.flush()
                print(f"  [created] Temple id={temple.id}")
            else:
                for k, v in temple_kwargs.items():
                    setattr(temple, k, v)
                print(f"  [updated] Temple exists id={temple.id}")

            assert isinstance(temple, Temple), "Temple evaluation failed."
            temple_ids[tdata["domain"]] = temple.id

            # Temple Profile
            profile_data = tdata.get("profile", {})
            result = await db.execute(
                select(TempleProfile).where(TempleProfile.temple_id == temple.id)
            )
            profile = result.scalars().first()
            if not profile:
                profile_kwargs = profile_data if isinstance(profile_data, dict) else {}
                profile = TempleProfile(temple_id=temple.id, **profile_kwargs)
                db.add(profile)
                print(f"  [created] TempleProfile")
            else:
                # Update fields in case they changed
                if isinstance(profile_data, dict):
                    for k, v in profile_data.items():
                        setattr(profile, k, v)
                print(f"  [updated] TempleProfile")

            await db.flush()

            # Admin user for this temple
            adm = tdata.get("admin", {})
            if isinstance(adm, dict) and "user_id" in adm and "password" in adm:
                result = await db.execute(
                    select(User).where(User.user_id == adm["user_id"])
                )
                admin_user = result.scalars().first()
                if not admin_user:
                    admin_user = User(
                        user_id=adm["user_id"],
                        password_hash=get_password_hash(adm["password"]),
                        role="ADMIN",
                        temple_id=temple.id,
                    )
                    db.add(admin_user)
                    print(f"  [created] Admin user: {adm['user_id']}")
                else:
                    admin_user.password_hash = get_password_hash(adm["password"])
                    print(f"  [updated] Admin user: {adm['user_id']}")
                await db.flush()

            # Poojas
            pooja_objs = []
            pooja_list = tdata.get("poojas", [])
            if isinstance(pooja_list, list):
                for pd in pooja_list:
                    if not isinstance(pd, dict) or "name" not in pd or "price" not in pd:
                        continue
                    result = await db.execute(
                        select(Pooja).where(
                            Pooja.temple_id == temple.id,
                            Pooja.name == pd["name"],
                        )
                    )
                    p = result.scalars().first()
                    try:
                        price_val = float(pd["price"])
                    except (ValueError, TypeError):
                        price_val = 0.0

                    if not p:
                        p = Pooja(temple_id=temple.id, name=pd["name"], base_price=price_val)
                        db.add(p)
                        await db.flush()
                        print(f"  [created] Pooja: {pd['name']}")
                    else:
                        print(f"  [skip] Pooja: {pd['name']}")
                    pooja_objs.append(p)

            # Devotees
            devotee_objs = []
            dev_list = tdata.get("devotees", [])
            if isinstance(dev_list, list):
                for dd in dev_list:
                    if not isinstance(dd, dict) or "phone" not in dd:
                        continue
                    result = await db.execute(
                        select(Devotee).where(
                            Devotee.temple_id == temple.id,
                            Devotee.phone == dd["phone"],
                        )
                    )
                    dev = result.scalars().first()
                    if not dev:
                        dev = Devotee(
                            temple_id=temple.id,
                            first_name=dd.get("first_name", ""),
                            last_name=dd.get("last_name", ""),
                            phone=dd["phone"],
                        )
                        db.add(dev)
                        await db.flush()
                    devotee_objs.append(dev)
            print(f"  [synced] {len(devotee_objs)} devotees")

            # Inventory
            inv_list = tdata.get("inventory", [])
            if isinstance(inv_list, list):
                for inv in inv_list:
                    if not isinstance(inv, dict) or "name" not in inv or "stock" not in inv:
                        continue
                    result = await db.execute(
                        select(InventoryItem).where(
                            InventoryItem.temple_id == temple.id,
                            InventoryItem.name == inv["name"],
                        )
                    )
                    item = result.scalars().first()
                    try:
                        stock_val = int(inv["stock"])
                    except (ValueError, TypeError):
                        stock_val = 0

                    if not item:
                        item = InventoryItem(
                            temple_id=temple.id,
                            name=inv["name"],
                            stock=stock_val,
                        )
                        db.add(item)
            await db.flush()
            inv_count = len(inv_list) if isinstance(inv_list, list) else 0
            print(f"  [synced] {inv_count} inventory items")

            # Archana Bookings (using first pooja = named pooja per temple)
            if pooja_objs:
                archana_pooja = pooja_objs[0]
                result = await db.execute(
                    select(Booking).where(Booking.temple_id == temple.id)
                )
                existing_bookings = result.scalars().all()
                target_archana = tdata.get("archana_count", 0)
                target_archana = int(target_archana) if isinstance(target_archana, (int, str, float)) and str(target_archana).isdigit() else 0

                needed = target_archana - len(existing_bookings)
                dev_count = len(devotee_objs)
                
                if needed > 0 and dev_count > 0:
                    for i in range(needed):
                        dev = devotee_objs[i % dev_count]
                        booking = Booking(
                            temple_id=temple.id,
                            devotee_id=dev.id,
                            total_amount=archana_pooja.base_price,
                            status=BookingStatus.CONFIRMED,
                        )
                        db.add(booking)
                    await db.flush()
                    print(f"  [created] {needed} archana bookings (total: {target_archana})")
                else:
                    print(f"  [skip] Archana bookings already at {len(existing_bookings)}")

            # Donations
            result = await db.execute(
                select(Donation).where(Donation.temple_id == temple.id)
            )
            existing_donations = result.scalars().all()
            existing_total = sum(d.amount for d in existing_donations)
            
            target_donation = tdata.get("donation_total", 0.0)
            try:
                target_donation = float(str(target_donation))
            except (ValueError, TypeError):
                target_donation = 0.0

            if existing_total < target_donation and devotee_objs:
                # Create one donation for the remaining amount
                remaining = target_donation - existing_total
                dev = devotee_objs[0]
                donation = Donation(
                    temple_id=temple.id,
                    devotee_id=dev.id,
                    amount=remaining,
                    notes=f"Test seed donation for {tdata.get('name', 'Temple')}",
                )
                db.add(donation)
                await db.flush()
                print(f"  [created] Donation of ₹{remaining:,.0f} (total: ₹{target_donation:,.0f})")
            else:
                print(f"  [skip] Donations already at ₹{existing_total:,.0f}")

        await db.commit()

    print("\n" + "=" * 60)
    print("  ✅ Seed complete!")
    print("=" * 60)
    print()
    print("  SuperAdmin Login:")
    print("    Username : superadmin")
    print("    Password : superadmin123")
    print()
    print("  Temple Admin Logins:")
    print("    templeA_admin / admin123  →  Mallottu Bhadrakali")
    print("    templeB_admin / admin123  →  Guruvayur Temple")
    print("    templeC_admin / admin123  →  Sabarimala Temple")
    print()
    print("  Data per temple:")
    print("    Temple A: 10 archana bookings, ₹50,000 donation, Ganapathi Homam")
    print("    Temple B:  5 archana bookings, ₹20,000 donation, Usha Pooja")
    print("    Temple C: 15 archana bookings, ₹1,00,000 donation, Harivarasanam")
    print()


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        try:
            from asyncio import WindowsSelectorEventLoopPolicy
            asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
        except ImportError:
            pass
    asyncio.run(main())
