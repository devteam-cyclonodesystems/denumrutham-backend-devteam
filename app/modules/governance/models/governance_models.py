import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database.database import Base
from app.modules.governance.models.operational_states import TempleOperationalState

JSONB_VARIANT = JSONB().with_variant(JSON, "sqlite")

def utcnow():
    return datetime.now(timezone.utc)


class ChangeRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"




class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    role = Column(String, nullable=True)
    module_name = Column(String, nullable=True)
    action = Column(String, nullable=False)
    action_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    details = Column(Text)
    approval_id = Column(UUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=True)
    content_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    module = Column(String, nullable=False)
    entity_id = Column(String, nullable=True)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    request_payload = Column(JSON, nullable=False)
    status = Column(String, default="pending")  # pending/approved/rejected
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    role = Column(String, nullable=True)  # Role-based delivery target
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    
# ====================================================================
# DEVOTEE PORTAL — New Models
# ====================================================================



class ArchanaBooking(Base):
    """Archana / Pooja booking — matches UI payload exactly."""
    __tablename__ = "archana_bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    ref_number = Column(String, nullable=True)  # e.g. AR01/0226
    devotee_name = Column(String, nullable=False)
    phone = Column(String, default="")
    nakshatra = Column(String, default="")
    items = Column(JSON, default=list)  # [{name, price}]
    family = Column(JSON, default=list)  # [{name, nakshatra, archana}]
    dakshina = Column(Float, default=0.0)
    booking_date = Column(String, nullable=False)
    booking_time = Column(String, default="")
    total = Column(Float, nullable=False, default=0.0)
    payment_mode = Column(String, default="Cash")
    booking_mode = Column(String, default="Counter")
    remarks = Column(Text, default="")
    consent = Column(Boolean, default=False)
    status = Column(String, default="confirmed")  # confirmed | cancelled
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, default="Admin")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)




class ChangeRequest(Base):
    """Field-level change request for approval-driven updates.
    
    All updates by STAFF go into ChangeRequest instead of live tables.
    TEMPLE_MANAGER approves → apply change, rejects → discard.
    """
    __tablename__ = "change_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String, nullable=False)  # 'temple', 'employee', 'hall', etc.
    entity_id = Column(String, nullable=False)  # UUID of the target entity
    field_name = Column(String, nullable=False)  # e.g. 'contact_number', 'salary'
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=False)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, default="PENDING")  # PENDING / APPROVED / REJECTED
    remarks = Column(Text, nullable=True)
    target_version = Column(Integer, nullable=True)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_change_requests_status", "status"),
        Index("idx_change_requests_entity", "entity_type", "entity_id"),
        Index("idx_change_requests_temple", "temple_id"),
    )


# ====================================================================
# TEMPLE FOLLOWER — Devotee follows a temple
# ====================================================================



class TempleDomainHistory(Base):
    """Tracks domain changes for URL stability and resolution."""
    __tablename__ = "temple_domain_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    old_domain = Column(String, nullable=False)
    new_domain = Column(String, nullable=False)
    changed_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_domain_history_old_domain", "old_domain"),
    )




class OperationalStateAudit(Base):
    """Tracks every transition in temple operational state."""
    __tablename__ = "operational_state_audits"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    old_state = Column(Enum(TempleOperationalState), nullable=True)
    new_state = Column(Enum(TempleOperationalState), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple")




class PlatformGlobalSetting(Base):
    """Global configuration settings for the entire platform (Super Admin controlled)."""
    __tablename__ = "platform_global_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(JSONB_VARIANT, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TempleOwnershipHistory(Base):
    """Auditable history of management_mode and subscription_plan changes for a temple."""
    __tablename__ = "temple_ownership_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_management_mode = Column(String(30), nullable=True)
    new_management_mode = Column(String(30), nullable=False)
    previous_subscription_plan = Column(String(40), nullable=True)
    new_subscription_plan = Column(String(40), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=True)
    changed_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_ownership_history_lookup", "temple_id", "changed_at"),
    )


class TempleLead(Base):
    """Pipeline capture of potential temple signups for sales & platform growth."""
    __tablename__ = "temple_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_name = Column(String, nullable=False)
    contact_person = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=False)
    state = Column(String, nullable=False)
    district = Column(String, nullable=False)
    interested_plan = Column(String, nullable=True)
    lead_source = Column(String, nullable=True)
    follow_up_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="NEW")  # NEW, CONTACTED, INTERESTED, NEGOTIATION, CONVERTED, LOST
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_temple_leads_status_date", "status", "follow_up_date"),
    )


