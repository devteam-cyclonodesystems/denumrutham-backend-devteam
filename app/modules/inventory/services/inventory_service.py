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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.domain import (
    InventoryItem, Supplier, InventoryInvoice, InventoryItemRequest,
    InventoryTransaction, InventoryTxnType,
    InventoryMovementType, InventoryStockLedger, InventoryLocation,
    InventoryIssueSession, ProcurementGRN, RitualTemplate, RitualTemplateItem,
    InventoryReconciliation, InventoryIssueStatus, ProcurementStatus,
    StoreProduct, StoreStock, KalavaraStock
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
                select(StoreStock).filter(StoreStock.product_id == item_id, StoreStock.temple_id == temple_id)
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
                select(KalavaraStock).filter(KalavaraStock.item_id == item_id, KalavaraStock.temple_id == temple_id)
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
    async def create_item(db: AsyncSession, item_in: InventoryItemCreate, temple_id: str) -> InventoryItem:
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
    async def create_supplier(db: AsyncSession, sup_in: SupplierCreate, temple_id: str) -> Supplier:
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
       
        # Sync Item to Kalavara
        if sup_in.items_supplied and "store module" not in (sup_in.remarks or "").lower():
            import re
            pattern = r"(.+)\s\((.+)\)\s@\s₹(.+)"
            for part in sup_in.items_supplied.split(','):
                match = re.search(pattern, part.strip())
                if match:
                    name = match.group(1).strip()
                    unit = match.group(2).strip()
                    try:
                        price = float(match.group(3).strip())
                    except: continue
                   
                    item_res = await db.execute(select(InventoryItem).filter(func.lower(InventoryItem.name) == func.lower(name), InventoryItem.temple_id == tid))
                    existing_item = item_res.scalars().first()
                    if not existing_item:
                        new_inv_item = InventoryItem(
                            temple_id=tid,
                            name=name,
                            category="Supplier Item",
                            unit=unit,
                            min_stock=10,
                            stock=0,
                            unit_price=price,
                            remarks=f"Auto-created from Supplier Catalog"
                        )
                        db.add(new_inv_item)
                    else:
                        existing_item.unit_price = price

        await db.commit()
        await db.refresh(sup)
        return sup

    @staticmethod
    async def update_supplier(db: AsyncSession, supplier_id: UUID, sup_in: SupplierCreate, temple_id: str) -> Supplier:
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
        import re
        # Pattern matches: Name (Unit) @ ₹Price
        pattern = r"(.+)\s\((.+)\)\s@\s₹(.+)"
       
        old_items = {}
        if sup.items_supplied:
            for part in sup.items_supplied.split(','):
                match = re.search(pattern, part.strip())
                if match:
                    name = match.group(1).strip()
                    try:
                        price = float(match.group(3).strip())
                        old_items[name] = price
                    except: continue

        new_items = {}
        if sup_in.items_supplied:
            for part in sup_in.items_supplied.split(','):
                match = re.search(pattern, part.strip())
                if match:
                    name = match.group(1).strip()
                    unit = match.group(2).strip()
                    try:
                        price = float(match.group(3).strip())
                        new_items[name] = {"price": price, "unit": unit}
                    except: continue

        # Record changes and Sync to Kalavara
        for name, data in new_items.items():
            new_price = data["price"]
            unit = data["unit"]
            old_price = old_items.get(name)
            if old_price != new_price:
                history = SupplierPriceHistory(
                    temple_id=tid,
                    supplier_id=supplier_id,
                    item_name=name,
                    old_price=old_price,
                    new_price=new_price,
                    changed_by="Admin"
                )
                db.add(history)
           
            # Sync Item to Kalavara
            if "store module" not in (sup_in.remarks or "").lower():
                item_res = await db.execute(select(InventoryItem).filter(func.lower(InventoryItem.name) == func.lower(name), InventoryItem.temple_id == tid))
                existing_item = item_res.scalars().first()
                if not existing_item:
                    new_inv_item = InventoryItem(
                        temple_id=tid,
                        name=name,
                        category="Supplier Item",
                        unit=unit,
                        min_stock=10,
                        stock=0,
                        unit_price=new_price,
                        remarks="Auto-created from Supplier Catalog"
                    )
                    db.add(new_inv_item)
                else:
                    existing_item.unit_price = new_price
       
        sup.name = sup_in.name
        sup.contact = sup_in.contact
        sup.alt_contact = sup_in.alt_contact
        sup.email = sup_in.email
        sup.address = sup_in.address
        sup.items_supplied = sup_in.items_supplied
        sup.remarks = sup_in.remarks
       
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

    # --- Invoices / GRN ---
    @staticmethod
    async def create_invoice(
        db: AsyncSession, inv_in: InvoiceCreate, temple_id: str, created_by: str = "Admin", user_id: UUID = None
    ) -> InventoryInvoice:
        """🔥 REFACTORED: Invoice → GRN → Ledger entries + Financial Txn."""
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

        # 2. Create Legacy Invoice (Backward Compat)
        invoice = InventoryInvoice(
            temple_id=tid,
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
            target_domain=inv_in.target_domain,
        )
        db.add(invoice)

        if inv_in.status and inv_in.status.upper() == "PENDING":
            await db.commit()
            await db.refresh(invoice)
            return {
                "id": invoice.id,
                "temple_id": invoice.temple_id,
                "ref_number": invoice.ref_number,
                "supplier_name": invoice.supplier_name,
                "date": invoice.date,
                "items_summary": invoice.items_summary,
                "amount": invoice.amount,
                "order_mode": invoice.order_mode,
                "payment_mode": invoice.payment_mode,
                "remarks": invoice.remarks,
                "status": invoice.status,
                "items_data": invoice.items_data,
                "created_by": invoice.created_by,
                "created_at": invoice.created_at,
                "grn_code": None,
                "grn_created_at": None,
                "target_domain": invoice.target_domain
            }

        await db.flush()

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

        await db.commit()
        await db.refresh(invoice)
        await db.refresh(grn)
        return {
            "id": invoice.id,
            "temple_id": invoice.temple_id,
            "ref_number": invoice.ref_number,
            "supplier_name": invoice.supplier_name,
            "date": invoice.date,
            "items_summary": invoice.items_summary,
            "amount": invoice.amount,
            "order_mode": invoice.order_mode,
            "payment_mode": invoice.payment_mode,
            "remarks": invoice.remarks,
            "status": invoice.status,
            "items_data": invoice.items_data,
            "created_by": invoice.created_by,
            "created_at": invoice.created_at,
            "grn_code": grn.grn_code if 'grn' in locals() else None,
            "grn_created_at": grn.created_at if 'grn' in locals() else None,
            "target_domain": invoice.target_domain
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
       
        invoices_with_grn = []
        for inv, grn in result.all():
            invoices_with_grn.append({
                "id": inv.id,
                "temple_id": inv.temple_id,
                "ref_number": inv.ref_number,
                "supplier_name": inv.supplier_name,
                "date": inv.date,
                "items_summary": inv.items_summary,
                "amount": inv.amount,
                "order_mode": inv.order_mode,
                "payment_mode": inv.payment_mode,
                "remarks": inv.remarks,
                "status": inv.status,
                "items_data": inv.items_data,
                "created_by": inv.created_by,
                "created_at": inv.created_at,
                "grn_code": grn.grn_code if grn else None,
                "grn_created_at": grn.created_at if grn else None,
                "target_domain": inv.target_domain
            })
        return invoices_with_grn

    @staticmethod
    async def complete_delivery(db: AsyncSession, invoice_id: UUID, temple_id: str, user_id: UUID = None, delivery_in = None) -> dict:
        from app.models.domain import Supplier, ProcurementGRN, InventoryMovementType, ProcurementStatus
        from app.services.transaction_service import TransactionService
       
        tid = UUID(str(temple_id))
        result = await db.execute(select(InventoryInvoice).filter(InventoryInvoice.id == invoice_id, InventoryInvoice.temple_id == tid))
        invoice = result.scalars().first()
        if not invoice:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Invoice not found")
       
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
                   
        # Financial Transaction
        if invoice.amount > 0:
            await TransactionService.create_transaction(
                db=db,
                temple_id=str(temple_id),
                txn_type="expense",
                category="purchase",
                amount=invoice.amount,
                description=f"Purchase Invoice {ref} - {invoice.supplier_name} (Delivered)",
                reference_id=ref,
                source="system",
            )
           
        await db.commit()
        await db.refresh(invoice)
        await db.refresh(grn)
        return {
            "id": invoice.id,
            "temple_id": invoice.temple_id,
            "ref_number": invoice.ref_number,
            "supplier_name": invoice.supplier_name,
            "date": invoice.date,
            "items_summary": invoice.items_summary,
            "amount": invoice.amount,
            "order_mode": invoice.order_mode,
            "payment_mode": invoice.payment_mode,
            "remarks": invoice.remarks,
            "status": invoice.status,
            "items_data": invoice.items_data,
            "created_by": invoice.created_by,
            "created_at": invoice.created_at,
            "grn_code": grn.grn_code,
            "grn_created_at": grn.created_at,
            "target_domain": invoice.target_domain
        }

    @staticmethod
    async def pay_due(db: AsyncSession, invoice_id: UUID, temple_id: str, user_id: UUID = None, remarks: str = "", payment_mode: str = "Cash", paid_amount: float = 0.0) -> dict:
        from app.models.domain import ProcurementGRN
        from app.services.transaction_service import TransactionService
       
        tid = UUID(str(temple_id))
        result = await db.execute(select(InventoryInvoice).filter(InventoryInvoice.id == invoice_id, InventoryInvoice.temple_id == tid))
        invoice = result.scalars().first()
        if not invoice:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Invoice not found")
           
        if not invoice.status or invoice.status.upper() != "COMPLETED":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Cannot pay dues on a pending delivery")
           
        invoice.remarks = remarks
        invoice.payment_mode = payment_mode
       
        if paid_amount > 0:
            await TransactionService.create_transaction(
                db=db,
                temple_id=str(temple_id),
                txn_type="expense",
                category="purchase",
                amount=paid_amount,
                description=f"Due Payment for Invoice {invoice.ref_number} - {invoice.supplier_name}",
                reference_id=invoice.ref_number,
                source="system",
            )
           
        await db.commit()
        await db.refresh(invoice)
       
        grn_res = await db.execute(select(ProcurementGRN).filter(ProcurementGRN.invoice_number == invoice.ref_number, ProcurementGRN.temple_id == tid))
        grn = grn_res.scalars().first()
       
        return {
            "id": invoice.id,
            "temple_id": invoice.temple_id,
            "ref_number": invoice.ref_number,
            "supplier_name": invoice.supplier_name,
            "date": invoice.date,
            "items_summary": invoice.items_summary,
            "amount": invoice.amount,
            "order_mode": invoice.order_mode,
            "payment_mode": invoice.payment_mode,
            "remarks": invoice.remarks,
            "status": invoice.status,
            "items_data": invoice.items_data,
            "created_by": invoice.created_by,
            "created_at": invoice.created_at,
            "grn_code": grn.grn_code if grn else None,
            "grn_created_at": grn.created_at if grn else None,
            "target_domain": invoice.target_domain
        }

    @staticmethod
    async def cancel_invoice(db: AsyncSession, invoice_id: UUID, temple_id: str, user_id: UUID = None) -> dict:
        from app.models.domain import ProcurementGRN, InventoryMovementType, ProcurementStatus
        from app.services.transaction_service import TransactionService
        from fastapi import HTTPException
        
        tid = UUID(str(temple_id))
        result = await db.execute(select(InventoryInvoice).filter(InventoryInvoice.id == invoice_id, InventoryInvoice.temple_id == tid))
        invoice = result.scalars().first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
            
        if invoice.status and invoice.status.upper() == "CANCELLED":
            raise HTTPException(status_code=400, detail="Invoice is already cancelled")
            
        old_status = invoice.status
        invoice.status = "CANCELLED"
        
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
            .filter(InventoryItem.temple_id == tid, InventoryItem.stock <= InventoryItem.min_stock)
        )
        return res.scalars().all()

    @staticmethod
    async def get_low_stock_count(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        res = await db.execute(
            select(func.count(InventoryItem.id))
            .filter(InventoryItem.temple_id == tid, InventoryItem.stock <= InventoryItem.min_stock)
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
        import pytz

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
        from app.models.domain import AuditLog
        audit = AuditLog(
            temple_id=tid,
            user_id=user_id,
            action="MATERIAL_REQUEST_APPROVED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} approved."
        )
        db.add(audit)

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
        from app.models.domain import AuditLog
        audit = AuditLog(
            temple_id=tid,
            user_id=user_id,
            action="MATERIAL_REQUEST_REJECTED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} rejected. Remarks: {remarks}"
        )
        db.add(audit)

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
        from app.models.domain import AuditLog
        audit = AuditLog(
            temple_id=tid,
            user_id=user_id,
            action="MATERIAL_REQUEST_CANCELLED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} cancelled. Remarks: {remarks}"
        )
        db.add(audit)

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
        from app.models.domain import AuditLog
        audit = AuditLog(
            temple_id=tid,
            user_id=user_id,
            action="MATERIAL_REQUEST_ISSUED",
            action_type="UPDATE",
            entity_id=str(req.id),
            details=f"Material request {req.req_code} stock issued. Status: {req.status}"
        )
        db.add(audit)

        await db.commit()
        await db.refresh(req)
        return req

def import_date():
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d")
