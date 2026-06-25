import asyncio
import sys
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.models import Temple, TempleBankAccount, ArchanaCatalog
from app.core.security.encryption import encrypt_data

async def link_bank_account(
    temple_name: str,
    bank_name: str,
    account_number: str,
    ifsc_code: str,
    account_holder_name: str,
    account_type: str = "SAVINGS",
    enable_all_archanas: bool = True
):
    async with AsyncSessionLocal() as db:
        # Find temple
        stmt = select(Temple).filter(Temple.name.ilike(f"%{temple_name}%"))
        res = await db.execute(stmt)
        temple = res.scalar_one_or_none()
        if not temple:
            print(f"Error: Temple '{temple_name}' not found.")
            return
        
        print(f"Found Temple: {temple.name} (ID: {temple.id})")
        
        # Find a valid user to satisfy submitted_by foreign key
        from app.models import User
        stmt_user = select(User).limit(1)
        res_user = await db.execute(stmt_user)
        user = res_user.scalar_one_or_none()
        if not user:
            print("Error: No users found in database.")
            return
        
        print(f"Using user '{user.email}' (ID: {user.id}) as submitter/verifier.")
        
        # Deactivate any existing bank accounts for this temple
        await db.execute(
            update(TempleBankAccount)
            .where(TempleBankAccount.temple_id == temple.id)
            .values(is_active=False, is_primary=False)
        )
        
        # Create new verified bank account
        account_number_enc = encrypt_data(account_number)
        bank_ac = TempleBankAccount(
            temple_id=temple.id,
            account_holder_name=account_holder_name,
            bank_name=bank_name,
            account_number_enc=account_number_enc,
            ifsc_code=ifsc_code,
            account_type=account_type.upper(),
            verification_status="VERIFIED",
            is_active=True,
            is_primary=True,
            submitted_by=user.id,
            verified_by=user.id,
            verified_at=datetime.now(timezone.utc),
            proof_uploaded_at=datetime.now(timezone.utc)
        )
        db.add(bank_ac)
        print(f"Adding bank account: {bank_name} - {account_holder_name} (IFSC: {ifsc_code})")
        
        if enable_all_archanas:
            # Enable online archanas
            stmt_cat = select(ArchanaCatalog).filter(ArchanaCatalog.temple_id == temple.id)
            res_cat = await db.execute(stmt_cat)
            archanas = res_cat.scalars().all()
            print(f"Found {len(archanas)} archanas in catalog. Enabling online booking for all of them.")
            for arc in archanas:
                arc.is_online_enabled = True
                arc.is_active = True
        
        await db.commit()
        print("Success! Bank account successfully linked & verified, and online bookings enabled for catalog items.")

if __name__ == "__main__":
    # Link bank details for Malottu temple
    asyncio.run(link_bank_account(
        temple_name="Malottu Sree Bhadrakali Temple",
        bank_name="Canara Bank",
        account_number="110022334455",
        ifsc_code="CNRB0001234",
        account_holder_name="Malottu Sree Bhadrakali Temple Trust",
        account_type="SAVINGS",
        enable_all_archanas=True
    ))
