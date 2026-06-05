import re
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime, date, time
from uuid import UUID
from app.modules.temple_management.models.temple_models import ImageCategory, ActivityStatus

HEX_COLOR_REGEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

def validate_hex_color(value: str) -> str:
    if not HEX_COLOR_REGEX.match(value):
        raise ValueError("Color must be a valid HEX format (e.g. #FFFFFF or #FFF)")
    return value


# ---------- Website Settings ----------
class TempleWebsiteSettingsBase(BaseModel):
    theme_name: Optional[str] = "default"
    primary_color: Optional[str] = "#ff6600"
    secondary_color: Optional[str] = "#ffcc00"
    logo_url: Optional[str] = None
    hero_layout: Optional[str] = "split"
    section_order: Optional[List[str]] = [
        "hero", "about", "deities", "announcements", "activities", "gallery", "offerings", "location"
    ]
    enable_mantras: Optional[bool] = True
    enable_festivals: Optional[bool] = True
    enable_donations: Optional[bool] = True
    enable_hall_booking: Optional[bool] = True
    enable_store: Optional[bool] = True
    seo_keywords: Optional[str] = None
    og_image_url: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    seo_description: Optional[str] = None
    notice_board_content: Optional[dict] = None

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_colors(cls, v):
        if v is not None:
            return validate_hex_color(v)
        return v


class TempleWebsiteSettingsUpdate(BaseModel):
    theme_name: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    logo_url: Optional[str] = None
    hero_layout: Optional[str] = None
    section_order: Optional[List[str]] = None
    enable_mantras: Optional[bool] = None
    enable_festivals: Optional[bool] = None
    enable_donations: Optional[bool] = None
    enable_hall_booking: Optional[bool] = None
    enable_store: Optional[bool] = None
    seo_keywords: Optional[str] = None
    og_image_url: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    seo_description: Optional[str] = None
    notice_board_content: Optional[dict] = None

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_colors(cls, v):
        if v is not None:
            return validate_hex_color(v)
        return v


class TempleWebsiteSettingsResponse(TempleWebsiteSettingsBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    temple_id: UUID
    created_at: datetime
    updated_at: datetime


# ---------- Announcements ----------
class TempleAnnouncementBase(BaseModel):
    title: str
    content: str
    is_active: Optional[bool] = True
    is_pinned: Optional[bool] = False
    priority: Optional[int] = 0
    display_order: Optional[int] = 0
    start_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None


class TempleAnnouncementCreate(TempleAnnouncementBase):
    pass


class TempleAnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None
    is_pinned: Optional[bool] = None
    priority: Optional[int] = None
    display_order: Optional[int] = None
    start_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None


class TempleAnnouncementResponse(TempleAnnouncementBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    temple_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None


# ---------- Activities ----------
class TempleActivityBase(BaseModel):
    title: str
    description: Optional[str] = None
    activity_date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = None
    is_active: Optional[bool] = True
    status: Optional[ActivityStatus] = ActivityStatus.UPCOMING
    livestream_url: Optional[str] = None


class TempleActivityCreate(TempleActivityBase):
    pass


class TempleActivityUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    activity_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
    status: Optional[ActivityStatus] = None
    livestream_url: Optional[str] = None


class TempleActivityResponse(TempleActivityBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    temple_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None


# ---------- Image Gallery ----------
class TempleImageBase(BaseModel):
    image_url: str
    caption: Optional[str] = ""
    category: Optional[ImageCategory] = ImageCategory.GALLERY


class TempleImageCreate(TempleImageBase):
    pass


class TempleImageUpdate(BaseModel):
    image_url: Optional[str] = None
    caption: Optional[str] = None
    category: Optional[ImageCategory] = None


class TempleImageResponse(TempleImageBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    temple_id: UUID
    created_at: datetime


# ---------- Profile Draft Update ----------
class TempleProfileDraftUpdate(BaseModel):
    description: Optional[str] = None
    history: Optional[str] = None
    location: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    contact_number: Optional[str] = None
    email: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    live_stream_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    upi_id: Optional[str] = None
    image_url: Optional[str] = None
    main_deity: Optional[str] = None
    deities: Optional[List[str]] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    twitter_url: Optional[str] = None
    website_url: Optional[str] = None
    festivals_description: Optional[str] = None
