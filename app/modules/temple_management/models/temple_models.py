import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint, event
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, backref, validates
from app.core.database.database import Base
from app.modules.governance.models.operational_states import TempleOperationalState
from app.modules.bookings.models.booking_models import ServiceType

JSONB_VARIANT = JSONB().with_variant(JSON, "sqlite")


def utcnow():
    return datetime.now(timezone.utc)


class TempleApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ImageCategory(str, enum.Enum):
    HERO_DESKTOP = "HERO_DESKTOP"
    HERO_MOBILE = "HERO_MOBILE"
    GALLERY = "GALLERY"
    DEITY = "DEITY"
    FESTIVAL = "FESTIVAL"
    FACILITY = "FACILITY"
    OTHER = "OTHER"


class ActivityStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class ServiceType(str, enum.Enum):
    ARCHANA = "ARCHANA"
    OFFERING = "OFFERING"
    HALL_BOOKING = "HALL_BOOKING"
    DONATION = "DONATION"
    STORE = "STORE"




class StateMaster(Base):
    __tablename__ = "state_master"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class DistrictMaster(Base):
    __tablename__ = "district_master"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_id = Column(UUID(as_uuid=True), ForeignKey("state_master.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=False, index=True)
    code = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("state_id", "name", name="uq_state_district_name"),
        UniqueConstraint("state_id", "slug", name="uq_state_district_slug"),
    )


class TempleSearchIndex(Base):
    __tablename__ = "temple_search_index"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    alternative_names = Column(Text, default="", server_default="")
    keywords = Column(Text, default="", server_default="")
    village = Column(String, default="", server_default="")
    searchable_text = Column(Text, default="", server_default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Temple(Base):
    __tablename__ = "temples"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    domain = Column(String, nullable=False) # Unique constraint replaced by partial index in __table_args__
    location = Column(String, default="")
    state = Column(String, default="")
    address_line_1 = Column(String, default="")
    address_line_2 = Column(String, default="")
    district = Column(String, default="")
    pincode = Column(String, default="")
    contact_number = Column(String, default="")
    alternate_contact = Column(String, default="")
    email = Column(String, default="")
    description = Column(Text, default="")
    # --- Phase 2: Domain + Identifier Architecture ---
    temple_code = Column(String, unique=True, nullable=True, index=True) # Format: TMP-YYYYMMDD-XXX

    # Dual-status: 'PENDING'/'APPROVED'/'REJECTED' for registration,
    # 'active'/'inactive' for operational (backward compat)
    status = Column(String, nullable=False, default="PENDING")
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    
    # Phase 1 Hardening: Explicit approval audit fields
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Phase 4 Hardening: Advanced Security
    security_version = Column(Integer, default=1, nullable=False)
    last_security_event_at = Column(DateTime(timezone=True), nullable=True)

    # Phase 5: Tenant Operational Governance
    operational_state = Column(Enum(TempleOperationalState), nullable=False, default=TempleOperationalState.ACTIVE)

    # Multi-Tier Operating & Subscription Model
    management_mode = Column(String(30), nullable=False, default="SELF_MANAGED")
    directory_status = Column(String(30), nullable=False, default="ACTIVE")
    subscription_plan = Column(String(40), nullable=False, default="SELF_MANAGED_PRO")

    # Phase 6 Additions
    state_id = Column(UUID(as_uuid=True), ForeignKey("state_master.id", ondelete="SET NULL"), nullable=True)
    district_id = Column(UUID(as_uuid=True), ForeignKey("district_master.id", ondelete="SET NULL"), nullable=True)
    verification_level = Column(Integer, default=0, nullable=False, server_default=text("0"))
    is_featured = Column(Boolean, default=False, nullable=False, server_default=text("false"))

    # Temple Suggestion Tracking
    creation_source = Column(String(50), nullable=False, server_default="SUPERADMIN_CREATED", default="SUPERADMIN_CREATED")
    source_suggestion_id = Column(UUID(as_uuid=True), ForeignKey("temple_suggestions.id", ondelete="SET NULL"), nullable=True)
    merged_temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index("unique_active_domain", "domain", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("idx_temples_visible", "id", postgresql_where=text("status = 'APPROVED' AND is_active = TRUE")),
        Index("idx_temples_directory_status", "directory_status"),
    )

    # Relationships
    profile = relationship("TempleProfile", back_populates="temple", uselist=False)
    images = relationship("TempleImage", back_populates="temple")
    user_temples = relationship("UserTemple", back_populates="temple")
    followers = relationship("TempleFollower", back_populates="temple")
    website_settings = relationship("TempleWebsiteSettings", back_populates="temple", uselist=False, cascade="all, delete-orphan")
    website_settings_live = relationship("TempleWebsiteSettingsLive", uselist=False, cascade="all, delete-orphan")
    merged_temple = relationship("Temple", remote_side=[id], foreign_keys=[merged_temple_id])
    advertisements = relationship("TempleAdvertisement", back_populates="temple", cascade="all, delete-orphan")
    recommendations = relationship("ServiceRecommendation", back_populates="temple", cascade="all, delete-orphan")
    
    # Phase 6 relationships
    state_ref = relationship("StateMaster", foreign_keys=[state_id])
    district_ref = relationship("DistrictMaster", foreign_keys=[district_id])
    search_index = relationship("TempleSearchIndex", backref="temple", uselist=False, cascade="all, delete-orphan")




class TempleStatusAudit(Base):
    __tablename__ = "temple_status_audit"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    old_status = Column(String, nullable=False)
    new_status = Column(String, nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime(timezone=True), default=utcnow)
    reason = Column(Text, nullable=True)




class TempleProfile(Base):
    """Extended temple information for the public devotee portal."""
    __tablename__ = "temple_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), unique=True, nullable=False)
    description = Column(Text, default="")
    history = Column(Text, default="")
    location = Column(String, default="")
    district = Column(String, default="")
    state = Column(String, default="")
    country = Column(String, default="India")
    contact_number = Column(String, default="")
    email = Column(String, default="")
    opening_time = Column(String, default="06:00")
    closing_time = Column(String, default="20:00")
    live_stream_url = Column(String, default="")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    upi_id = Column(String, default="")
    image_url = Column(String, default="")
    main_deity = Column(String, default="")
    deities = Column(JSON, nullable=True)
    facebook_url = Column(String, default="")
    instagram_url = Column(String, default="")
    youtube_url = Column(String, default="")
    twitter_url = Column(String, default="")
    website_url = Column(String, default="")
    festivals_description = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple", back_populates="profile")




class TempleProfileDraft(Base):
    """
    Staging table for temple profile edits.
    Manager edits → saved here.
    Admin approves → promote to TempleProfile.
    """
    __tablename__ = "temple_profile_drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    description = Column(Text, nullable=True)
    history = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    district = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, default="India")
    contact_number = Column(String, nullable=True)
    email = Column(String, nullable=True)
    opening_time = Column(String, nullable=True)
    closing_time = Column(String, nullable=True)
    live_stream_url = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    upi_id = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    main_deity = Column(String, nullable=True)
    deities = Column(JSON, nullable=True)
    facebook_url = Column(String, nullable=True)
    instagram_url = Column(String, nullable=True)
    youtube_url = Column(String, nullable=True)
    twitter_url = Column(String, nullable=True)
    website_url = Column(String, nullable=True)
    festivals_description = Column(Text, nullable=True)
    
    # Audit
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, default="PENDING")  # PENDING / APPROVED / REJECTED
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)




