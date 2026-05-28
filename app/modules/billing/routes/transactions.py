"""Transaction API endpoints with strict tenant enforcement."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import TokenData
from app.schemas.transaction import TransactionCreate, TransactionResponse
from app.services.transaction_service import TransactionService

router = APIRouter()


@router.post("", response_model=TransactionResponse)
async def create_transaction(
    txn_in: TransactionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    txn = await TransactionService.create_transaction(
        db=db,
        temple_id=temple_id,
        txn_type=txn_in.type,
        category=txn_in.category,
        amount=txn_in.amount,
        description=txn_in.description,
        reference_id=txn_in.reference_id,
        source=txn_in.source,
    )
    await db.commit()
    return txn


@router.get("", response_model=List[TransactionResponse])
async def list_transactions(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await TransactionService.get_transactions(db=db, temple_id=temple_id, skip=skip, limit=limit)
