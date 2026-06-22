from pydantic import BaseModel, ConfigDict, UUID4, field_serializer
from typing import Optional, List
from datetime import datetime
from enum import Enum
from app.utils.timezone_utils import utc_to_ist

class QueueStatus(str, Enum):
    WAITING = "WAITING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    SYNC_PENDING = "SYNC_PENDING"

class ArchanaStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SYNCED = "SYNCED"
    OFFLINE_PENDING_SYNC = "OFFLINE_PENDING_SYNC"

class CatalogStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"

class DeityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"

class DeityBase(BaseModel):
    deity_name: str
    display_name: Optional[str] = None
    icon: Optional[str] = None
    status: DeityStatus = DeityStatus.ACTIVE
    display_order: int = 0

class DeityCreate(DeityBase):
    pass

class DeityUpdate(BaseModel):
    deity_name: Optional[str] = None
    display_name: Optional[str] = None
    icon: Optional[str] = None
    status: Optional[DeityStatus] = None
    display_order: Optional[int] = None

class DeityResponse(DeityBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    tenant_id: UUID4
    created_at: datetime
    updated_at: datetime

class ArchanaCatalogBase(BaseModel):
    name: str
    price: float
    deity_id: Optional[UUID4] = None
    duration_minutes: Optional[int] = 5
    remarks: Optional[str] = None
    is_active: bool = True
    daily_limit: Optional[int] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

class ArchanaCatalogCreate(ArchanaCatalogBase):
    pass

class ArchanaCatalogUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    deity_id: Optional[UUID4] = None
    duration_minutes: Optional[int] = None
    remarks: Optional[str] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

class ArchanaCatalogResponse(ArchanaCatalogBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    status: CatalogStatus
    version: int
    requested_by: Optional[UUID4] = None
    approved_by: Optional[UUID4] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    deity: Optional[DeityResponse] = None


class BookingItemCreate(BaseModel):
    service_id: UUID4
    quantity: int = 1

class BookingMemberCreate(BaseModel):
    name: str
    nakshatra: Optional[str] = None
    is_primary: bool = False
    manual_deity_name: Optional[str] = None
    items: List[BookingItemCreate]

class EnterpriseArchanaBookingCreate(BaseModel):
    primary_devotee_name: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    whatsapp_consent: bool = False
    booking_date: Optional[datetime] = None
    ritual_time: Optional[datetime] = None
    priority_slot: bool = False
    dakshina: float = 0.0
    delivery_charge: float = 0.0
    payment_mode: str = "Cash"
    booking_mode: str = "Counter"
    prasadam_collection: str = "Collect Directly"
    remarks: Optional[str] = None
    members: List[BookingMemberCreate]
    offline_event_id: Optional[str] = None
    device_id: Optional[str] = None
    idempotency_key: Optional[str] = None

class BookingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    service_id: UUID4
    quantity: int
    price_at_booking: float
    ritual_name_snapshot: Optional[str] = None
    ritual_deity_snapshot: Optional[str] = None
    ritual_duration_snapshot: Optional[int] = None
    ritual_version_id: Optional[int] = None
    total_price: float


class BookingMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    name: str
    nakshatra: Optional[str]
    is_primary: bool
    items: List[BookingItemResponse]

class RitualQueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    token_number: str
    status: QueueStatus
    priest_id: Optional[UUID4]
    estimated_start_time: Optional[datetime]

class EnterpriseArchanaBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    ref_id: str
    primary_devotee_name: str
    phone_number: Optional[str] = None
    booking_date: datetime
    ritual_time: Optional[datetime] = None
    total_amount: float
    dakshina: float
    delivery_charge: float = 0.0
    grand_total: float
    payment_mode: str
    booking_mode: str
    prasadam_collection: str = "Collect Directly"
    status: ArchanaStatus
    created_by: Optional[UUID4] = None
    created_at: datetime
    members: List[BookingMemberResponse]
    queue_entry: Optional[RitualQueueResponse] = None

    @field_serializer('ritual_time')
    def serialize_ritual_time(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return utc_to_ist(dt).isoformat()

class DashboardKPIs(BaseModel):
    total_bookings: int
    confirmed_bookings: int
    cancelled_bookings: int
    total_revenue: float
    today_bookings: int
    pending_queue: int
    completed_rituals: int

# Backward compatibility shells
class ArchanaBookingCreate(EnterpriseArchanaBookingCreate):
    pass

class ArchanaBookingResponse(EnterpriseArchanaBookingResponse):
    pass
