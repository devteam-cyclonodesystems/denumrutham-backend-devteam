import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.future import select
from app.models.domain import Supplier
from app.modules.inventory.services.inventory_service import InventoryService
from tests.conftest import TEMPLE_ID, TestSessionLocal

@pytest.mark.anyio
async def test_create_and_update_supplier_catalog():
    async with TestSessionLocal() as session:
        # Create a supplier
        sup_payload = {
            "name": "Test Supplier DB Error",
            "contact": "9876543210",
            "email": "test@supplier.com",
            "address": "123 Street",
            "items_supplied": "Oranges (KG) @ ₹80 [Min: 10]",
            "remarks": "Newly Registered"
        }
        
        # In test_routes.py we hit the endpoints
        # Let's test the service layer directly first
        from app.modules.inventory.schemas.inventory import SupplierCreate
        sup_in = SupplierCreate(**sup_payload)
        
        sup = await InventoryService.create_supplier(
            db=session,
            sup_in=sup_in,
            temple_id=str(TEMPLE_ID)
        )
        assert sup.name == "Test Supplier DB Error"
        assert sup.id is not None
        
        # Now update it with item list changes (Proposed price change)
        sup_update_payload = {
            "name": "Test Supplier DB Error",
            "contact": "9876543210",
            "email": "test@supplier.com",
            "address": "123 Street",
            "items_supplied": "Oranges (KG) @ ₹95 [Min: 10]", # Proposed price increase
            "remarks": "Updated via dashboard"
        }
        sup_in_update = SupplierCreate(**sup_update_payload)
        
        updated_sup = await InventoryService.update_supplier(
            db=session,
            supplier_id=sup.id,
            sup_in=sup_in_update,
            temple_id=str(TEMPLE_ID)
        )
        assert updated_sup.name == "Test Supplier DB Error"
