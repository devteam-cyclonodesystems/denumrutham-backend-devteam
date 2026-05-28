"""
Temple Follow Schemas.
"""
from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional
from datetime import datetime


class FollowTempleRequest(BaseModel):
    """Follow a temple."""
    temple_id: UUID4


class FollowedTempleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    temple_name: Optional[str] = None
    temple_location: Optional[str] = None
    created_at: datetime


class FollowStatusResponse(BaseModel):
    """Check if user follows a temple."""
    is_following: bool
    temple_id: UUID4