class TempleImage(Base):
    """Gallery images for a temple."""
    __tablename__ = "temple_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    image_url = Column(String, nullable=False)
    caption = Column(String, default="")
    category = Column(Enum(ImageCategory, name="image_category_enum"), nullable=False, default=ImageCategory.GALLERY)
    is_visible = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple", back_populates="images")

    @classmethod
    def filter_visible(cls, images):
        """Filter out hidden images from public display."""
        return [img for img in images if getattr(img, 'is_visible', True) is not False]


class TempleWebsiteSettings(Base):
    __tablename__ = "temple_website_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    theme_name = Column(String, nullable=False, default="default")
    primary_color = Column(String, nullable=False, default="#ff6600")
    secondary_color = Column(String, nullable=False, default="#ffcc00")
    logo_url = Column(String, nullable=True)
    hero_layout = Column(String, nullable=False, default="split")
    feature_visibility = Column(JSONB_VARIANT, nullable=False, default=dict)
    section_order = Column(JSON, nullable=False, default=lambda: ["hero", "about", "deities", "announcements", "activities", "gallery", "offerings", "location"])
    enable_mantras = Column(Boolean, nullable=False, default=True)
    enable_festivals = Column(Boolean, nullable=False, default=True)
    enable_donations = Column(Boolean, nullable=False, default=True)
    enable_hall_booking = Column(Boolean, nullable=False, default=True)
    enable_store = Column(Boolean, nullable=False, default=True)
    seo_keywords = Column(String, nullable=True)
    og_image_url = Column(String, nullable=True)
    hero_title = Column(String, nullable=True)
    hero_subtitle = Column(String, nullable=True)
    seo_description = Column(String, nullable=True)
    notice_board_content = Column(JSON, nullable=True)
    location_settings = Column(JSONB_VARIANT, nullable=True, default=dict)
    timings_settings = Column(JSONB_VARIANT, nullable=True, default=list)
    daily_activities_settings = Column(JSONB_VARIANT, nullable=True, default=list)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Website Builder Approval Workflow Tracking
    approval_status = Column(String(30), nullable=False, default="DRAFT")
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    temple = relationship("Temple", back_populates="website_settings")


