from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional
from datetime import datetime


class TransactionCreate(BaseModel):
    type: str  # "income" | "expense"
    category: str  # archana | hall_booking | salary | purchase | donation | offering | store | other
    amount: float
    description: str = ""
    reference_id: Optional[str] = None
    source: str = "manual"


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    type: str
    category: str
    amount: float
    description: str
    reference_id: Optional[str] = None
    source: str
    date: datetime
    created_at: datetime