class TempleClaimRequest(Base):
    """Lifecycle of devotee/manager claim requests over directory-only temples."""
    __tablename__ = "temple_claim_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    claimant_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED
    proof_urls = Column(JSON, nullable=True)  # List of URLs/paths to proofs
    target_management_mode = Column(String(30), nullable=False, default="GOVERNED")
    target_subscription_plan = Column(String(40), nullable=False, default="GOVERNED_STANDARD")
    trial_duration_days = Column(Integer, nullable=False, default=30)
    claimant_notes = Column(Text, nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    temple = relationship("Temple")
    claimant = relationship("User", foreign_keys=[claimant_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        Index("idx_claims_temple_status", "temple_id", "status"),
        Index("idx_claims_claimant", "claimant_id"),
    )


class TempleSuggestionStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MERGED = "MERGED"


class TempleSuggestion(Base):
    __tablename__ = "temple_suggestions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_number = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    deity = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    
    address_line_1 = Column(String, nullable=False)
    address_line_2 = Column(String, nullable=True)
    village_town = Column(String(150), nullable=False)
    district_id = Column(UUID(as_uuid=True), ForeignKey("district_master.id", ondelete="RESTRICT"), nullable=False, index=True)
    state_id = Column(UUID(as_uuid=True), ForeignKey("state_master.id", ondelete="RESTRICT"), nullable=False, index=True)
    pincode = Column(String(10), nullable=False)
    
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    google_maps_url = Column(String(512), nullable=True)
    
    website = Column(String(255), nullable=True)
    social_media_links = Column(JSONB_VARIANT, nullable=True, default={})
    festival_info = Column(Text, nullable=True)
    office_phone = Column(String(30), nullable=True)
    submitter_affiliation = Column(String(50), nullable=False)
    
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    submitter_ip = Column(String(45), nullable=True)
    
    confidence_score = Column(Integer, default=0, nullable=False)
    original_submission_json = Column(JSONB_VARIANT, nullable=False)
    
    status = Column(Enum(TempleSuggestionStatus), nullable=False, default=TempleSuggestionStatus.PENDING, index=True)
    rejection_reason = Column(Text, nullable=True)
    moderator_notes = Column(Text, nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    
    promoted_temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="SET NULL"), nullable=True)
    merged_temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    state = relationship("StateMaster", foreign_keys=[state_id])
    district = relationship("DistrictMaster", foreign_keys=[district_id])
    submitter = relationship("User", foreign_keys=[submitted_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    promoted_temple = relationship("Temple", foreign_keys=[promoted_temple_id])
    merged_temple = relationship("Temple", foreign_keys=[merged_temple_id])
    images = relationship("TempleSuggestionImage", back_populates="suggestion", cascade="all, delete-orphan")
    contacts = relationship("TempleSuggestionContact", back_populates="suggestion", cascade="all, delete-orphan")
    audits = relationship("TempleSuggestionAudit", back_populates="suggestion", cascade="all, delete-orphan")


class TempleSuggestionImage(Base):
    __tablename__ = "temple_suggestion_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggestion_id = Column(UUID(as_uuid=True), ForeignKey("temple_suggestions.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String(512), nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    suggestion = relationship("TempleSuggestion", back_populates="images")


class TempleSuggestionContact(Base):
    __tablename__ = "temple_suggestion_contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggestion_id = Column(UUID(as_uuid=True), ForeignKey("temple_suggestions.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    designation = Column(String(150), nullable=False)
    mobile_number = Column(String(20), nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    suggestion = relationship("TempleSuggestion", back_populates="contacts")


class TempleSuggestionAudit(Base):
    __tablename__ = "temple_suggestion_audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggestion_id = Column(UUID(as_uuid=True), ForeignKey("temple_suggestions.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # SUBMIT, EDIT, APPROVE, REJECT, MERGE
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    change_diff = Column(JSONB_VARIANT, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    suggestion = relationship("TempleSuggestion", back_populates="audits")
    user = relationship("User", foreign_keys=[performed_by])






