import asyncio
import sys
import os
from uuid import UUID

sys.path.append(os.path.abspath('c:/Denumrutham/backend'))

from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.models.archana import ArchanaCatalog, CatalogStatus

async def populate():
    temple_id = UUID('b03313bc-0d2b-48a4-a537-0e839bbaf4c9')
    
    # Deities
    deity_devi = UUID('97ea5803-7ea9-4645-b8df-ba988197dc62')
    deity_siva = UUID('8c58e726-8e30-47f0-bf23-2d95071ee122')
    deity_ayyappa = UUID('f2fe3c30-b47f-45aa-bbed-165b82c0166c')
    deity_ganapathy = UUID('e48825f3-a1c3-4e94-b6ff-2bb1a1b49f41')
    
    services = [
        {"name": "Bhadrakali Archana", "price": 150.0, "deity_id": deity_devi, "duration_minutes": 5, "remarks": "Daily archana for Malottu Devi"},
        {"name": "Shatru Samhara Pushpanjali", "price": 250.0, "deity_id": deity_devi, "duration_minutes": 10, "remarks": "Special pushpanjali for protection"},
        {"name": "Neyyabhishekam", "price": 350.0, "deity_id": deity_ayyappa, "duration_minutes": 15, "remarks": "Abhishekam with ghee for Sree Dharmasastha"},
        {"name": "Ganapathi Homam", "price": 200.0, "deity_id": deity_ganapathy, "duration_minutes": 20, "remarks": "Morning Homam for Sree Mahaganapathy"},
        {"name": "Pinvilakku", "price": 100.0, "deity_id": deity_siva, "duration_minutes": 5, "remarks": "Back lamp offering for Lord Siva"}
    ]
    
    async with AsyncSessionLocal() as session:
        # Set RLS session context for background/superadmin bypass
        await session.execute(text("SELECT set_config('app.current_temple_id', 'SYSTEM', false)"))
        await session.execute(text("SELECT set_config('app.current_role', 'SUPER_ADMIN', false)"))
        
        for s in services:
            item = ArchanaCatalog(
                temple_id=temple_id,
                name=s["name"],
                price=s["price"],
                deity_id=s["deity_id"],
                duration_minutes=s["duration_minutes"],
                remarks=s["remarks"],
                is_active=True,
                status=CatalogStatus.APPROVED
            )
            session.add(item)
            
        await session.commit()
        print("Mock catalog items added successfully!")

if __name__ == '__main__':
    asyncio.run(populate())
