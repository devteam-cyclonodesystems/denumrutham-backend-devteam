"""
Advertisement Schemas.
"""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import List, Optional
from uuid import UUID
from datetime import datetime


class PlatformAdvertisementBase(BaseModel):
    placement: str = Field(..., description="E.g., HEADER_LEADERBOARD, TEMPLE_LIST_INLINE, TEMPLE_LIST_FOOTER")
    media_urls: List[str] = Field(..., description="Array of image URLs")
    media_type: str = Field(default="IMAGE", pattern="^(IMAGE|CAROUSEL)$")
    target_url: str = Field(..., description="Click-through redirect destination link")
    start_date: datetime
    end_date: datetime
    is_active: bool = True

    @model_validator(mode="after")
    def validate_ad_dates_and_media(self) -> 'PlatformAdvertisementBase':
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        
        m_urls = self.media_urls
        m_type = self.media_type
        if m_type == "IMAGE":
            if len(m_urls) != 1:
                raise ValueError("IMAGE ad must have exactly 1 media URL")
        elif m_type == "CAROUSEL":
            if len(m_urls) < 2:
                raise ValueError("CAROUSEL ad must have at least 2 media URLs")
        return self


class PlatformAdvertisementCreate(PlatformAdvertisementBase):
    pass


class PlatformAdvertisementUpdate(BaseModel):
    placement: Optional[str] = None
    media_urls: Optional[List[str]] = None
    media_type: Optional[str] = None
    target_url: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_ad_updates(self) -> 'PlatformAdvertisementUpdate':
        if self.start_date is not None and self.end_date is not None:
            if self.start_date >= self.end_date:
                raise ValueError("start_date must be before end_date")
        # Validate media checks if updated
        m_urls = self.media_urls
        m_type = self.media_type
        if m_urls is not None or m_type is not None:
            # Note: partial updates are validated at model/service layer or assumed checked if both provided
            pass
        return self


class PlatformAdvertisementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    placement: str
    media_urls: List[str]
    media_type: str
    target_url: str
    start_date: datetime
    end_date: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TempleAdvertisementBase(BaseModel):
    placement: str = Field(..., description="E.g., TEMPLE_DETAILS_AFTER_ABOUT, TEMPLE_DETAILS_BEFORE_GALLERY, TEMPLE_DETAILS_INLINE")
    media_urls: List[str] = Field(..., description="Array of image URLs")
    media_type: str = Field(default="IMAGE", pattern="^(IMAGE|CAROUSEL)$")
    target_url: str = Field(..., description="Click-through redirect destination link")
    start_date: datetime
    end_date: datetime
    display_order: int = 0
    is_active: bool = True

    @model_validator(mode="after")
    def validate_ad_dates_and_media(self) -> 'TempleAdvertisementBase':
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        
        m_urls = self.media_urls
        m_type = self.media_type
        if m_type == "IMAGE":
            if len(m_urls) != 1:
                raise ValueError("IMAGE ad must have exactly 1 media URL")
        elif m_type == "CAROUSEL":
            if len(m_urls) < 2:
                raise ValueError("CAROUSEL ad must have at least 2 media URLs")
        return self


class TempleAdvertisementCreate(TempleAdvertisementBase):
    pass


class TempleAdvertisementUpdate(BaseModel):
    placement: Optional[str] = None
    media_urls: Optional[List[str]] = None
    media_type: Optional[str] = None
    target_url: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_ad_updates(self) -> 'TempleAdvertisementUpdate':
        if self.start_date is not None and self.end_date is not None:
            if self.start_date >= self.end_date:
                raise ValueError("start_date must be before end_date")
        return self


class TempleAdvertisementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    temple_id: UUID
    placement: str
    media_urls: List[str]
    media_type: str
    target_url: str
    start_date: datetime
    end_date: datetime
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
