"""
Inventory Management Service Module

Purpose:
Manages internal temple (Kalavara) inventory and commercial store stock transactions.

Responsibilities:
- Coordinates item procurement, GRNs, and supplier invoice states
- Implements stock reservations for auction listings and POS commerce
- Daily snapshot generation for cost reconciliation

Operational Notes:
- Uses Postgres indices to optimize massive item scans
- Multi-tenant isolated
- Strict non-mutation rules on historical stock ledgers
"""

"""Inventory Service — Items, Suppliers, Invoices, Item Requests with transaction engine."""
import logging
from uuid import UUID
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.domain import (
    InventoryItem, Supplier, InventoryInvoice, InventoryItemRequest,
    InventoryTransaction, InventoryTxnType,
    InventoryMovementType, InventoryStockLedger, InventoryLocation,
    InventoryIssueSession, ProcurementGRN, RitualTemplate, RitualTemplateItem,
    InventoryReconciliation, InventoryIssueStatus, ProcurementStatus,
    StoreProduct, StoreStock, KalavaraStock,
    SupplierPriceHistory, PriceApprovalRequest, InventoryPaymentTransaction
)
from app.schemas.inventory import (
    InventoryItemCreate, SupplierCreate, InvoiceCreate, ItemRequestCreate,
    InventoryLocationCreate, IssueSessionCreate, GRNCreate, RitualTemplateCreate,
    ReconciliationCreate
)
from app.services.transaction_service import TransactionService

logger = logging.getLogger("tms.services.inventory")


