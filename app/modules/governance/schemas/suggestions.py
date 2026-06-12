"""
Pydantic Schemas for the Temple Suggestion System.
"""
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
import re

class SuggestionContactSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    designation: str
    mobile_number: str
    is_primary: Optional[bool] = False

    @field_validator("mobile_number")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        # Enforce basic format check (digits, optional plus, between 7 and 15 chars)
        clean_number = re.sub(r"[\s\-]", "", v)
        if not re.match(r"^\+?[0-9]{7,15}$", clean_number):
            raise ValueError("Invalid mobile number format")
        return clean_number

class SuggestionImageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    image_url: str
    is_primary: Optional[bool] = False

class TempleSuggestionCreate(BaseModel):
    name: str
    deity: str
    description: Optional[str] = None
    
    address_line_1: str
    address_line_2: Optional[str] = None
    village_town: str
    district_id: UUID
    state_id: UUID
    pincode: str
    
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google_maps_url: Optional[str] = None
    
    website: Optional[str] = None
    social_media_links: Optional[Dict[str, str]] = {}
    festival_info: Optional[str] = None
    office_phone: Optional[str] = None
    submitter_affiliation: str # DEVOTEE, PRIEST, COMMITTEE_MEMBER, NEIGHBOR, FAMILY, OTHER
    
    contacts: List[SuggestionContactSchema]
    images: Optional[List[SuggestionImageSchema]] = []

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Temple name cannot be empty")
        return v.strip()

    @field_validator("deity")
    @classmethod
    def validate_deity(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Main deity cannot be empty")
        return v.strip()

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str) -> str:
        clean_pin = v.strip()
        if not re.match(r"^[0-9]{5,10}$", clean_pin):
            raise ValueError("Pincode must be between 5 and 10 digits")
        return clean_pin

    @field_validator("contacts")
    @classmethod
    def validate_contacts(cls, v: List[SuggestionContactSchema]) -> List[SuggestionContactSchema]:
        if not v:
            raise ValueError("At least one responsible contact is required")
        has_primary = any(c.is_primary for c in v)
        if not has_primary:
            # Mark the first contact as primary by default
            v[0].is_primary = True
        return v

class TempleSuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference_number: str
    name: str
    deity: str
    description: Optional[str] = None
    
    address_line_1: str
    address_line_2: Optional[str] = None
    village_town: str
    district_id: UUID
    state_id: UUID
    pincode: str
    
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google_maps_url: Optional[str] = None
    
    website: Optional[str] = None
    social_media_links: Optional[Dict[str, str]] = {}
    festival_info: Optional[str] = None
    office_phone: Optional[str] = None
    submitter_affiliation: str
    
    submitted_by: UUID
    submitter_ip: Optional[str] = None
    confidence_score: int
    
    status: str
    rejection_reason: Optional[str] = None
    moderator_notes: Optional[str] = None
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    
    promoted_temple_id: Optional[UUID] = None
    merged_temple_id: Optional[UUID] = None
    
    created_at: datetime
    updated_at: datetime
    
    # Decorated extra fields
    state_name: Optional[str] = None
    district_name: Optional[str] = None
    submitter_name: Optional[str] = None
    reviewer_name: Optional[str] = None
    
    contacts: List[SuggestionContactSchema] = []
    images: List[SuggestionImageSchema] = []

class TempleSuggestionReview(BaseModel):
    status: str # APPROVED, REJECTED, MERGED
    rejection_reason: Optional[str] = None
    moderator_notes: Optional[str] = None
    merged_temple_id: Optional[UUID] = None
    
    # Edit Overrides during review
    name: Optional[str] = None
    deity: Optional[str] = None
    description: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    village_town: Optional[str] = None
    district_id: Optional[UUID] = None
    state_id: Optional[UUID] = None
    pincode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google_maps_url: Optional[str] = None
    website: Optional[str] = None
    social_media_links: Optional[Dict[str, str]] = None
    festival_info: Optional[str] = None
    office_phone: Optional[str] = None

class DuplicateCheckRequest(BaseModel):
    name: str
    district_id: UUID
    pincode: str

class DuplicateMatchResponse(BaseModel):
    temple_id: UUID
    name: str
    district: str
    pincode: str
    management_mode: str