JSONB_VARIANT = JSONB().with_variant(JSON, "sqlite")


class TempleWebsiteSettingsLive(Base):
    """Live public website snapshot for the Website Builder."""
    __tablename__ = "temple_website_settings_live"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("temples.id", ondelete="CASCADE"), 
        unique=True, 
        nullable=False, 
        index=True
    )
    settings_snapshot = Column(JSONB_VARIANT, nullable=False)
    schema_version = Column(Integer, default=1, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String, default="PUBLISHED", nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class TempleAnnouncement(Base):
    __tablename__ = "temple_announcements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_pinned = Column(Boolean, nullable=False, default=False)
    priority = Column(Integer, nullable=False, default=0)
    display_order = Column(Integer, nullable=False, default=0)
    start_date = Column(DateTime(timezone=True), nullable=True)
    expiry_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    temple = relationship("Temple", backref=backref("announcements", cascade="all, delete-orphan"))


class TempleActivity(Base):
    __tablename__ = "temple_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    activity_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    location = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    status = Column(Enum(ActivityStatus, name="activity_status_enum"), nullable=False, default=ActivityStatus.UPCOMING)
    livestream_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    temple = relationship("Temple", backref=backref("activities", cascade="all, delete-orphan"))


class TempleFestival(Base):
    __tablename__ = "temple_festivals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    banner_image = Column(String, nullable=True)
    catalogue_urls = Column(JSONB_VARIANT, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    temple = relationship("Temple", backref=backref("festivals", cascade="all, delete-orphan"))


class TempleService(Base):
    """Services offered by a temple (archana, offerings, hall booking, etc.)."""
    __tablename__ = "temple_services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    service_name = Column(String, nullable=False)
    service_type = Column(Enum(ServiceType), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    description = Column(Text, default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class TempleFollower(Base):
    """Devotee follows a temple for notifications and quick access."""
    __tablename__ = "temple_followers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="followed_temples")
    temple = relationship("Temple", back_populates="followers")

    __table_args__ = (
        UniqueConstraint("user_id", "temple_id", name="uq_temple_follower"),
    )


class TempleFollowerPreference(Base):
    """Notification preferences for a temple follower."""
    __tablename__ = "temple_follower_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    follower_id = Column(UUID(as_uuid=True), ForeignKey("temple_followers.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    push_enabled = Column(Boolean, nullable=False, default=True)
    festival_enabled = Column(Boolean, nullable=False, default=True)
    announcement_enabled = Column(Boolean, nullable=False, default=True)
    event_enabled = Column(Boolean, nullable=False, default=True)
    pooja_reminder_enabled = Column(Boolean, nullable=False, default=True)
    custom_categories = Column(JSONB_VARIANT, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    follower = relationship("TempleFollower", backref=backref("preferences", uselist=False, cascade="all, delete-orphan"))


class ServiceRecommendation(Base):
    """Association table mapping services/products to recommended services or products."""
    __tablename__ = "service_recommendations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    source_service_id = Column(UUID(as_uuid=True), ForeignKey("temple_services.id", ondelete="CASCADE"), nullable=True)
    source_product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=True)
    recommendation_source_type = Column(String(20), nullable=False, default="SERVICE")
    recommended_service_id = Column(UUID(as_uuid=True), ForeignKey("temple_services.id", ondelete="CASCADE"), nullable=True)
    recommended_product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "(source_service_id IS NOT NULL AND source_product_id IS NULL) OR "
            "(source_product_id IS NOT NULL AND source_service_id IS NULL)",
            name="chk_recommendation_source"
        ),
        CheckConstraint(
            "(recommended_service_id IS NOT NULL AND recommended_product_id IS NULL) OR "
            "(recommended_product_id IS NOT NULL AND recommended_service_id IS NULL)",
            name="chk_recommendation_target"
        ),
        Index("idx_service_recommendations_lookup", "temple_id", "source_service_id", postgresql_where=text("is_active = TRUE")),
        Index("idx_product_recommendations_lookup", "temple_id", "source_product_id", postgresql_where=text("is_active = TRUE")),
    )

    temple = relationship("Temple", back_populates="recommendations")
    source_service = relationship("TempleService", foreign_keys=[source_service_id])
    source_product = relationship("StoreProduct", foreign_keys=[source_product_id])
    recommended_service = relationship("TempleService", foreign_keys=[recommended_service_id])
    recommended_product = relationship("StoreProduct", foreign_keys=[recommended_product_id])


class PlatformAdvertisement(Base):
    """Advertisements managed by Super Admins shown across the platform."""
    __tablename__ = "platform_advertisements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    placement = Column(String(50), nullable=False) # 'HEADER_LEADERBOARD', 'TEMPLE_LIST_INLINE', 'TEMPLE_LIST_FOOTER'
    media_urls = Column(JSONB_VARIANT, nullable=False, default=list) # JSON array of image URLs
    media_type = Column(String(20), nullable=False, default="IMAGE")
    target_url = Column(String(500), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    approval_status = Column(String(20), nullable=False, default="APPROVED") # DRAFT, PENDING_REVIEW, APPROVED, REJECTED, PAUSED, EXPIRED
    approval_remarks = Column(Text, nullable=True)
    priority = Column(String(20), nullable=False, default="MEDIUM") # HIGH, MEDIUM, LOW
    scheduling_rules = Column(JSON, nullable=True)
    impression_cap = Column(Integer, nullable=True)
    click_cap = Column(Integer, nullable=True)
    cpm_rate = Column(Float, nullable=False, default=0.0)
    cpc_rate = Column(Float, nullable=False, default=0.0)
    billing_contact = Column(String(200), nullable=True)
    revenue_attribution = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(
            "media_type IN ('IMAGE', 'CAROUSEL', 'VIDEO')",
            name="chk_platform_ad_media_type"
        ),
    )


class TempleAdvertisement(Base):
    """Advertisements managed by Temple Admins for their specific portal page."""
    __tablename__ = "temple_advertisements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    placement = Column(String(50), nullable=False)
    # Canonical placement registry (keep in sync with frontend AdvertisementPlacementResolver):
    #   'TEMPLE_DETAILS_AFTER_ABOUT'    — banner between About and Activities sections
    #   'TEMPLE_DETAILS_BEFORE_GALLERY' — banner immediately before Gallery section
    #   'TEMPLE_DETAILS_INLINE'         — header leaderboard / top-of-page banner
    #   'SIDEBAR_SPOTLIGHT'             — Phase 1 right-rail sidebar (beside About + Activities)
    media_urls = Column(JSONB_VARIANT, nullable=False, default=list) # JSON array of image URLs
    media_type = Column(String(20), nullable=False, default="IMAGE")
    target_url = Column(String(500), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    approval_status = Column(String(20), nullable=False, default="PENDING") # DRAFT, PENDING_REVIEW, APPROVED, REJECTED, PAUSED, EXPIRED
    approval_remarks = Column(Text, nullable=True)
    priority = Column(String(20), nullable=False, default="MEDIUM") # HIGH, MEDIUM, LOW
    scheduling_rules = Column(JSON, nullable=True)
    impression_cap = Column(Integer, nullable=True)
    click_cap = Column(Integer, nullable=True)
    cpm_rate = Column(Float, nullable=False, default=0.0)
    cpc_rate = Column(Float, nullable=False, default=0.0)
    billing_contact = Column(String(200), nullable=True)
    revenue_attribution = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_temple_ads_active", "temple_id", "start_date", "end_date", postgresql_where=text("is_active = TRUE")),
        CheckConstraint(
            "media_type IN ('IMAGE', 'CAROUSEL', 'VIDEO')",
            name="chk_temple_ad_media_type"
        ),
    )

    temple = relationship("Temple", back_populates="advertisements")


@event.listens_for(PlatformAdvertisement, "before_insert")
@event.listens_for(PlatformAdvertisement, "before_update")
def validate_platform_ad_media(mapper, connection, target):
    if target.media_type is None:
        target.media_type = "IMAGE"
    media_type = target.media_type
    media_urls = target.media_urls
    if not isinstance(media_urls, list):
        raise ValueError("media_urls must be a list of strings")
    if media_type == "IMAGE" or media_type == "VIDEO":
        if len(media_urls) != 1:
            raise ValueError(f"{media_type} platform advertisement must contain exactly 1 media URL")
    elif media_type == "CAROUSEL":
        if len(media_urls) < 2:
            raise ValueError("CAROUSEL platform advertisement must contain at least 2 media URLs")
    else:
        raise ValueError(f"Invalid media_type: {media_type}")


@event.listens_for(TempleAdvertisement, "before_insert")
@event.listens_for(TempleAdvertisement, "before_update")
def validate_temple_ad_media(mapper, connection, target):
    if target.media_type is None:
        target.media_type = "IMAGE"
    media_type = target.media_type
    media_urls = target.media_urls
    if not isinstance(media_urls, list):
        raise ValueError("media_urls must be a list of strings")
    if media_type == "IMAGE" or media_type == "VIDEO":
        if len(media_urls) != 1:
            raise ValueError(f"{media_type} temple advertisement must contain exactly 1 media URL")
    elif media_type == "CAROUSEL":
        if len(media_urls) < 2:
            raise ValueError("CAROUSEL temple advertisement must contain at least 2 media URLs")
    else:
        raise ValueError(f"Invalid media_type: {media_type}")


class AdvertisementAnalytics(Base):
    """Analytics logging for platform and temple advertisements."""
    __tablename__ = "advertisement_analytics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    advertisement_type = Column(String(20), nullable=False) # 'PLATFORM', 'TEMPLE'
    platform_advertisement_id = Column(UUID(as_uuid=True), ForeignKey("platform_advertisements.id", ondelete="SET NULL"), nullable=True)
    temple_advertisement_id = Column(UUID(as_uuid=True), ForeignKey("temple_advertisements.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(20), nullable=False) # 'IMPRESSION', 'CLICK'
    visitor_hash = Column(String(64), nullable=False)
    session_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "(advertisement_type = 'PLATFORM' AND platform_advertisement_id IS NOT NULL AND temple_advertisement_id IS NULL) OR "
            "(advertisement_type = 'TEMPLE' AND temple_advertisement_id IS NOT NULL AND platform_advertisement_id IS NULL)",
            name="chk_ad_analytics_owner"
        ),
        Index("idx_ad_analytics_agg", "platform_advertisement_id", "temple_advertisement_id", "event_type", "created_at"),
    )

    platform_advertisement = relationship("PlatformAdvertisement", backref="analytics")
    temple_advertisement = relationship("TempleAdvertisement", backref="analytics")


# ====================================================================
# CART & ADDRESS — Store / booking checkout
# ====================================================================


class PortalAnalyticsEventType(str, enum.Enum):
    BOOK_POOJA_CLICK = "BOOK_POOJA_CLICK"
    OFFERING_CLICK = "OFFERING_CLICK"
    STORE_CLICK = "STORE_CLICK"
    FOLLOW_CLICK = "FOLLOW_CLICK"
    AD_CLICK = "AD_CLICK"
    RECOMMENDATION_CLICK = "RECOMMENDATION_CLICK"
    CHECKOUT_STARTED = "CHECKOUT_STARTED"
    CHECKOUT_COMPLETED = "CHECKOUT_COMPLETED"


class PortalAnalyticsEvent(Base):
    """Devotee interaction events for portal telemetry."""
    __tablename__ = "portal_analytics_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="SET NULL"), nullable=True)
    event_name = Column(String(50), nullable=False)
    visitor_hash = Column(String(64), nullable=False)
    session_id = Column(String(100), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_metadata = Column(JSONB_VARIANT, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "event_name IN ("
            "'BOOK_POOJA_CLICK', 'OFFERING_CLICK', 'STORE_CLICK', "
            "'FOLLOW_CLICK', 'AD_CLICK', 'RECOMMENDATION_CLICK', "
            "'CHECKOUT_STARTED', 'CHECKOUT_COMPLETED'"
            ")",
            name="chk_portal_event_name"
        ),
        Index("idx_portal_analytics_lookup", "temple_id", "event_name", "created_at"),
    )

    temple = relationship("Temple")
    user = relationship("User")


class CampaignRevenueMetrics(Base):
    """Immutable aggregate model capturing clicks, impressions, and calculated revenue attribution."""
    __tablename__ = "campaign_revenue_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_type = Column(String(20), nullable=False) # 'PLATFORM' or 'TEMPLE'
    total_impressions = Column(Integer, nullable=False, default=0)
    total_clicks = Column(Integer, nullable=False, default=0)
    estimated_revenue = Column(Float, nullable=False, default=0.0)
    last_calculated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