class InventoryService:

    # --- Core Engine ---
    @staticmethod
    async def record_movement(
        db: AsyncSession,
        temple_id: UUID,
        item_id: UUID,
        qty_change: float,
        movement_type: InventoryMovementType,
        performed_by: UUID = None,
        location_id: UUID = None,
        reference_type: str = None,
        reference_id: str = None,
        remarks: str = None
    ) -> InventoryStockLedger:
        """🔥 CENTRAL STOCK MOVEMENT ENGINE: Immutable append-only ledgering."""
        # 1. Determine if Item is STORE or KALAVARA
        is_store = False
        item_res = await db.execute(
            select(StoreProduct).filter(StoreProduct.id == item_id, StoreProduct.temple_id == temple_id)
        )
        item = item_res.scalars().first()
        if item:
            is_store = True
        else:
            item_res = await db.execute(
                select(InventoryItem).filter(InventoryItem.id == item_id, InventoryItem.temple_id == temple_id)
            )
            item = item_res.scalars().first()
            if not item:
                logger.error(f"Inventory item/product {item_id} not found for temple {temple_id}")
                raise ValueError("Inventory item not found")

        # 2. Update stock table and version check
        if is_store:
            stock_res = await db.execute(
                select(StoreStock)
                .filter(StoreStock.product_id == item_id, StoreStock.temple_id == temple_id)
                .with_for_update()
            )
            stock = stock_res.scalars().first()
            if not stock:
                stock = StoreStock(
                    temple_id=temple_id,
                    product_id=item_id,
                    quantity=0.0,
                    location_id=location_id,
                    version_number=1
                )
                db.add(stock)
                await db.flush()
            before_stock = stock.quantity
            after_stock = before_stock + qty_change
            stock.quantity = after_stock
            stock.version_number += 1
        else:
            stock_res = await db.execute(
                select(KalavaraStock)
                .filter(KalavaraStock.item_id == item_id, KalavaraStock.temple_id == temple_id)
                .with_for_update()
            )
            stock = stock_res.scalars().first()
            if not stock:
                stock = KalavaraStock(
                    temple_id=temple_id,
                    item_id=item_id,
                    quantity=0.0,
                    location_id=location_id or item.location_id,
                    version_number=1
                )
                db.add(stock)
                await db.flush()
            before_stock = stock.quantity
            after_stock = before_stock + qty_change
            stock.quantity = after_stock
            stock.version_number += 1
            # Update legacy stock column for backward compatibility
            item.stock = after_stock

        # 3. Create Ledger Entry (Audit trail)
        ledger = InventoryStockLedger(
            temple_id=temple_id,
            domain_type="STORE" if is_store else "KALAVARA",
            store_product_id=item_id if is_store else None,
            kalavara_item_id=None if is_store else item_id,
            item_name=item.name,
            location_id=location_id or (stock.location_id if stock else None),
            movement_type=movement_type,
            quantity_change=qty_change,
            before_stock=before_stock,
            after_stock=after_stock,
            reference_type=reference_type,
            reference_id=reference_id,
            performed_by=performed_by,
            remarks=remarks
        )
        db.add(ledger)
        return ledger

    # --- Items ---
    @staticmethod
    async def create_item(
        db: AsyncSession, 
        item_in: InventoryItemCreate, 
        temple_id: str,
        user_id: Optional[UUID] = None,
        username: str = "Admin",
        user_role: str = "SYSTEM"
    ) -> InventoryItem:
        import math
        from fastapi import HTTPException
        
        min_stock_val = item_in.min_stock
        unit_price_val = item_in.unit_price
        
        if math.isnan(min_stock_val) or math.isnan(unit_price_val):
            raise HTTPException(status_code=400, detail="Values cannot be NaN")
            
        if min_stock_val < 1 or min_stock_val > 100000:
            raise HTTPException(status_code=400, detail="Minimum Quantity Alert must be between 1 and 100,000")
            
        if unit_price_val < 0:
            raise HTTPException(status_code=400, detail="Unit price cannot be negative")

        tid = UUID(str(temple_id))
        item = InventoryItem(
            temple_id=tid,
            name=item_in.name,
            stock=item_in.qty,
            category=item_in.category,
            unit=item_in.unit,
            min_stock=item_in.min_stock,
            unit_price=item_in.unit_price,
            purchase_mode=item_in.purchase_mode,
            remarks=item_in.remarks,
        )
        db.add(item)
        await db.flush()

        # Initial stock record
        if item_in.qty > 0:
            await InventoryService.record_movement(
                db=db,
                temple_id=tid,
                item_id=item.id,
                qty_change=item_in.qty,
                movement_type=InventoryMovementType.ADJUSTMENT,
                remarks="Initial stock entry"
            )

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=user_role,
            module_name="INVENTORY",
            action="ITEM_CREATED",
            action_type="CREATE",
            entity_id=str(item.id),
            new_value={"name": item.name, "category": item.category, "stock": item.stock},
            details=f"Inventory item '{item.name}' created with initial stock {item.stock}."
        )

        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def get_items(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 500):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryItem)
            .filter(InventoryItem.temple_id == tid, InventoryItem.is_archived == False)
            .order_by(InventoryItem.name)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    # --- Suppliers ---
    @staticmethod
    def parse_supplier_item(token: str) -> dict:
        """Parses a serialized supplier item token into components.
        Supports:
        - Legacy: Rice (KG) @ ₹100
        - Legacy Alternate: Rice (KG) @ ₹100 [Alert: 15]
        - New: Rice (KG) @ ₹100 [Min: 15]
        """
        import re
        # Regex accepts any legacy or new variant
        pattern = r"^(.+?)\s*\((.+?)\)\s*@\s*₹?\s*([\d.]+)(?:\s*\[(?:Min|Alert):\s*([\d.]+)\])?$"
        match = re.match(pattern, token.strip(), re.IGNORECASE)
        if match:
            try:
                name = match.group(1).strip()
                unit = match.group(2).strip()
                price = float(match.group(3).strip())
                min_stock = float(match.group(4).strip()) if match.group(4) else 10.0
                
                 # Rule 4: Validation limits (1 to 100,000) and scientific notation rejection
                raw_min = match.group(4).strip() if match.group(4) else "10"
                if re.search(r'[eE]', raw_min) or re.search(r'[eE]', match.group(3).strip()):
                    logger.warning(f"Rejected scientific notation in supplier item: {token}")
                    return {"valid": False}
                    
                import math
                if math.isnan(min_stock) or math.isnan(price):
                    logger.warning(f"Rejected NaN value in supplier item: {token}")
                    return {"valid": False}
                    
                if min_stock < 1 or min_stock > 100000 or price < 0:
                    logger.warning(f"Rejected boundary violation for supplier item: {token}")
                    return {"valid": False}
                
                return {
                    "name": name,
                    "unit": unit,
                    "price": price,
                    "min_stock": min_stock,
                    "valid": True
                }
            except Exception as e:
                logger.warning(f"Error parsing supplier item token '{token}': {e}")
                return {"valid": False}
        else:
            logger.warning(f"Malformed supplier item token pattern '{token}'")
            return {"valid": False}

    @staticmethod
    def serialize_supplier_item(name: str, unit: str, price: float, min_stock: float) -> str:
        """Serializes supplier item details into standard token format [Min: X]"""
        return f"{name} ({unit}) @ ₹{price} [Min: {min_stock}]"

    @staticmethod
    async def create_supplier(
        db: AsyncSession, sup_in: SupplierCreate, temple_id: str,
        user_id: UUID = None, username: str = "Admin", user_role: str = "SYSTEM"
    ) -> Supplier:
        tid = UUID(str(temple_id))
        count_result = await db.execute(
            select(func.count(Supplier.id)).filter(Supplier.temple_id == tid)
        )
        count = count_result.scalar() or 0
        sup_code = f"TSUP-{str(count + 1).zfill(3)}"

        sup = Supplier(
            temple_id=tid,
            sup_code=sup_code,
            name=sup_in.name,
            contact=sup_in.contact,
            alt_contact=sup_in.alt_contact,
            email=sup_in.email,
            address=sup_in.address,
            items_supplied=sup_in.items_supplied,
            last_delivery=sup_in.last_delivery,
            remarks=sup_in.remarks,
        )
        db.add(sup)
        await db.flush()
       
        # Sync Item to Kalavara
        if sup_in.items_supplied and "store module" not in (sup_in.remarks or "").lower():
            for part in sup_in.items_supplied.split(','):
                res = InventoryService.parse_supplier_item(part)
                if not res.get("valid"):
                    continue # Warning already logged
                
                name = res["name"]
                unit = res["unit"]
                price = res["price"]
                min_stock_val = res["min_stock"]
                
                item_res = await db.execute(
                    select(InventoryItem).filter(
                        func.lower(InventoryItem.name) == func.lower(name),
                        InventoryItem.temple_id == tid
                    ).with_for_update()
                )
                existing_item = item_res.scalars().first()
                
                if not existing_item:
                    # Sync creates it: Rule 3 tracking
                    new_inv_item = InventoryItem(
                        temple_id=tid,
                        name=name,
                        category="Supplier Item",
                        unit=unit,
                        min_stock=min_stock_val,
                        stock=0.0,
                        unit_price=0.0,  # Initialize to 0.0 so price needs approval
                        remarks="Auto-created from Supplier Catalog",
                        created_from_supplier=True,
                        min_stock_source="SUPPLIER"
                    )
                    db.add(new_inv_item)
                    await db.flush()
                    existing_item = new_inv_item
                else:
                    # Item exists!
                    # Rule 2: Only overwrite threshold if not manually modified
                    if existing_item.created_from_supplier and existing_item.min_stock_source == "SUPPLIER":
                        existing_item.min_stock = min_stock_val
                
                # Rule 13: Price change detection engine - ANY PRICE CHANGE -> PENDING_APPROVAL
                if existing_item.unit_price != price:
                    old_price = existing_item.unit_price
                    price_diff = price - (old_price or 0.0)
                    pct_change = ((price - old_price) / old_price * 100) if old_price and old_price > 0 else 0.0
                    
                    app_type = "WARNING" if pct_change <= 100.0 else "CRITICAL"
                    
                    from app.models.domain import PriceApprovalRequest
                    existing_req_res = await db.execute(
                        select(PriceApprovalRequest).filter(
                            PriceApprovalRequest.inventory_item_id == existing_item.id,
                            PriceApprovalRequest.new_price == price,
                            PriceApprovalRequest.status == "PENDING_APPROVAL"
                        )
                    )
                    if not existing_req_res.scalars().first():
                        price_req = PriceApprovalRequest(
                            temple_id=tid,
                            supplier_id=sup.id,
                            inventory_item_id=existing_item.id,
                            old_price=old_price,
                            new_price=price,
                            change_percentage=pct_change,
                            requested_by=username,
                            requested_by_user_id=user_id,
                            requested_by_role=user_role,
                            status="PENDING_APPROVAL",
                            approval_type=app_type,
                            reason=f"Supplier sync price change of {pct_change:.2f}%",
                            reason_notes=f"Price change requested from supplier sync. Old price: {old_price}, Proposed price: {price}"
                        )
                        db.add(price_req)
                        
                        if app_type == "CRITICAL":
                            logger.error(
                                f"[CRITICAL PROCUREMENT ALERT] Supplier {sup_in.name} requested price increase "
                                f"of {pct_change:.2f}% (from {old_price} to {price}) for item {name}."
                            )
                            from app.modules.temple_management.services.notification_service import NotificationService
                            await NotificationService.create_notification(
                                db,
                                temple_id=tid,
                                title="CRITICAL PROCUREMENT ALERT",
                                message=f"[CRITICAL PROCUREMENT ALERT] Supplier {sup_in.name} requested price increase of {pct_change:.2f}% (from {old_price} to {price}) for item {name}.",
                                role="TEMPLE_MANAGER"
                            )
                            await NotificationService.create_notification(
                                db,
                                temple_id=tid,
                                title="CRITICAL PROCUREMENT ALERT",
                                message=f"[CRITICAL PROCUREMENT ALERT] Supplier {sup_in.name} requested price increase of {pct_change:.2f}% (from {old_price} to {price}) for item {name}.",
                                role="TEMPLE_ADMIN"
                            )
                
                existing_item.unit = unit
                existing_item.supplier_id = sup.id

        # Sync Item to Store Products if it is a store module supplier
        if sup_in.items_supplied and "store module" in (sup_in.remarks or "").lower():
            from app.models.domain import StoreProduct, StoreStock
            for part in sup_in.items_supplied.split(','):
                res = InventoryService.parse_supplier_item(part)
                if not res.get("valid"):
                    continue
                
                name = res["name"]
                unit = res["unit"]
                price = res["price"]
                
                prod_res = await db.execute(
                    select(StoreProduct).filter(
                        func.lower(StoreProduct.name) == func.lower(name),
                        StoreProduct.temple_id == tid
                    ).with_for_update()
                )
                existing_product = prod_res.scalars().first()
                
                if not existing_product:
                    new_prod = StoreProduct(
                        temple_id=tid,
                        name=name,
                        category="Other",
                        unit=unit,
                        unit_price=price,
                        supplier_id=sup.id,
                        is_active=True,
                        is_archived=False
                    )
                    db.add(new_prod)
                    await db.flush()
                    
                    new_stock = StoreStock(
                        temple_id=tid,
                        product_id=new_prod.id,
                        quantity=0.0,
                        version_number=1
                    )
                    db.add(new_stock)
                    await db.flush()
                else:
                    existing_product.unit_price = price
                    existing_product.unit = unit
                    existing_product.supplier_id = sup.id

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=user_role,
            module_name="INVENTORY",
            action="SUPPLIER_CREATED",
            action_type="CREATE",
            entity_id=str(sup.id),
            new_value={"name": sup.name, "sup_code": sup.sup_code},
            details=f"Supplier '{sup.name}' created with code {sup.sup_code}."
        )

        await db.commit()
        await db.refresh(sup)
        return sup

    @staticmethod
    async def update_supplier(
        db: AsyncSession, supplier_id: UUID, sup_in: SupplierCreate, temple_id: str,
        user_id: UUID = None, username: str = "Admin", user_role: str = "SYSTEM"
    ) -> Supplier:
        from app.models.domain import Supplier, SupplierPriceHistory
        tid = UUID(str(temple_id))
        logger.info(f"Updating supplier {supplier_id} for temple {tid}")
       
        result = await db.execute(select(Supplier).filter(Supplier.id == supplier_id, Supplier.temple_id == tid))
        sup = result.scalars().first()
        if not sup:
            logger.warning(f"Supplier {supplier_id} not found")
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Supplier not found")
       
        # Track price changes
        old_items = {}
        if sup.items_supplied:
            for part in sup.items_supplied.split(','):
                res = InventoryService.parse_supplier_item(part)
                if res.get("valid"):
                    old_items[res["name"]] = res["price"]

        new_items = {}
        if sup_in.items_supplied:
            for part in sup_in.items_supplied.split(','):
                res = InventoryService.parse_supplier_item(part)
                if res.get("valid"):
                    new_items[res["name"]] = res

        # Record changes and Sync to Kalavara
        for name, data in new_items.items():
            new_price = data["price"]
            unit = data["unit"]
            min_stock_val = data["min_stock"]
            old_price = old_items.get(name)
            
            # Sync Item to Kalavara or Store Products
            if "store module" not in (sup_in.remarks or "").lower():
                item_res = await db.execute(
                    select(InventoryItem).filter(
                        func.lower(InventoryItem.name) == func.lower(name),
                        InventoryItem.temple_id == tid
                    ).with_for_update()
                )
                existing_item = item_res.scalars().first()
                
                if not existing_item:
                    # New item created: Rule 3 tracking
                    new_inv_item = InventoryItem(
                        temple_id=tid,
                        name=name,
                        category="Supplier Item",
                        unit=unit,
                        min_stock=min_stock_val,
                        stock=0.0,
                        unit_price=0.0, # Rule: New items start at 0 to force approval
                        remarks="Auto-created from Supplier Catalog",
                        created_from_supplier=True,
                        min_stock_source="SUPPLIER"
                    )
                    db.add(new_inv_item)
                    await db.flush()
                    existing_item = new_inv_item
                else:
                    # Item exists!
                    # Rule 2: Only overwrite threshold if not manually modified
                    if existing_item.created_from_supplier and existing_item.min_stock_source == "SUPPLIER":
                        existing_item.min_stock = min_stock_val
                    
                    # Rule 13: Price change detection engine - ANY PRICE CHANGE -> PENDING_APPROVAL
                    if existing_item.unit_price != new_price:
                        old_price = existing_item.unit_price
                        price = new_price
                        price_diff = price - (old_price or 0.0)
                        pct_change = ((price - old_price) / old_price * 100) if old_price and old_price > 0 else 0.0
                        
                        # PENDING_APPROVAL rules
                        app_type = "WARNING" if pct_change <= 100.0 else "CRITICAL"
                        
                        from app.models.domain import PriceApprovalRequest
                        existing_req_res = await db.execute(
                            select(PriceApprovalRequest).filter(
                                PriceApprovalRequest.inventory_item_id == existing_item.id,
                                PriceApprovalRequest.new_price == price,
                                PriceApprovalRequest.status == "PENDING_APPROVAL"
                            )
                        )
                        if not existing_req_res.scalars().first():
                            price_req = PriceApprovalRequest(
                                temple_id=tid,
                                supplier_id=supplier_id,
                                inventory_item_id=existing_item.id,
                                old_price=old_price,
                                new_price=price,
                                change_percentage=pct_change,
                                requested_by=username,
                                requested_by_user_id=user_id,
                                requested_by_role=user_role,
                                status="PENDING_APPROVAL",
                                approval_type=app_type,
                                reason=f"Supplier sync price increase of {pct_change:.2f}%",
                                reason_notes=f"Price change requested from supplier sync. Old price: {old_price}, Proposed price: {price}"
                            )
                            db.add(price_req)
                            
                            if app_type == "CRITICAL":
                                logger.error(
                                    f"[CRITICAL PROCUREMENT ALERT] Supplier {sup_in.name} requested price increase "
                                    f"of {pct_change:.2f}% (from {old_price} to {price}) for item {name}."
                                )
                                from app.modules.temple_management.services.notification_service import NotificationService
                                await NotificationService.create_notification(
                                    db,
                                    temple_id=tid,
                                    title="CRITICAL PROCUREMENT ALERT",
                                    message=f"[CRITICAL PROCUREMENT ALERT] Supplier {sup_in.name} requested price increase of {pct_change:.2f}% (from {old_price} to {price}) for item {name}.",
                                    role="TEMPLE_MANAGER"
                                )
                                await NotificationService.create_notification(
                                    db,
                                    temple_id=tid,
                                    title="CRITICAL PROCUREMENT ALERT",
                                    message=f"[CRITICAL PROCUREMENT ALERT] Supplier {sup_in.name} requested price increase of {pct_change:.2f}% (from {old_price} to {price}) for item {name}.",
                                    role="TEMPLE_ADMIN"
                                )
                        
                    existing_item.unit = unit
                    existing_item.supplier_id = supplier_id
            else:
                # If store module supplier, we sync to StoreProduct!
                from app.models.domain import StoreProduct, StoreStock
                prod_res = await db.execute(
                    select(StoreProduct).filter(
                        func.lower(StoreProduct.name) == func.lower(name),
                        StoreProduct.temple_id == tid
                    ).with_for_update()
                )
                existing_product = prod_res.scalars().first()
                if not existing_product:
                    new_prod = StoreProduct(
                        temple_id=tid,
                        name=name,
                        category="Other",
                        unit=unit,
                        unit_price=new_price,
                        supplier_id=supplier_id,
                        is_active=True,
                        is_archived=False
                    )
                    db.add(new_prod)
                    await db.flush()
                    
                    new_stock = StoreStock(
                        temple_id=tid,
                        product_id=new_prod.id,
                        quantity=0.0,
                        version_number=1
                    )
                    db.add(new_stock)
                    await db.flush()
                else:
                    existing_product.unit_price = new_price
                    existing_product.unit = unit
                    existing_product.supplier_id = supplier_id

                # If store module supplier, we still record history if price changed
                if old_price is not None and old_price != new_price:
                    price_diff = new_price - old_price
                    pct_change = ((new_price - old_price) / old_price * 100) if old_price > 0 else 0.0
                    history = SupplierPriceHistory(
                        temple_id=tid,
                        supplier_id=supplier_id,
                        item_name=name,
                        old_price=old_price,
                        new_price=new_price,
                        changed_by=username,
                        supplier_name=sup_in.name,
                        price_difference=price_diff,
                        percentage_change=pct_change,
                        modified_by_id=str(user_id) if user_id else "SYSTEM",
                        modified_by_name=username,
                        reason="Supplier price updated in catalog",
                        source="Supplier Update"
                    )
                    db.add(history)
       
        sup.name = sup_in.name
        sup.contact = sup_in.contact
        sup.alt_contact = sup_in.alt_contact
        sup.email = sup_in.email
        sup.address = sup_in.address
        sup.items_supplied = sup_in.items_supplied
        sup.remarks = sup_in.remarks
       
        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=user_role,
            module_name="INVENTORY",
            action="SUPPLIER_UPDATED",
            action_type="UPDATE",
            entity_id=str(sup.id),
            new_value={"name": sup.name, "sup_code": sup.sup_code},
            details=f"Supplier '{sup.name}' updated."
        )

        await db.commit()
        await db.refresh(sup)
        logger.info(f"Supplier {supplier_id} updated successfully")
        return sup

    @staticmethod
    async def get_supplier_history(db: AsyncSession, supplier_id: UUID, temple_id: str):
        from app.models.domain import SupplierPriceHistory
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(SupplierPriceHistory)
            .filter(SupplierPriceHistory.supplier_id == supplier_id, SupplierPriceHistory.temple_id == tid)
            .order_by(SupplierPriceHistory.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def get_suppliers(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(Supplier)
            .filter(Supplier.temple_id == tid)
            .order_by(Supplier.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def update_item(
        db: AsyncSession, item_id: UUID, item_in: dict, temple_id: str,
        user_id: UUID = None, username: str = "Admin", user_role: str = "SYSTEM"
    ) -> InventoryItem:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryItem)
            .filter(InventoryItem.id == item_id, InventoryItem.temple_id == tid)
            .with_for_update()
        )
        item = result.scalars().first()
        if not item:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Item not found")

        # Concurrency check (optimistic locking)
        expected_version = item_in.get("version")
        if expected_version is not None and item.version != expected_version:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=409,
                detail="This inventory item was modified by another user. Please refresh and try again."
            )
        item.version = (item.version or 1) + 1

        import math
        from fastapi import HTTPException
        
        # Enforce validation Rules (Rule 4)
        new_price = item_in.get("unit_price")
        if new_price is not None:
            if math.isnan(new_price):
                raise HTTPException(status_code=400, detail="Price cannot be NaN")
            if new_price < 0:
                raise HTTPException(status_code=400, detail="Price cannot be negative")
                
        new_min_stock = item_in.get("min_stock")
        if new_min_stock is not None:
            if math.isnan(new_min_stock):
                raise HTTPException(status_code=400, detail="Minimum Quantity Alert cannot be NaN")
            if new_min_stock < 1 or new_min_stock > 100000:
                raise HTTPException(status_code=400, detail="Minimum Quantity Alert must be between 1 and 100,000")

        # 1. Price Volatility Governance
        new_price = item_in.get("unit_price")
        if new_price is not None and new_price != item.unit_price:
            old_price = item.unit_price
            price_diff = new_price - old_price
            pct_change = ((new_price - old_price) / old_price * 100) if old_price and old_price > 0 else 0.0
            
            supplier_id = item.supplier_id
            app_type = "WARNING" if pct_change <= 100.0 else "CRITICAL"
            
            from app.models.domain import PriceApprovalRequest
            existing_req_res = await db.execute(
                select(PriceApprovalRequest).filter(
                    PriceApprovalRequest.inventory_item_id == item.id,
                    PriceApprovalRequest.new_price == new_price,
                    PriceApprovalRequest.status == "PENDING_APPROVAL"
                )
            )
            if not existing_req_res.scalars().first():
                price_req = PriceApprovalRequest(
                    temple_id=tid,
                    supplier_id=supplier_id,
                    inventory_item_id=item.id,
                    old_price=old_price,
                    new_price=new_price,
                    change_percentage=pct_change,
                    requested_by=username,
                    requested_by_user_id=user_id,
                    requested_by_role=user_role,
                    status="PENDING_APPROVAL",
                    approval_type=app_type,
                    reason=f"Manual price update of {pct_change:.2f}%",
                    reason_notes=item_in.get("remarks") or "Manual price update requested."
                )
                db.add(price_req)
                
                if app_type == "CRITICAL":
                    logger.error(
                        f"[CRITICAL PROCUREMENT ALERT] Manual request for price increase "
                        f"of {pct_change:.2f}% (from {old_price} to {new_price}) for item {item.name}."
                    )
                    from app.modules.temple_management.services.notification_service import NotificationService
                    await NotificationService.create_notification(
                        db,
                        temple_id=tid,
                        title="CRITICAL PROCUREMENT ALERT",
                        message=f"[CRITICAL PROCUREMENT ALERT] Manual request for price increase of {pct_change:.2f}% (from {old_price} to {new_price}) for item {item.name}.",
                        role="TEMPLE_MANAGER"
                    )
                    await NotificationService.create_notification(
                        db,
                        temple_id=tid,
                        title="CRITICAL PROCUREMENT ALERT",
                        message=f"[CRITICAL PROCUREMENT ALERT] Manual request for price increase of {pct_change:.2f}% (from {old_price} to {new_price}) for item {item.name}.",
                        role="TEMPLE_ADMIN"
                    )

        # 2. Threshold Governance
        new_min_stock = item_in.get("min_stock")
        if new_min_stock is not None:
            # Rule 3: Mark as MANUAL threshold
            item.min_stock = new_min_stock
            item.min_stock_source = "MANUAL"

        if "category" in item_in:
            item.category = item_in["category"]
        if "unit" in item_in:
            item.unit = item_in["unit"]
        if "remarks" in item_in:
            item.remarks = item_in["remarks"]

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=user_role,
            module_name="INVENTORY",
            action="ITEM_UPDATED",
            action_type="UPDATE",
            entity_id=str(item.id),
            new_value={"name": item.name, "category": item.category, "stock": item.stock, "min_stock": item.min_stock, "unit_price": item.unit_price},
            details=f"Inventory item '{item.name}' updated."
        )

        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def get_item_price_history(db: AsyncSession, item_id: UUID, temple_id: str) -> dict:
        tid = UUID(str(temple_id))
        item_res = await db.execute(
            select(InventoryItem).filter(InventoryItem.id == item_id, InventoryItem.temple_id == tid)
        )
        item = item_res.scalars().first()
        if not item:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Item not found")

        history_res = await db.execute(
            select(SupplierPriceHistory)
            .filter(
                func.lower(SupplierPriceHistory.item_name) == func.lower(item.name),
                SupplierPriceHistory.temple_id == tid
            )
            .order_by(SupplierPriceHistory.created_at.desc())
        )
        history_list = history_res.scalars().all()

        # Volatility Analytics (Rule 14)
        total_changes = len(history_list)
        last_change_date = None
        highest_price = item.unit_price
        lowest_price = item.unit_price
        avg_price = item.unit_price

        prices = [item.unit_price]
        for h in history_list:
            if h.new_price is not None:
                prices.append(h.new_price)
            if h.old_price is not None:
                prices.append(h.old_price)

        if total_changes > 0:
            last_change_date = history_list[0].created_at.isoformat()
            highest_price = max(prices)
            lowest_price = min(prices)
            avg_price = sum(prices) / len(prices)

        trend = "STABLE"
        if len(history_list) >= 1:
            latest = history_list[0].new_price
            prev = history_list[0].old_price if history_list[0].old_price is not None else latest
            if latest > prev:
                trend = "INCREASING"
            elif latest < prev:
                trend = "DECREASING"

        formatted_history = []
        for h in history_list:
            formatted_history.append({
                "date": h.created_at.strftime("%d-%b-%Y"),
                "timestamp": h.created_at.isoformat(),
                "old_price": h.old_price,
                "new_price": h.new_price,
                "difference": h.price_difference,
                "percentage_change": h.percentage_change,
                "updated_by": h.modified_by_name or h.changed_by,
                "supplier": h.supplier_name or "Manual Edit",
                "source": h.source,
                "reason": h.reason or ""
            })

        return {
            "item_name": item.name,
            "current_price": item.unit_price,
            "analytics": {
                "last_price_change_date": last_change_date,
                "total_price_changes": total_changes,
                "average_purchase_price": avg_price,
                "highest_historical_price": highest_price,
                "lowest_historical_price": lowest_price,
                "current_price_trend": trend
            },
            "history": formatted_history
        }

    @staticmethod
    async def create_invoice(
        db: AsyncSession, inv_in: InvoiceCreate, temple_id: str, created_by: str = "Admin", user_id: UUID = None
    ) -> dict:
        """🔥 REFACTORED: Structured Accounts Payable & Payment Ledger Creation."""
        from decimal import Decimal
        tid = UUID(str(temple_id))

        # 1. Generate References
        ref = inv_in.ref_number
        if not ref:
            count_result = await db.execute(
                select(func.count(InventoryInvoice.id)).filter(InventoryInvoice.temple_id == tid)
            )
            count = count_result.scalar() or 0
            from datetime import datetime
            now = datetime.utcnow()
            mm = str(now.month).zfill(2)
            yy = str(now.year)[-2:]
            ref = f"Inv{str(count + 1).zfill(3)}/{mm}{yy}"

        # Resolve real user UUID from username/email/sub
        real_user_uuid = None
        if user_id:
            try:
                if isinstance(user_id, UUID):
                    real_user_uuid = user_id
                else:
                    real_user_uuid = UUID(str(user_id))
            except ValueError:
                from app.models.domain import User
                user_res = await db.execute(
                    select(User).filter(
                        (User.user_id == str(user_id)) |
                        (User.email == str(user_id))
                    )
                )
                user_obj = user_res.scalars().first()
                if user_obj:
                    real_user_uuid = user_obj.id

        if not real_user_uuid:
            from app.models.domain import User
            user_res = await db.execute(select(User).filter(User.temple_id == tid))
            user_obj = user_res.scalars().first()
            if user_obj:
                real_user_uuid = user_obj.id
            else:
                user_res = await db.execute(select(User))
                user_obj = user_res.scalars().first()
                if user_obj:
                    real_user_uuid = user_obj.id

        # Resolve supplier ID
        sup_res = await db.execute(select(Supplier).filter(Supplier.name == inv_in.supplier_name, Supplier.temple_id == tid))
        supplier = sup_res.scalars().first()
        supplier_id = supplier.id if supplier else None
        if not supplier_id:
            sup_fallback_res = await db.execute(select(Supplier).filter(Supplier.temple_id == tid))
            sup_fallback = sup_fallback_res.scalars().first()
            if sup_fallback:
                supplier_id = sup_fallback.id

        # Derive initial payment totals and payment status
        total_amount = Decimal(str(inv_in.amount))
        if total_amount < 0:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invoice amount cannot be negative")

        payment_status = (inv_in.payment_status or "PAY_LATER").upper()
        if payment_status not in ("FULL_PAYMENT", "PARTIAL_PAYMENT", "PAY_LATER"):
            payment_status = "PAY_LATER"

        paid_amount = Decimal("0.00")
        if payment_status == "FULL_PAYMENT":
            paid_amount = total_amount
        elif payment_status == "PARTIAL_PAYMENT":
            paid_amount = Decimal(str(inv_in.paid_amount or 0.00))

        if paid_amount < 0:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Paid amount cannot be negative")
        if paid_amount > total_amount:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Paid amount cannot exceed invoice total")

        balance_due = total_amount - paid_amount

        # System-Derived status logic
        if balance_due == total_amount:
            payment_status = "PAY_LATER"
        elif balance_due > 0 and paid_amount > 0:
            payment_status = "PARTIAL_PAYMENT"
        elif balance_due == 0:
            payment_status = "FULL_PAYMENT"

        # 2. Create Invoice
        invoice = InventoryInvoice(
            temple_id=tid,
            supplier_id=supplier_id,
            ref_number=ref,
            supplier_name=inv_in.supplier_name,
            date=inv_in.date or str(import_date()),
            items_summary=inv_in.items_summary,
            amount=inv_in.amount,
            order_mode=inv_in.order_mode,
            payment_mode=inv_in.payment_mode,
            remarks=inv_in.remarks,
            status=inv_in.status.upper() if inv_in.status else "COMPLETED",
            items_data=inv_in.items,  # Save structured lines
            created_by=created_by,
            created_by_user_id=real_user_uuid,
            target_domain=inv_in.target_domain,
            payment_status=payment_status,
            total_paid_amount=paid_amount,
            balance_due=balance_due,
            last_payment_date=utcnow() if paid_amount > 0 else None,
            payment_completed_at=utcnow() if payment_status == "FULL_PAYMENT" else None
        )
        db.add(invoice)
        await db.flush()

        # If it's not pending delivery and paid_amount > 0, create a payment transaction record
        if invoice.status.upper() != "PENDING" and paid_amount > 0:
            clean_method = (inv_in.payment_mode or "CASH").upper().replace(" ", "_").replace("-", "_")
            if clean_method not in ('CASH', 'UPI', 'CARD', 'BANK_TRANSFER', 'CHEQUE'):
                clean_method = 'CASH'
            tx = InventoryPaymentTransaction(
                temple_id=tid,
                invoice_id=invoice.id,
                amount=paid_amount,
                payment_method=clean_method,
                payment_reference=inv_in.payment_reference,
                transaction_status='COMPLETED',
                notes=inv_in.remarks or "Initial invoice payment",
                created_by_user_id=real_user_uuid
            )
            db.add(tx)

        if invoice.status.upper() == "PENDING":
            # Force PENDING invoice payment state to PAY_LATER with 0 initial payments
            invoice.payment_status = "PAY_LATER"
            invoice.total_paid_amount = Decimal("0.00")
            invoice.balance_due = total_amount
            invoice.last_payment_date = None
            invoice.payment_completed_at = None

            # Add Audit log
            from app.modules.audit.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=tid,
                user_id=real_user_uuid,
                role=None,
                module_name="INVENTORY",
                action="INVOICE_CREATED",
                action_type="CREATE",
                entity_id=str(invoice.id),
                new_value={"ref_number": invoice.ref_number, "amount": float(invoice.amount), "status": invoice.status},
                details=f"Procurement invoice {invoice.ref_number} created with amount ₹{invoice.amount}."
            )

            await db.commit()
            await db.refresh(invoice)
            return {
                "id": invoice.id,
                "temple_id": invoice.temple_id,
                "supplier_id": invoice.supplier_id,
                "ref_number": invoice.ref_number,
                "supplier_name": invoice.supplier_name,
                "date": invoice.date,
                "items_summary": invoice.items_summary,
                "amount": invoice.amount,
                "order_mode": invoice.order_mode,
                "payment_mode": invoice.payment_mode,
                "remarks": invoice.remarks,
                "status": invoice.status,
                "payment_status": invoice.payment_status,
                "total_paid_amount": invoice.total_paid_amount,
                "balance_due": invoice.balance_due,
                "last_payment_date": invoice.last_payment_date,
                "payment_completed_at": invoice.payment_completed_at,
                "items_data": invoice.items_data,
                "created_by": invoice.created_by,
                "created_by_user_id": invoice.created_by_user_id,
                "created_at": invoice.created_at,
                "updated_at": invoice.updated_at,
                "grn_code": None,
                "grn_created_at": None,
                "target_domain": invoice.target_domain,
                "payment_history": []
            }

        # 3. Create GRN (Enterprise Layer)
        sup_res = await db.execute(select(Supplier).filter(Supplier.name == inv_in.supplier_name, Supplier.temple_id == tid))
        supplier = sup_res.scalars().first()
       
        supplier_id = supplier.id if supplier else None
        if not supplier_id:
            sup_fallback_res = await db.execute(select(Supplier).filter(Supplier.temple_id == tid))
            sup_fallback = sup_fallback_res.scalars().first()
            if sup_fallback:
                supplier_id = sup_fallback.id
       
        grn = ProcurementGRN(
            temple_id=tid,
            grn_code=f"GRN-{ref}",
            supplier_id=supplier_id,
            invoice_number=ref,
            total_amount=inv_in.amount,
            received_by=real_user_uuid,
            status=ProcurementStatus.COMPLETED,
            remarks=f"Generated from Invoice {ref}",
            target_domain=inv_in.target_domain
        )
        db.add(grn)

        # 4. Process line items via StockMovementEngine
        for line in inv_in.items:
            item_id = line.get("item_id")
            qty = line.get("qty", 0)
            if item_id and qty > 0:
                await InventoryService.record_movement(
                    db=db,
                    temple_id=tid,
                    item_id=UUID(str(item_id)),
                    qty_change=float(qty),
                    movement_type=InventoryMovementType.PURCHASE,
                    performed_by=real_user_uuid,
                    reference_type="GRN",
                    reference_id=grn.grn_code,
                    remarks=f"Purchase via Invoice {ref}"
                )

        # 5. Financial Transaction
        if inv_in.amount > 0:
            await TransactionService.create_transaction(
                db=db,
                temple_id=temple_id,
                txn_type="expense",
                category="purchase",
                amount=inv_in.amount,
                description=f"Purchase Invoice {ref} - {inv_in.supplier_name}",
                reference_id=ref,
                source="system",
            )

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=real_user_uuid,
            role=None,
            module_name="INVENTORY",
            action="INVOICE_CREATED",
            action_type="CREATE",
            entity_id=str(invoice.id),
            new_value={"ref_number": invoice.ref_number, "amount": float(invoice.amount), "status": invoice.status},
            details=f"Procurement invoice {invoice.ref_number} created with amount ₹{invoice.amount}."
        )
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=real_user_uuid,
            role=None,
            module_name="INVENTORY",
            action="GRN_CREATED",
            action_type="CREATE",
            entity_id=str(grn.id),
            new_value={"grn_code": grn.grn_code, "invoice_number": grn.invoice_number},
            details=f"Goods Receipt Note {grn.grn_code} generated for invoice {grn.invoice_number}."
        )

        await db.commit()
        await db.refresh(invoice)
        await db.refresh(grn)
        return {
            "id": invoice.id,
            "temple_id": invoice.temple_id,
            "supplier_id": invoice.supplier_id,
            "ref_number": invoice.ref_number,
            "supplier_name": invoice.supplier_name,
            "date": invoice.date,
            "items_summary": invoice.items_summary,
            "amount": invoice.amount,
            "order_mode": invoice.order_mode,
            "payment_mode": invoice.payment_mode,
            "remarks": invoice.remarks,
            "status": invoice.status,
            "payment_status": invoice.payment_status,
            "total_paid_amount": invoice.total_paid_amount,
            "balance_due": invoice.balance_due,
            "last_payment_date": invoice.last_payment_date,
            "payment_completed_at": invoice.payment_completed_at,
            "items_data": invoice.items_data,
            "created_by": invoice.created_by,
            "created_by_user_id": invoice.created_by_user_id,
            "created_at": invoice.created_at,
            "updated_at": invoice.updated_at,
            "grn_code": grn.grn_code if 'grn' in locals() else None,
            "grn_created_at": grn.created_at if 'grn' in locals() else None,
            "target_domain": invoice.target_domain,
            "payment_history": [tx] if (paid_amount > 0 and 'tx' in locals()) else []
        }

    @staticmethod
    async def get_invoices(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 500):
        from app.models.domain import ProcurementGRN
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryInvoice, ProcurementGRN)
            .outerjoin(ProcurementGRN, ProcurementGRN.invoice_number == InventoryInvoice.ref_number)
            .filter(InventoryInvoice.temple_id == tid)
            .order_by(InventoryInvoice.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
       
        all_rows = result.all()
        invoice_ids = [row[0].id for row in all_rows]

        txs_map = {}
        if invoice_ids:
            tx_res = await db.execute(
                select(InventoryPaymentTransaction)
                .filter(InventoryPaymentTransaction.invoice_id.in_(invoice_ids))
                .order_by(InventoryPaymentTransaction.payment_date.asc())
            )
            for tx in tx_res.scalars().all():
                txs_map.setdefault(tx.invoice_id, []).append(tx)

        invoices_with_grn = []
        for inv, grn in all_rows:
            invoices_with_grn.append({
                "id": inv.id,
                "temple_id": inv.temple_id,
                "supplier_id": inv.supplier_id,
                "ref_number": inv.ref_number,
                "supplier_name": inv.supplier_name,
                "date": inv.date,
                "items_summary": inv.items_summary,
                "amount": inv.amount,
                "order_mode": inv.order_mode,
                "payment_mode": inv.payment_mode,
                "remarks": inv.remarks,
                "status": inv.status,
                "payment_status": inv.payment_status,
                "total_paid_amount": inv.total_paid_amount,
                "balance_due": inv.balance_due,
                "last_payment_date": inv.last_payment_date,
                "payment_completed_at": inv.payment_completed_at,
                "items_data": inv.items_data,
                "created_by": inv.created_by,
                "created_by_user_id": inv.created_by_user_id,
                "created_at": inv.created_at,
                "updated_at": inv.updated_at,
                "grn_code": grn.grn_code if grn else None,
                "grn_created_at": grn.created_at if grn else None,
                "target_domain": inv.target_domain,
                "payment_history": txs_map.get(inv.id, [])
            })
        return invoices_with_grn

    @staticmethod
    async def complete_delivery(db: AsyncSession, invoice_id: UUID, temple_id: str, user_id: UUID = None, delivery_in = None) -> dict:
        from app.models.domain import Supplier, ProcurementGRN, InventoryMovementType, ProcurementStatus, InventoryPaymentTransaction
        from app.services.transaction_service import TransactionService
        from datetime import datetime, timezone
        from decimal import Decimal
       
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryInvoice)
            .filter(InventoryInvoice.id == invoice_id)
            .with_for_update()
        )
        invoice = result.scalars().first()
        if not invoice:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Invoice not found")
            
        if invoice.temple_id != tid:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Not authorized to access this invoice")
       
        if not invoice.status or invoice.status.upper() != "PENDING":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invoice is not pending delivery")
           
        invoice.status = "COMPLETED"
        if delivery_in:
            if delivery_in.order_mode:
                invoice.order_mode = delivery_in.order_mode
            if delivery_in.payment_mode:
                invoice.payment_mode = delivery_in.payment_mode
            if delivery_in.remarks:
                invoice.remarks = delivery_in.remarks
            if delivery_in.items is not None:
                from sqlalchemy.orm.attributes import flag_modified
                delivered_map = {str(x.get("item_id")): x for x in delivery_in.items}
                new_items_data = []
                new_amount = 0.0
                for line in (invoice.items_data or []):
                    iid_str = str(line.get("item_id"))
                    if iid_str in delivered_map:
                        deliv = delivered_map[iid_str]
                        qty = float(deliv.get("qty", 0.0))
                        price = float(deliv.get("price", line.get("price", 0.0)))
                    else:
                        qty = 0.0
                        price = float(line.get("price", 0.0))
                    
                    new_items_data.append({
                        "item_id": line.get("item_id"),
                        "qty": qty,
                        "price": price,
                        "name": line.get("name")
                    })
                    new_amount += qty * price
                invoice.items_data = new_items_data
                invoice.amount = new_amount
                flag_modified(invoice, "items_data")

        # Derive payment totals and status dynamically
        total_amount = Decimal(str(invoice.amount))
        payment_status_input = (delivery_in.payment_status or "PAY_LATER").upper() if delivery_in else "PAY_LATER"
        
        paid_amount = Decimal("0.00")
        if payment_status_input == "FULL_PAYMENT":
            paid_amount = total_amount
        elif payment_status_input == "PARTIAL_PAYMENT":
            paid_amount = Decimal(str(delivery_in.paid_amount or 0.00)) if delivery_in else Decimal("0.00")

        if paid_amount < 0:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Paid amount cannot be negative")
        if paid_amount > total_amount:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Paid amount cannot exceed invoice total")

        balance_due = total_amount - paid_amount
        
        # System-Derived status logic
        if balance_due == total_amount:
            payment_status = "PAY_LATER"
        elif balance_due > 0 and paid_amount > 0:
            payment_status = "PARTIAL_PAYMENT"
        elif balance_due == 0:
            payment_status = "FULL_PAYMENT"
            
        invoice.payment_status = payment_status
        invoice.total_paid_amount = paid_amount
        invoice.balance_due = balance_due
        invoice.last_payment_date = datetime.now(timezone.utc) if paid_amount > 0 else None
        invoice.payment_completed_at = datetime.now(timezone.utc) if payment_status == "FULL_PAYMENT" else None
       
        # Resolve real user UUID from username/email/sub
        real_user_uuid = None
        if user_id:
            try:
                if isinstance(user_id, UUID):
                    real_user_uuid = user_id
                else:
                    real_user_uuid = UUID(str(user_id))
            except ValueError:
                from app.models.domain import User
                user_res = await db.execute(
                    select(User).filter(
                        (User.user_id == str(user_id)) |
                        (User.email == str(user_id))
                    )
                )
                user_obj = user_res.scalars().first()
                if user_obj:
                    real_user_uuid = user_obj.id

        if not real_user_uuid:
            from app.models.domain import User
            user_res = await db.execute(select(User).filter(User.temple_id == tid))
            user_obj = user_res.scalars().first()
            if user_obj:
                real_user_uuid = user_obj.id
            else:
                user_res = await db.execute(select(User))
                user_obj = user_res.scalars().first()
                if user_obj:
                    real_user_uuid = user_obj.id

        # Insert Payment Transaction if paid_amount > 0
        tx = None
        if paid_amount > 0:
            clean_method = (invoice.payment_mode or "CASH").upper().replace(" ", "_").replace("-", "_")
            if clean_method not in ('CASH', 'UPI', 'CARD', 'BANK_TRANSFER', 'CHEQUE'):
                clean_method = 'CASH'
            tx = InventoryPaymentTransaction(
                temple_id=tid,
                invoice_id=invoice.id,
                amount=paid_amount,
                payment_method=clean_method,
                payment_reference=delivery_in.payment_reference if delivery_in else None,
                transaction_status='COMPLETED',
                notes=invoice.remarks or "Initial delivery completion payment",
                created_by_user_id=real_user_uuid
            )
            db.add(tx)

        # Create GRN
        sup_res = await db.execute(select(Supplier).filter(Supplier.name == invoice.supplier_name, Supplier.temple_id == tid))
        supplier = sup_res.scalars().first()
       
        supplier_id = supplier.id if supplier else None
        if not supplier_id:
            sup_fallback_res = await db.execute(select(Supplier).filter(Supplier.temple_id == tid))
            sup_fallback = sup_fallback_res.scalars().first()
            if sup_fallback:
                supplier_id = sup_fallback.id
       
        ref = invoice.ref_number
        grn = ProcurementGRN(
            temple_id=tid,
            grn_code=f"GRN-{ref}",
            supplier_id=supplier_id,
            invoice_number=ref,
            total_amount=invoice.amount,
            received_by=real_user_uuid,
            status=ProcurementStatus.COMPLETED,
            remarks=f"Generated from Invoice {ref} on delivery completion",
            target_domain=invoice.target_domain
        )
        db.add(grn)
       
        # Process stock movements
        if invoice.items_data:
            for line in invoice.items_data:
                item_id = line.get("item_id")
                qty = line.get("qty", 0)
                if item_id and qty > 0:
                    await InventoryService.record_movement(
                        db=db,
                        temple_id=tid,
                        item_id=UUID(str(item_id)),
                        qty_change=float(qty),
                        movement_type=InventoryMovementType.PURCHASE,
                        performed_by=real_user_uuid,
                        reference_type="GRN",
                        reference_id=grn.grn_code,
                        remarks=f"Purchase via Invoice {ref}"
                    )
                   
        # Financial Transaction (Cash-Basis Expense)
        if paid_amount > 0:
            await TransactionService.create_transaction(
                db=db,
                temple_id=str(temple_id),
                txn_type="expense",
                category="purchase",
                amount=float(paid_amount),
                description=f"Purchase Invoice {ref} - {invoice.supplier_name} (Delivered & Paid)",
                reference_id=ref,
                source="system",
            )
           
        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=real_user_uuid,
            role=None,
            module_name="INVENTORY",
            action="DELIVERY_COMPLETED",
            action_type="UPDATE",
            entity_id=str(invoice.id),
            new_value={"status": "COMPLETED", "amount": float(invoice.amount)},
            details=f"Procurement invoice {invoice.ref_number} delivery completed."
        )
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=real_user_uuid,
            role=None,
            module_name="INVENTORY",
            action="GRN_CREATED",
            action_type="CREATE",
            entity_id=str(grn.id),
            new_value={"grn_code": grn.grn_code, "invoice_number": grn.invoice_number},
            details=f"Goods Receipt Note {grn.grn_code} generated on delivery completion."
        )

        await db.commit()
        await db.refresh(invoice)
        await db.refresh(grn)
        return {
            "id": invoice.id,
            "temple_id": invoice.temple_id,
            "supplier_id": invoice.supplier_id,
            "ref_number": invoice.ref_number,
            "supplier_name": invoice.supplier_name,
            "date": invoice.date,
            "items_summary": invoice.items_summary,
            "amount": invoice.amount,
            "order_mode": invoice.order_mode,
            "payment_mode": invoice.payment_mode,
            "remarks": invoice.remarks,
            "status": invoice.status,
            "payment_status": invoice.payment_status,
            "total_paid_amount": invoice.total_paid_amount,
            "balance_due": invoice.balance_due,
            "last_payment_date": invoice.last_payment_date,
            "payment_completed_at": invoice.payment_completed_at,
            "items_data": invoice.items_data,
            "created_by": invoice.created_by,
            "created_by_user_id": invoice.created_by_user_id,
            "created_at": invoice.created_at,
            "updated_at": invoice.updated_at,
            "grn_code": grn.grn_code,
            "grn_created_at": grn.created_at,
            "target_domain": invoice.target_domain,
            "payment_history": [tx] if tx else []
        }

    @staticmethod
    async def pay_due(db: AsyncSession, invoice_id: UUID, temple_id: str, user_id: UUID = None, remarks: str = "", payment_mode: str = "Cash", paid_amount: float = 0.0) -> dict:
        from app.models.domain import ProcurementGRN, InventoryPaymentTransaction
        from app.services.transaction_service import TransactionService
        from datetime import datetime, timezone
        from decimal import Decimal
       
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryInvoice)
            .filter(InventoryInvoice.id == invoice_id)
            .with_for_update()
        )
        invoice = result.scalars().first()
        if not invoice:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Invoice not found")
            
        if invoice.temple_id != tid:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Not authorized to access this invoice")
           
        if not invoice.status or invoice.status.upper() != "COMPLETED":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Cannot pay dues on a pending delivery")
           
        additional_paid = Decimal(str(paid_amount))
        if additional_paid <= 0:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")
            
        current_paid = Decimal(str(invoice.total_paid_amount or 0.00))
        total_amount = Decimal(str(invoice.amount))
        
        new_paid = current_paid + additional_paid
        if new_paid > total_amount:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Total paid amount cannot exceed invoice amount")
            
        balance_due = total_amount - new_paid
        
        # System-Derived status logic
        if balance_due == total_amount:
            payment_status = "PAY_LATER"
        elif balance_due > 0 and new_paid > 0:
            payment_status = "PARTIAL_PAYMENT"
        elif balance_due == 0:
            payment_status = "FULL_PAYMENT"
            
        invoice.total_paid_amount = new_paid
        invoice.balance_due = balance_due
        invoice.payment_status = payment_status
        invoice.last_payment_date = datetime.now(timezone.utc)
        if payment_status == "FULL_PAYMENT":
            invoice.payment_completed_at = datetime.now(timezone.utc)
            
        invoice.remarks = remarks
        invoice.payment_mode = payment_mode
        
        # Resolve real user UUID from username/email/sub
        real_user_uuid = None
        if user_id:
            try:
                if isinstance(user_id, UUID):
                    real_user_uuid = user_id
                else:
                    real_user_uuid = UUID(str(user_id))
            except ValueError:
                from app.models.domain import User
                user_res = await db.execute(
                    select(User).filter(
                        (User.user_id == str(user_id)) |
                        (User.email == str(user_id))
                    )
                )
                user_obj = user_res.scalars().first()
                if user_obj:
                    real_user_uuid = user_obj.id

        if not real_user_uuid:
            from app.models.domain import User
            user_res = await db.execute(select(User).filter(User.temple_id == tid))
            user_obj = user_res.scalars().first()
            if user_obj:
                real_user_uuid = user_obj.id
            else:
                user_res = await db.execute(select(User))
                user_obj = user_res.scalars().first()
                if user_obj:
                    real_user_uuid = user_obj.id
                    
        # Record payment transaction
        clean_method = (payment_mode or "CASH").upper().replace(" ", "_").replace("-", "_")
        if clean_method not in ('CASH', 'UPI', 'CARD', 'BANK_TRANSFER', 'CHEQUE'):
            clean_method = 'CASH'
        tx = InventoryPaymentTransaction(
            temple_id=tid,
            invoice_id=invoice.id,
            amount=additional_paid,
            payment_method=clean_method,
            payment_reference=None,
            transaction_status='COMPLETED',
            notes=remarks or "Due payment",
            created_by_user_id=real_user_uuid
        )
        db.add(tx)
       
        # Cash-Basis Expense Transaction
        if additional_paid > 0:
            await TransactionService.create_transaction(
                db=db,
                temple_id=str(temple_id),
                txn_type="expense",
                category="purchase",
                amount=float(additional_paid),
                description=f"Due Payment for Invoice {invoice.ref_number} - {invoice.supplier_name}",
                reference_id=invoice.ref_number,
                source="system",
            )
           
        await db.commit()
        await db.refresh(invoice)
        
        # Load payment history
        tx_res = await db.execute(
            select(InventoryPaymentTransaction)
            .filter(InventoryPaymentTransaction.invoice_id == invoice.id)
            .order_by(InventoryPaymentTransaction.payment_date.asc())
        )
        txs_list = tx_res.scalars().all()
       
        grn_res = await db.execute(select(ProcurementGRN).filter(ProcurementGRN.invoice_number == invoice.ref_number, ProcurementGRN.temple_id == tid))
        grn = grn_res.scalars().first()
       
        return {
            "id": invoice.id,
            "temple_id": invoice.temple_id,
            "supplier_id": invoice.supplier_id,
            "ref_number": invoice.ref_number,
            "supplier_name": invoice.supplier_name,
            "date": invoice.date,
            "items_summary": invoice.items_summary,
            "amount": invoice.amount,
            "order_mode": invoice.order_mode,
            "payment_mode": invoice.payment_mode,
            "remarks": invoice.remarks,
            "status": invoice.status,
            "payment_status": invoice.payment_status,
            "total_paid_amount": invoice.total_paid_amount,
            "balance_due": invoice.balance_due,
            "last_payment_date": invoice.last_payment_date,
            "payment_completed_at": invoice.payment_completed_at,
            "items_data": invoice.items_data,
            "created_by": invoice.created_by,
            "created_by_user_id": invoice.created_by_user_id,
            "created_at": invoice.created_at,
            "updated_at": invoice.updated_at,
            "grn_code": grn.grn_code if grn else None,
            "grn_created_at": grn.created_at if grn else None,
            "target_domain": invoice.target_domain,
            "payment_history": txs_list
        }

    @staticmethod
    async def cancel_invoice(db: AsyncSession, invoice_id: UUID, temple_id: str, user_id: UUID = None, reason: str = None) -> dict:
        from app.models.domain import ProcurementGRN, InventoryMovementType, ProcurementStatus
        from app.services.transaction_service import TransactionService
        from fastapi import HTTPException
        
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryInvoice)
            .filter(InventoryInvoice.id == invoice_id)
            .with_for_update()
        )
        invoice = result.scalars().first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
            
        if invoice.temple_id != tid:
            raise HTTPException(status_code=403, detail="Not authorized to access this invoice")
            
        if invoice.status and invoice.status.upper() == "CANCELLED":
            raise HTTPException(status_code=400, detail="Invoice is already cancelled")
            
        old_status = invoice.status
        invoice.status = "CANCELLED"
        if reason:
            cancellation_log = f"[Cancelled: {reason}]"
            invoice.remarks = (invoice.remarks + " | " + cancellation_log) if invoice.remarks else cancellation_log
        
        # If it was completed, reverse stock movements and create offsetting financial transaction
        if old_status and old_status.upper() == "COMPLETED":
            # 1. Update GRN status
            grn_res = await db.execute(select(ProcurementGRN).filter(ProcurementGRN.invoice_number == invoice.ref_number, ProcurementGRN.temple_id == tid))
            grn = grn_res.scalars().first()
            if grn:
                grn.status = ProcurementStatus.FAILED
                
            # 2. Reverse stock movements (negative adjustment)
            if invoice.items_data:
                # We need to resolve real user UUID for movement engine
                real_user_uuid = None
                if user_id:
                    try:
                        if isinstance(user_id, UUID):
                            real_user_uuid = user_id
                        else:
                            real_user_uuid = UUID(str(user_id))
                    except ValueError:
                        pass
                
                for line in invoice.items_data:
                    item_id = line.get("item_id")
                    qty = line.get("qty", 0)
                    if item_id and qty > 0:
                        await InventoryService.record_movement(
                            db=db,
                            temple_id=tid,
                            item_id=UUID(str(item_id)),
                            qty_change=-float(qty),
                            movement_type=InventoryMovementType.ADJUSTMENT,
                            performed_by=real_user_uuid,
                            reference_type="CANCEL",
                            reference_id=invoice.ref_number,
                            remarks=f"Reversal due to Purchase Invoice cancellation ({invoice.ref_number})"
                        )
                        
            # 3. Create offsetting income transaction
            if invoice.amount > 0:
                await TransactionService.create_transaction(
                    db=db,
                    temple_id=str(temple_id),
                    txn_type="income",
                    category="purchase",
                    amount=invoice.amount,
                    description=f"Reversal of Purchase Invoice {invoice.ref_number} (Cancelled)",
                    reference_id=invoice.ref_number,
                    source="system"
                )
                
        await db.commit()
        await db.refresh(invoice)
        return {"message": "Invoice cancelled successfully"}

    # --- Item Requests & Issue Sessions ---
    @staticmethod
    async def create_item_request(
        db: AsyncSession, req_in: ItemRequestCreate, temple_id: str, created_by: str = "Admin", user_id: UUID = None
    ) -> InventoryItemRequest:
        """REFACTORED: Request is now BUSINESS INTENT ONLY. Stock NOT deducted yet."""
        tid = UUID(str(temple_id))

        # Generate ref id in KRYYMMDD-01 format
        from datetime import datetime, timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist)
        date_str = now_ist.strftime("%y%m%d") # YYMMDD format
        
        # Count requests made today to get sequence
        today_str = now_ist.strftime("%Y-%m-%d")
        count_today_res = await db.execute(
            select(func.count(InventoryItemRequest.id)).filter(
                InventoryItemRequest.temple_id == tid,
                InventoryItemRequest.date == today_str
            )
        )
        count_today = count_today_res.scalar() or 0
        seq = str(count_today + 1).zfill(2)
        req_code = f"KR{date_str}-{seq}"

        items_list = []
        for line in req_in.items_data:
            items_list.append({
                "itemId": line.get("itemId") or line.get("item_id"),
                "qty": float(line.get("qty", 0.0)),
                "approvedQty": 0.0,
                "issuedQty": 0.0,
                "remarks": line.get("remarks", ""),
                "unit": line.get("unit", "piece")
            })

        req = InventoryItemRequest(
            temple_id=tid,
            req_code=req_code,
            date=req_in.date,
            requester=req_in.requester,
            role=req_in.role,
            department=req_in.department,
            items_summary=req_in.items_summary,
            items_data=items_list,
            remarks=req_in.remarks,
            status="PENDING", # Initial status for layered evolution
            created_by=created_by,
            priority=req_in.priority or "Medium",
            purpose=req_in.purpose or "",
            requested_by_user_id=user_id or req_in.requested_by_user_id,
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)
        return req

    @staticmethod
    async def create_issue_session(
        db: AsyncSession, session_in: IssueSessionCreate, temple_id: str, user_id: UUID
    ) -> InventoryIssueSession:
        """🔥 OPERATIONAL EXECUTION: This is where stock actually moves."""
        tid = UUID(str(temple_id))
       
        # 1. Fetch Request
        req_res = await db.execute(select(InventoryItemRequest).filter(InventoryItemRequest.id == session_in.request_id))
        request = req_res.scalars().first()
        if not request:
            raise ValueError("Item request not found")

        # 2. Create Session
        session = InventoryIssueSession(
            temple_id=tid,
            request_id=session_in.request_id,
            issued_by=user_id,
            location_id=session_in.location_id,
            status=InventoryIssueStatus.COMPLETED,
            remarks=session_in.remarks
        )
        db.add(session)

        # 3. Process Movements via Engine
        for line in session_in.items:
            item_id = line.get("itemId")
            qty = line.get("qty", 0)
            if item_id and qty > 0:
                await InventoryService.record_movement(
                    db=db,
                    temple_id=tid,
                    item_id=UUID(str(item_id)),
                    qty_change=-float(qty), # Negative for issuance
                    movement_type=InventoryMovementType.ISSUE,
                    performed_by=user_id,
                    location_id=session_in.location_id,
                    reference_type="REQUEST",
                    reference_id=request.req_code,
                    remarks=f"Issued via Session {session.id}"
                )

        # 4. Update Request Status
        request.status = "COMPLETED"
       
        # Append approval timeline log in IST
        from datetime import datetime, timedelta, timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp_str = datetime.now(ist).strftime("%d %b %Y, %I:%M:%S %p")
        approval_log = f"[Approval: Approved by Admin at {timestamp_str}]"
        if request.remarks:
            request.remarks = request.remarks + " | " + approval_log
        else:
            request.remarks = approval_log
       
        await db.commit()
        await db.refresh(session)
        return session

    # --- Enterprise Modules ---
   
    @staticmethod
    async def create_location(db: AsyncSession, loc_in: InventoryLocationCreate, temple_id: str) -> InventoryLocation:
        tid = UUID(str(temple_id))
        loc = InventoryLocation(
            temple_id=tid,
            name=loc_in.name,
            description=loc_in.description
        )
        db.add(loc)
        await db.commit()
        await db.refresh(loc)
        return loc

    @staticmethod
    async def get_locations(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        res = await db.execute(select(InventoryLocation).filter(InventoryLocation.temple_id == tid))
        return res.scalars().all()

    @staticmethod
    async def reconcile_stock(db: AsyncSession, recon_in: ReconciliationCreate, temple_id: str, user_id: UUID) -> InventoryReconciliation:
        tid = UUID(str(temple_id))
       
        # 1. Fetch current stock from KalavaraStock or StoreStock
        is_store = False
        prod_res = await db.execute(select(StoreProduct).filter(StoreProduct.id == recon_in.item_id, StoreProduct.temple_id == tid))
        product = prod_res.scalars().first()
        if product:
            is_store = True
            
        if is_store:
            stock_res = await db.execute(select(StoreStock).filter(StoreStock.product_id == recon_in.item_id, StoreStock.temple_id == tid))
            stock = stock_res.scalars().first()
            if not stock:
                stock = StoreStock(
                    temple_id=tid,
                    product_id=recon_in.item_id,
                    quantity=0.0,
                    version_number=1
                )
                db.add(stock)
                await db.flush()
        else:
            stock_res = await db.execute(select(KalavaraStock).filter(KalavaraStock.item_id == recon_in.item_id, KalavaraStock.temple_id == tid))
            stock = stock_res.scalars().first()
            if not stock:
                item_res = await db.execute(select(InventoryItem).filter(InventoryItem.id == recon_in.item_id, InventoryItem.temple_id == tid))
                item = item_res.scalars().first()
                if not item:
                    raise ValueError("Item not found")
                stock = KalavaraStock(
                    temple_id=tid,
                    item_id=recon_in.item_id,
                    quantity=item.stock or 0.0,
                    location_id=item.location_id,
                    version_number=1
                )
                db.add(stock)
                await db.flush()

        expected = stock.quantity
        actual = recon_in.actual_stock
        diff = actual - expected

        # 2. Record Adjustment via Engine
        if diff != 0:
            await InventoryService.record_movement(
                db=db,
                temple_id=tid,
                item_id=recon_in.item_id,
                qty_change=diff,
                movement_type=InventoryMovementType.ADJUSTMENT,
                performed_by=user_id,
                reference_type="RECONCILIATION",
                remarks=recon_in.remarks or "Manual reconciliation"
            )

        # 3. Log Reconciliation session
        recon = InventoryReconciliation(
            temple_id=tid,
            item_id=recon_in.item_id,
            expected_stock=expected,
            actual_stock=actual,
            adjustment_qty=diff,
            performed_by=user_id,
            remarks=recon_in.remarks
        )
        db.add(recon)
        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=None,
            module_name="INVENTORY",
            action="STOCK_RECONCILED",
            action_type="UPDATE",
            entity_id=str(recon.id),
            new_value={"expected": float(expected), "actual": float(actual), "diff": float(diff)},
            details=f"Stock reconciled. Expected: {expected}, Actual: {actual}, Diff: {diff}."
        )

        await db.commit()
        await db.refresh(recon)
        return recon

    @staticmethod
    async def create_ritual_template(db: AsyncSession, temp_in: RitualTemplateCreate, temple_id: str) -> RitualTemplate:
        tid = UUID(str(temple_id))
        template = RitualTemplate(
            temple_id=tid,
            name=temp_in.name,
            description=temp_in.description
        )
        db.add(template)
        await db.flush()

        for item in temp_in.items:
            ti = RitualTemplateItem(
                template_id=template.id,
                item_id=UUID(str(item.get("itemId"))),
                default_qty=float(item.get("defaultQty", 1.0))
            )
            db.add(ti)

        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def get_item_requests(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 500):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryItemRequest)
            .filter(InventoryItemRequest.temple_id == tid)
            .order_by(InventoryItemRequest.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def get_ritual_templates(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        res = await db.execute(select(RitualTemplate).filter(RitualTemplate.temple_id == tid))
        return res.scalars().all()

    @staticmethod
    async def get_ledger(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 500):
        tid = UUID(str(temple_id))
        res = await db.execute(
            select(InventoryStockLedger)
            .filter(InventoryStockLedger.temple_id == tid)
            .order_by(InventoryStockLedger.timestamp.desc())
            .offset(skip)
            .limit(limit)
        )
        return res.scalars().all()

    @staticmethod
    async def get_low_stock_items(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        res = await db.execute(
            select(InventoryItem)
            .filter(InventoryItem.temple_id == tid, InventoryItem.stock < InventoryItem.min_stock)
        )
        return res.scalars().all()

    @staticmethod
    async def get_low_stock_count(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        res = await db.execute(
            select(func.count(InventoryItem.id))
            .filter(InventoryItem.temple_id == tid, InventoryItem.stock < InventoryItem.min_stock)
        )
        return res.scalar() or 0


    @staticmethod
    async def record_return(
        db: AsyncSession,
        request_id: UUID,
        items: list,
        remarks: str,
        temple_id: str,
        user_id: UUID
    ) -> dict:
        from app.models.domain import InventoryItemRequest, InventoryMovementType, InventoryMovement, InventoryItem
        from datetime import datetime

        tid = UUID(str(temple_id))
       
        # 1. Fetch Request
        req_res = await db.execute(select(InventoryItemRequest).filter(InventoryItemRequest.id == request_id, InventoryItemRequest.temple_id == tid))
        request = req_res.scalars().first()
        if not request:
            raise ValueError("Item request not found")

        # 2. Record stock movements (increase stock for returned items)
        return_details = []
        for line in items:
            item_id = line.get("itemId")
            qty = line.get("qty", 0)
            if item_id and qty > 0:
                await InventoryService.record_movement(
                    db=db,
                    temple_id=tid,
                    item_id=UUID(str(item_id)),
                    qty_change=float(qty), # Positive for return
                    movement_type=InventoryMovementType.RETURN,
                    performed_by=user_id,
                    location_id=None,
                    reference_type="RETURN",
                    reference_id=request.req_code or str(request.id)[:8],
                    remarks=f"Returned from request {request.req_code or str(request.id)[:8]}"
                )
                # Find item name
                item_res = await db.execute(select(InventoryItem).filter(InventoryItem.id == UUID(str(item_id))))
                itm = item_res.scalars().first()
                name = itm.name if itm else "Unknown Item"
                return_details.append(f"{qty}x {name}")

        # 3. Append to timeline in request remarks
        from datetime import datetime, timedelta, timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp_str = datetime.now(ist).strftime("%d %b %Y, %I:%M:%S %p")
       
        details_str = ", ".join(return_details) if return_details else "items"
        return_log = f"[Return: Returned {details_str} at {timestamp_str}]"
       
        if request.remarks:
            request.remarks = request.remarks + " | " + return_log
        else:
            request.remarks = return_log
            
        request.status = "RETURNED"
        
        await db.commit()
        await db.refresh(request)
        return {"status": "success", "message": "Return logged successfully", "request_status": request.status}

    @staticmethod
    async def approve_item_request(
        db: AsyncSession, request_id: UUID, approved_items: list, temple_id: str, user_id: UUID
    ) -> InventoryItemRequest:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryItemRequest).filter(
                InventoryItemRequest.id == request_id,
                InventoryItemRequest.temple_id == tid
            )
        )
        req = result.scalars().first()
        if not req:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Request not found")
        
        # update approved qty
        approved_map = {str(item.get("itemId") or item.get("item_id")): float(item.get("approvedQty", 0.0)) for item in approved_items}
        
        items_copy = []
        for itm in (req.items_data or []):
            new_itm = dict(itm)
            iid = str(new_itm.get("itemId") or new_itm.get("item_id"))
            if iid in approved_map:
                new_itm["approvedQty"] = approved_map[iid]
            else:
                new_itm["approvedQty"] = float(new_itm.get("qty", 0.0)) # Default to full requested quantity if not specified
            items_copy.append(new_itm)
        
        req.items_data = items_copy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(req, "items_data")
        req.status = "APPROVED"
        req.approved_by_user_id = user_id
        
        from datetime import datetime, timedelta, timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp_str = datetime.now(ist).strftime("%d %b %Y, %I:%M:%S %p")
        log_str = f"[Approval: Approved at {timestamp_str}]"
        req.remarks = (req.remarks + " | " + log_str) if req.remarks else log_str

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=None,
            module_name="INVENTORY",
            action="MATERIAL_REQUEST_APPROVED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} approved."
        )

        await db.commit()
        await db.refresh(req)
        return req

    @staticmethod
    async def reject_item_request(
        db: AsyncSession, request_id: UUID, remarks: str, temple_id: str, user_id: UUID
    ) -> InventoryItemRequest:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryItemRequest).filter(
                InventoryItemRequest.id == request_id,
                InventoryItemRequest.temple_id == tid
            )
        )
        req = result.scalars().first()
        if not req:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Request not found")
        
        req.status = "REJECTED"
        req.approved_by_user_id = user_id
        
        from datetime import datetime, timedelta, timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp_str = datetime.now(ist).strftime("%d %b %Y, %I:%M:%S %p")
        log_str = f"[Approval: Rejected: {remarks} at {timestamp_str}]"
        req.remarks = (req.remarks + " | " + log_str) if req.remarks else log_str

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=None,
            module_name="INVENTORY",
            action="MATERIAL_REQUEST_REJECTED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} rejected. Remarks: {remarks}"
        )

        await db.commit()
        await db.refresh(req)
        return req

    @staticmethod
    async def cancel_item_request(
        db: AsyncSession, request_id: UUID, remarks: str, temple_id: str, user_id: UUID
    ) -> InventoryItemRequest:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryItemRequest).filter(
                InventoryItemRequest.id == request_id,
                InventoryItemRequest.temple_id == tid
            )
        )
        req = result.scalars().first()
        if not req:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Request not found")
        
        req.status = "CANCELLED"
        
        from datetime import datetime, timedelta, timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp_str = datetime.now(ist).strftime("%d %b %Y, %I:%M:%S %p")
        log_str = f"[Cancellation: Cancelled: {remarks} at {timestamp_str}]"
        req.remarks = (req.remarks + " | " + log_str) if req.remarks else log_str

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=None,
            module_name="INVENTORY",
            action="MATERIAL_REQUEST_CANCELLED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} cancelled. Remarks: {remarks}"
        )

        await db.commit()
        await db.refresh(req)
        return req

    @staticmethod
    async def issue_item_request_stock(
        db: AsyncSession, request_id: UUID, issued_items: list, location_id: str, temple_id: str, user_id: UUID
    ) -> InventoryItemRequest:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(InventoryItemRequest).filter(
                InventoryItemRequest.id == request_id,
                InventoryItemRequest.temple_id == tid
            )
        )
        req = result.scalars().first()
        if not req:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Request not found")
        
        # Verify status is APPROVED or PARTIALLY ISSUED
        if req.status not in ["APPROVED", "PARTIALLY ISSUED"]:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Cannot issue stock for a request in status {req.status}")
            
        # Create issue session record
        session = InventoryIssueSession(
            temple_id=tid,
            request_id=request_id,
            issued_by=user_id,
            location_id=location_id,
            status=InventoryIssueStatus.COMPLETED,
            remarks=f"Stock issuance for request {req.req_code}"
        )
        db.add(session)
        await db.flush()

        # Update issued quantities and record movements
        issued_map = {str(item.get("itemId") or item.get("item_id")): float(item.get("qty", 0.0)) for item in issued_items}
        
        items_copy = []
        fully_issued = True
        
        for itm in (req.items_data or []):
            new_itm = dict(itm)
            iid_str = str(new_itm.get("itemId") or new_itm.get("item_id"))
            approved = float(new_itm.get("approvedQty", 0.0))
            current_issued = float(new_itm.get("issuedQty", 0.0))
            
            to_issue = issued_map.get(iid_str, 0.0)
            
            if to_issue > 0:
                # Stock deduction check
                await InventoryService.record_movement(
                    db=db,
                    temple_id=tid,
                    item_id=UUID(iid_str),
                    qty_change=-to_issue, # Negative to deduct
                    movement_type=InventoryMovementType.ISSUE,
                    performed_by=user_id,
                    location_id=location_id,
                    reference_type="REQUEST",
                    reference_id=req.req_code,
                    remarks=f"Issued via Session {session.id}"
                )
                current_issued += to_issue
                new_itm["issuedQty"] = current_issued

            if current_issued < approved:
                fully_issued = False
            items_copy.append(new_itm)

        req.items_data = items_copy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(req, "items_data")
        req.status = "ISSUED" if fully_issued else "PARTIALLY ISSUED"
        req.issued_by_user_id = user_id
        
        from datetime import datetime, timedelta, timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp_str = datetime.now(ist).strftime("%d %b %Y, %I:%M:%S %p")
        log_str = f"[Issue: Stock issued (Session: {session.id}) at {timestamp_str}]"
        req.remarks = (req.remarks + " | " + log_str) if req.remarks else log_str

        # Add Audit log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=None,
            module_name="INVENTORY",
            action="MATERIAL_REQUEST_ISSUED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} stock issued. Status: {req.status}"
        )

        await db.commit()
        await db.refresh(req)
        return req

    @staticmethod
    async def get_price_approvals(
        db: AsyncSession, temple_id: str, status: Optional[str] = "PENDING_APPROVAL"
    ) -> List[dict]:
        from app.models.domain import PriceApprovalRequest
        from sqlalchemy.orm import selectinload
        tid = UUID(str(temple_id))
        stmt = select(PriceApprovalRequest).filter(PriceApprovalRequest.temple_id == tid).options(
            selectinload(PriceApprovalRequest.item),
            selectinload(PriceApprovalRequest.supplier)
        )
        if status:
            stmt = stmt.filter(PriceApprovalRequest.status == status)
        
        result = await db.execute(stmt)
        requests = result.scalars().all()
        
        out = []
        for r in requests:
            item_name = r.item.name if r.item else "Unknown Item"
            supplier_name = r.supplier.name if r.supplier else "Unknown Supplier"
            out.append({
                "id": r.id,
                "temple_id": r.temple_id,
                "supplier_id": r.supplier_id,
                "inventory_item_id": r.inventory_item_id,
                "old_price": r.old_price,
                "new_price": r.new_price,
                "change_percentage": r.change_percentage,
                "requested_by": r.requested_by,
                "requested_at": r.requested_at,
                "status": r.status,
                "approved_by": r.approved_by,
                "approved_at": r.approved_at,
                "reason": r.reason,
                "approval_type": r.approval_type,
                "requested_by_user_id": r.requested_by_user_id,
                "requested_by_role": r.requested_by_role,
                "reason_notes": r.reason_notes,
                "item_name": item_name,
                "supplier_name": supplier_name,
            })
        return out

    @staticmethod
    async def approve_price_approval(
        db: AsyncSession, request_id: UUID, temple_id: str,
        user_id: UUID, username: str, role: str
    ) -> dict:
        from app.models.domain import PriceApprovalRequest, SupplierPriceHistory
        from app.modules.audit.services.audit_service import AuditService
        from datetime import datetime, timezone
        from sqlalchemy.orm import selectinload
        
        tid = UUID(str(temple_id))
        res = await db.execute(
            select(PriceApprovalRequest)
            .filter(PriceApprovalRequest.id == request_id, PriceApprovalRequest.temple_id == tid)
            .options(selectinload(PriceApprovalRequest.supplier))
            .with_for_update()
        )
        req = res.scalars().first()
        if not req:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Price approval request not found")
        
        if req.requested_by_user_id and user_id and req.requested_by_user_id == user_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Self approval is not permitted.")
        
        if req.status != "PENDING_APPROVAL":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Request is already {req.status}")
            
        item_res = await db.execute(
            select(InventoryItem)
            .filter(InventoryItem.id == req.inventory_item_id, InventoryItem.temple_id == tid)
            .with_for_update()
        )
        item = item_res.scalars().first()
        if not item:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Associated inventory item not found")
            
        old_price = item.unit_price
        item.unit_price = req.new_price
        
        req.status = "APPROVED"
        req.approved_by = username
        req.approved_at = datetime.now(timezone.utc)
        
        supplier_name = req.supplier.name if req.supplier else "N/A"
        price_diff = req.new_price - (old_price or 0.0)
        history = SupplierPriceHistory(
            temple_id=tid,
            supplier_id=req.supplier_id,
            item_name=item.name,
            old_price=old_price,
            new_price=req.new_price,
            changed_by=username,
            supplier_name=supplier_name,
            price_difference=price_diff,
            percentage_change=req.change_percentage,
            modified_by_id=str(user_id) if user_id else "SYSTEM",
            modified_by_name=username,
            reason=f"Approved price change request: {req.id}",
            source="Supplier Update"
        )
        db.add(history)
        
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=role,
            module_name="INVENTORY",
            action="PRICE_APPROVAL_DECISION",
            action_type="UPDATE",
            entity_id=str(req.id),
            old_value={"status": "PENDING_APPROVAL"},
            new_value={
                "status": "APPROVED",
                "approved_by": username,
                "approved_at": req.approved_at.isoformat()
            },
            details=f"Decision: APPROVED | Request ID: {req.id} | Item: {item.name} | Supplier: {supplier_name} | Old Price: {old_price} | New Price: {req.new_price} | Percentage Change: {req.change_percentage:.2f}% | Approval Type: {req.approval_type} | Decision By: {username}",
        )
        
        await db.commit()
        return {"status": "success", "message": "Price approval request approved and item price updated."}

    @staticmethod
    async def reject_price_approval(
        db: AsyncSession, request_id: UUID, temple_id: str,
        user_id: UUID, username: str, role: str, reason: Optional[str] = None
    ) -> dict:
        from app.models.domain import PriceApprovalRequest
        from app.modules.audit.services.audit_service import AuditService
        from datetime import datetime, timezone
        from typing import Optional
        from sqlalchemy.orm import selectinload
        
        tid = UUID(str(temple_id))
        res = await db.execute(
            select(PriceApprovalRequest)
            .filter(PriceApprovalRequest.id == request_id, PriceApprovalRequest.temple_id == tid)
            .options(
                selectinload(PriceApprovalRequest.item),
                selectinload(PriceApprovalRequest.supplier)
            )
            .with_for_update()
        )
        req = res.scalars().first()
        if not req:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Price approval request not found")
        
        if req.requested_by_user_id and user_id and req.requested_by_user_id == user_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Self approval is not permitted.")
        
        if req.status != "PENDING_APPROVAL":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Request is already {req.status}")
            
        req.status = "REJECTED"
        req.approved_by = username
        req.approved_at = datetime.now(timezone.utc)
        req.reason = reason
        
        item_name = req.item.name if req.item else "N/A"
        supplier_name = req.supplier.name if req.supplier else "N/A"
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=user_id,
            role=role,
            module_name="INVENTORY",
            action="PRICE_APPROVAL_DECISION",
            action_type="UPDATE",
            entity_id=str(req.id),
            old_value={"status": "PENDING_APPROVAL"},
            new_value={
                "status": "REJECTED",
                "approved_by": username,
                "approved_at": req.approved_at.isoformat(),
                "reason": reason
            },
            details=f"Decision: REJECTED | Request ID: {req.id} | Item: {item_name} | Supplier: {supplier_name} | Old Price: {req.old_price} | New Price: {req.new_price} | Percentage Change: {req.change_percentage:.2f}% | Approval Type: {req.approval_type} | Decision By: {username} | Reason: {reason or 'None'}",
        )
        
        await db.commit()
        return {"status": "success", "message": "Price approval request rejected."}

def import_date():
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d")
