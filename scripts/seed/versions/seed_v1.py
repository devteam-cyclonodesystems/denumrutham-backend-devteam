import uuid
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_password_hash
from app.models.domain import (
    User, Temple, TempleProfile, TempleWebsiteSettings, TempleWebsiteSettingsLive,
    TempleAnnouncement, TempleActivity, StateMaster, DistrictMaster, TempleFollower,
    TempleClaimRequest, TempleSuggestion, TempleSuggestionImage, TempleSuggestionContact,
    TempleSuggestionAudit, TempleService, ServiceBooking, ServiceBookingStatus,
    Notification, UserTemple
)
from app.modules.bookings.models.booking_models import DevoteeProfile, Devotee, ServiceBookingStatus, NotificationMode, BookingSource
from app.modules.temple_management.models.offering import OfferingCategory, Offering
from app.modules.governance.models.governance_models import TempleSuggestionStatus
from app.modules.auth.models.system_rbac import SystemRole

logger = logging.getLogger("Seed.V1")

async def seed_v1(db: AsyncSession, super_admin_id: uuid.UUID) -> dict:
    """
    Seeds version 1.0.0 canonical UAT dataset.
    Returns a dictionary of count metrics for the manifest.
    """
    metrics = {
        "dataset_version": "1.0.0",
        "temples": 0,
        "suggestions": 0,
        "claims": 0,
        "bookings": 0,
        "offerings": 0,
        "notifications": 0,
        "followers": 0
    }

    # 1. Fetch system roles
    role_admin = (await db.execute(select(SystemRole).filter(SystemRole.name == "TEMPLE_ADMIN"))).scalars().first()
    role_devotee = (await db.execute(select(SystemRole).filter(SystemRole.name == "DEVOTEE"))).scalars().first()

    # 2. Seed State and Districts if they do not exist
    state_kl = (await db.execute(select(StateMaster).filter(StateMaster.code == "KL"))).scalars().first()
    if not state_kl:
        state_kl = StateMaster(
            id=uuid.uuid4(),
            name="Kerala",
            slug="kerala",
            code="KL"
        )
        db.add(state_kl)
        await db.flush()
    
    districts = [
        {"name": "Thiruvananthapuram", "slug": "thiruvananthapuram", "code": "TVM"},
        {"name": "Kollam", "slug": "kollam", "code": "KLM"},
        {"name": "Pathanamthitta", "slug": "pathanamthitta", "code": "PTA"},
        {"name": "Alappuzha", "slug": "alappuzha", "code": "ALP"},
        {"name": "Kottayam", "slug": "kottayam", "code": "KTM"},
        {"name": "Idukki", "slug": "idukki", "code": "IDK"},
        {"name": "Ernakulam", "slug": "ernakulam", "code": "EKM"},
        {"name": "Thrissur", "slug": "thrissur", "code": "TCR"},
        {"name": "Palakkad", "slug": "palakkad", "code": "PKD"},
        {"name": "Malappuram", "slug": "malappuram", "code": "MPM"},
        {"name": "Kozhikode", "slug": "kozhikode", "code": "KKD"},
        {"name": "Wayanad", "slug": "wayanad", "code": "WYD"},
        {"name": "Kannur", "slug": "kannur", "code": "KNR"},
        {"name": "Kasaragod", "slug": "kasaragod", "code": "KSD"}
    ]
    district_objs = {}
    for dist in districts:
        d_obj = (await db.execute(select(DistrictMaster).filter(
            DistrictMaster.state_id == state_kl.id,
            DistrictMaster.code == dist["code"]
        ))).scalars().first()
        if not d_obj:
            d_obj = DistrictMaster(
                id=uuid.uuid4(),
                state_id=state_kl.id,
                name=dist["name"],
                slug=dist["slug"],
                code=dist["code"]
            )
            db.add(d_obj)
            await db.flush()
        district_objs[dist["code"]] = d_obj

    # 3. Create Temple Managers & Devotee Users
    manager_email = "manager@demotemple.org"
    manager_user = (await db.execute(select(User).filter(User.email == manager_email))).scalars().first()
    if not manager_user:
        manager_user = User(
            id=uuid.uuid4(),
            user_id="manager",
            name="Seeded Temple Manager",
            email=manager_email,
            phone="+919999999998",
            password_hash=get_password_hash("ManagerPass@2026"),
            role="TEMPLE_MANAGER",
            system_role_id=role_admin.id if role_admin else None,
            status="ACTIVE",
            is_active=True,
            approval_status="APPROVED"
        )
        db.add(manager_user)
        await db.flush()

    devotee_email = "devotee@example.com"
    devotee_user = (await db.execute(select(User).filter(User.email == devotee_email))).scalars().first()
    if not devotee_user:
        devotee_user = User(
            id=uuid.uuid4(),
            user_id="devotee",
            name="Seeded Devotee",
            email=devotee_email,
            phone="+919876543210",
            password_hash=get_password_hash("DevoteePass@2026"),
            role="DEVOTEE",
            system_role_id=role_devotee.id if role_devotee else None,
            status="ACTIVE",
            is_active=True,
            approval_status="APPROVED"
        )
        db.add(devotee_user)
        await db.flush()
        
        # Devotee Profile
        devotee_profile = DevoteeProfile(
            id=uuid.uuid4(),
            user_id=devotee_user.id,
            name=devotee_user.name,
            nakshatra="Rohini",
            gothram="Kashyapa",
            address="Vaikom, Kottayam, Kerala"
        )
        db.add(devotee_profile)
        await db.flush()

    # 4. Seed Temples
    # Temple A - DIRECTORY_TEMPLATE (Stage 1)
    temple_a = Temple(
        id=uuid.uuid4(),
        name="Sree Dharma Sastha Sabarimala",
        domain="sabarimala-sree-dharma-sastha",
        location="Sabarimala, Pathanamthitta, Kerala",
        state="Kerala",
        district="Pathanamthitta",
        status="APPROVED",
        is_active=True,
        management_mode="DIRECTORY_ONLY",
        created_by=super_admin_id
    )
    db.add(temple_a)
    metrics["temples"] += 1

    profile_a = TempleProfile(
        temple_id=temple_a.id,
        description="Ancient hill shrine dedicated to Lord Ayyappa.",
        history="Sabarimala is situated on a hilltop in the Western Ghats mountain ranges.",
        location=temple_a.location,
        district=temple_a.district,
        state=temple_a.state,
        opening_time="04:00",
        closing_time="22:00"
    )
    db.add(profile_a)

    settings_a_draft = TempleWebsiteSettings(
        id=uuid.uuid4(),
        temple_id=temple_a.id,
        theme_name="default",
        primary_color="#ff6600",
        secondary_color="#ffcc00",
        hero_title=temple_a.name,
        hero_subtitle="Pathanamthitta, Kerala",
        section_order=["hero", "about", "timings", "gallery", "location"],
        feature_visibility={"enablePoojaBooking": False, "enableOfferings": False, "enableStore": False, "enableHallBooking": False, "enableFollow": True}
    )
    db.add(settings_a_draft)

    # Temple B - DENUMRUTHAM_MANAGED (Stage 2 - Curation Overrides)
    temple_b = Temple(
        id=uuid.uuid4(),
        name="Alappuzha Sree Krishna Temple",
        domain="alappuzha-sree-krishna",
        location="Alappuzha, Kerala",
        state="Kerala",
        district="Alappuzha",
        status="APPROVED",
        is_active=True,
        management_mode="DIRECTORY_ONLY",
        created_by=super_admin_id
    )
    db.add(temple_b)
    metrics["temples"] += 1

    profile_b = TempleProfile(
        temple_id=temple_b.id,
        description="Historical shrine curation by Denumrutham admin.",
        location=temple_b.location,
        district=temple_b.district,
        state=temple_b.state,
        opening_time="05:00",
        closing_time="20:00"
    )
    db.add(profile_b)

    settings_b_draft = TempleWebsiteSettings(
        id=uuid.uuid4(),
        temple_id=temple_b.id,
        theme_name="sunset",
        primary_color="#e056fd",
        secondary_color="#be2edd",
        hero_title=temple_b.name,
        hero_subtitle="Curated by Admin",
        section_order=["hero", "about", "timings", "gallery", "location"],
        feature_visibility={"enablePoojaBooking": False, "enableOfferings": False, "enableStore": False, "enableHallBooking": False, "enableFollow": True}
    )
    db.add(settings_b_draft)

    settings_b_live = TempleWebsiteSettingsLive(
        id=settings_b_draft.id,
        temple_id=temple_b.id,
        settings_snapshot={
            "theme_name": "sunset",
            "primary_color": "#e056fd",
            "secondary_color": "#be2edd",
            "hero_title": temple_b.name,
            "hero_subtitle": "Curated by Admin",
            "section_order": ["hero", "about", "timings", "gallery", "location"],
            "featureVisibility": {"enablePoojaBooking": False, "enableOfferings": False, "enableStore": False, "enableHallBooking": False, "enableFollow": True},
            "hero_layout": "split",
            "enable_mantras": True,
            "enable_festivals": True,
            "enable_donations": True,
            "enable_hall_booking": True,
            "enable_store": True,
        },
        version=1,
        published_at=datetime.now(timezone.utc)
    )
    db.add(settings_b_live)

    # Temple B Announcements and Activities for curation testing
    announcement_b = TempleAnnouncement(
        id=uuid.uuid4(),
        temple_id=temple_b.id,
        title="Utsavam Timings Update",
        content="Darshan timings extended for seasonal festival.",
        is_active=True
    )
    db.add(announcement_b)

    activity_b = TempleActivity(
        id=uuid.uuid4(),
        temple_id=temple_b.id,
        title="Nirmalya Darshanam",
        description="Morning sacred view of Sree Krishna.",
        activity_date=datetime.now(timezone.utc).date(),
        is_active=True
    )
    db.add(activity_b)

    # Temple C - TEMPLE_MANAGED (Stage 3 - Active commerce and linked manager)
    temple_c = Temple(
        id=uuid.uuid4(),
        name="Vaikom Mahadeva Temple",
        domain="vaikom-mahadeva",
        location="Vaikom, Kottayam, Kerala",
        state="Kerala",
        district="Kottayam",
        status="APPROVED",
        is_active=True,
        management_mode="SELF_MANAGED",
        created_by=super_admin_id
    )
    db.add(temple_c)
    metrics["temples"] += 1

    profile_c = TempleProfile(
        temple_id=temple_c.id,
        description="Famous Vaikom Mahadeva temple representing Shaivite heritage.",
        location=temple_c.location,
        district=temple_c.district,
        state=temple_c.state,
        opening_time="04:30",
        closing_time="21:30"
    )
    db.add(profile_c)

    settings_c_draft = TempleWebsiteSettings(
        id=uuid.uuid4(),
        temple_id=temple_c.id,
        theme_name="forest",
        primary_color="#2ecc71",
        secondary_color="#27ae60",
        hero_title=temple_c.name,
        hero_subtitle="Welcome to Vaikom",
        section_order=["hero", "about", "timings", "poojas", "gallery", "location"],
        feature_visibility={"enablePoojaBooking": True, "enableOfferings": True, "enableStore": False, "enableHallBooking": False, "enableFollow": True}
    )
    db.add(settings_c_draft)

    settings_c_live = TempleWebsiteSettingsLive(
        id=settings_c_draft.id,
        temple_id=temple_c.id,
        settings_snapshot={
            "theme_name": "forest",
            "primary_color": "#2ecc71",
            "secondary_color": "#27ae60",
            "hero_title": temple_c.name,
            "hero_subtitle": "Welcome to Vaikom",
            "section_order": ["hero", "about", "timings", "poojas", "gallery", "location"],
            "featureVisibility": {"enablePoojaBooking": True, "enableOfferings": True, "enableStore": False, "enableHallBooking": False, "enableFollow": True},
            "hero_layout": "split",
            "enable_mantras": True,
            "enable_festivals": True,
            "enable_donations": True,
            "enable_hall_booking": True,
            "enable_store": True,
        },
        version=1,
        published_at=datetime.now(timezone.utc)
    )
    db.add(settings_c_live)
    await db.flush()

    # Link manager user to Temple C
    manager_user.temple_id = temple_c.id
    mapping = UserTemple(
        id=uuid.uuid4(),
        user_id=manager_user.id,
        temple_id=temple_c.id,
        role="TEMPLE_MANAGER",
        is_active=True
    )
    db.add(mapping)

    # Pooja Configurations (Temple Services) for Temple C
    pooja_1 = TempleService(
        id=uuid.uuid4(),
        temple_id=temple_c.id,
        service_name="Maha Ganapathi Homam",
        service_type="ARCHANA",
        price=500.0,
        description="Ritual for removing all obstacles.",
        active=True
    )
    pooja_2 = TempleService(
        id=uuid.uuid4(),
        temple_id=temple_c.id,
        service_name="Neyyabhishekam",
        service_type="ARCHANA",
        price=250.0,
        description="Ghee abhishekam for purification.",
        active=True
    )
    db.add(pooja_1)
    db.add(pooja_2)
    await db.flush()

    # Seed 1 Completed Pooja Booking
    booking_1 = ServiceBooking(
        id=uuid.uuid4(),
        temple_id=temple_c.id,
        devotee_user_id=devotee_user.id,
        service_id=pooja_1.id,
        booking_date=datetime.now(timezone.utc),
        amount=500.0,
        status=ServiceBookingStatus.PAID,
        devotee_name=devotee_user.name,
        devotee_phone=devotee_user.phone,
        notes="Pradakshina priority",
        notification_mode=NotificationMode.EMAIL,
        notification_destination=devotee_user.email,
        booking_source=BookingSource.WEB_PUBLIC
    )
    db.add(booking_1)
    metrics["bookings"] += 1

    # Seed 1 Pending Pooja Booking
    booking_2 = ServiceBooking(
        id=uuid.uuid4(),
        temple_id=temple_c.id,
        devotee_user_id=devotee_user.id,
        service_id=pooja_2.id,
        booking_date=datetime.now(timezone.utc) + timedelta(days=1),
        amount=250.0,
        status=ServiceBookingStatus.PENDING,
        devotee_name=devotee_user.name,
        devotee_phone=devotee_user.phone,
        notes="Morning slot preferred",
        notification_mode=NotificationMode.EMAIL,
        notification_destination=devotee_user.email,
        booking_source=BookingSource.WEB_PUBLIC
    )
    db.add(booking_2)
    metrics["bookings"] += 1

    # Seed 1 Completed Offering (Vazhipadu)
    offering_cat = OfferingCategory(
        id=uuid.uuid4(),
        temple_id=temple_c.id,
        category_name="Vazhipadu",
        category_code="VZP",
        receipt_prefix="VZP-",
        is_active=True
    )
    db.add(offering_cat)
    await db.flush()

    offering_1 = Offering(
        id=uuid.uuid4(),
        temple_id=temple_c.id,
        offering_number="OFF-2026-0001",
        donor_name="Hari Kumar",
        donor_phone=devotee_user.phone,
        donor_email=devotee_user.email,
        offering_type="VAZHIPADU",
        category_id=offering_cat.id,
        total_amount=50.0,
        paid_amount=50.0,
        payment_status="PAID",
        payment_method="UPI",
        booking_mode="WEB_PUBLIC"
    )
    db.add(offering_1)
    metrics["offerings"] += 1

    # Seed 1 Notification for devotee
    notif = Notification(
        id=uuid.uuid4(),
        user_id=devotee_user.id,
        temple_id=temple_c.id,
        title="Offering Confirmed",
        message="Your vazhipadu offering was successfully verified and scheduled.",
        is_read=False
    )
    db.add(notif)
    metrics["notifications"] += 1

    # Temple D - Redirect target
    temple_d = Temple(
        id=uuid.uuid4(),
        name="Ambalappuzha Sree Krishna Temple",
        domain="ambalappuzha-sree-krishna",
        location="Ambalappuzha, Alappuzha, Kerala",
        state="Kerala",
        district="Alappuzha",
        status="APPROVED",
        is_active=True,
        management_mode="DIRECTORY_ONLY",
        created_by=super_admin_id
    )
    db.add(temple_d)
    metrics["temples"] += 1

    profile_d = TempleProfile(
        temple_id=temple_d.id,
        description="Famed shrine representing standard directory mappings.",
        location=temple_d.location,
        district=temple_d.district,
        state=temple_d.state,
        opening_time="05:00",
        closing_time="20:00"
    )
    db.add(profile_d)

    # Temple E - Merged Duplicate (Redirecting to Temple D)
    temple_e = Temple(
        id=uuid.uuid4(),
        name="Ambalapuzha Krishna Temple",
        domain="ambalapuzha-krishna-duplicate",
        location="Ambalappuzha, Kerala",
        state="Kerala",
        district="Alappuzha",
        status="MERGED",
        is_active=True,
        management_mode="DIRECTORY_ONLY",
        merged_temple_id=temple_d.id,
        created_by=super_admin_id
    )
    db.add(temple_e)
    metrics["temples"] += 1

    # Temple F - Archived/Disabled Temple (Inactive Search target)
    temple_f = Temple(
        id=uuid.uuid4(),
        name="Old Inactive Shrine",
        domain="old-inactive-shrine",
        location="Kochi, Kerala",
        state="Kerala",
        district="Ernakulam",
        status="APPROVED",
        is_active=False,
        created_by=super_admin_id
    )
    db.add(temple_f)
    metrics["temples"] += 1

    profile_f = TempleProfile(
        temple_id=temple_f.id,
        description="Historical shrine that is currently inactive and locked.",
        location=temple_f.location,
        district=temple_f.district,
        state=temple_f.state
    )
    db.add(profile_f)

    # 5. Seed Temple Suggestions
    # Suggestion 1 - PENDING
    sug_1 = TempleSuggestion(
        id=uuid.uuid4(),
        reference_number="TS-2026-KL-000001",
        name="Chottanikkara Bhagavathy Temple",
        deity="Bhagavathy",
        description="Famous Bhagavathy temple situated in Kochi.",
        address_line_1="Chottanikkara",
        village_town="Kochi",
        district_id=district_objs["EKM"].id,
        state_id=state_kl.id,
        pincode="682312",
        submitted_by=devotee_user.id,
        submitter_affiliation="Devotee devotee",
        confidence_score=40,
        original_submission_json={"name": "Chottanikkara Bhagavathy Temple", "deity": "Bhagavathy", "pincode": "682312"},
        status=TempleSuggestionStatus.PENDING
    )
    db.add(sug_1)
    metrics["suggestions"] += 1

    # Suggestion 2 - APPROVED (Promoted to Temple B)
    sug_2 = TempleSuggestion(
        id=uuid.uuid4(),
        reference_number="TS-2026-KL-000002",
        name="Alappuzha Sree Krishna Temple",
        deity="Krishna",
        description="Historical Krishna temple.",
        address_line_1="Alappuzha Junction",
        village_town="Alappuzha",
        district_id=district_objs["ALP"].id,
        state_id=state_kl.id,
        pincode="688001",
        submitted_by=devotee_user.id,
        submitter_ip="127.0.0.1",
        submitter_affiliation="Local Resident",
        confidence_score=60,
        original_submission_json={"name": "Alappuzha Sree Krishna Temple"},
        status=TempleSuggestionStatus.APPROVED,
        promoted_temple_id=temple_b.id,
        reviewed_by=super_admin_id,
        reviewed_at=datetime.now(timezone.utc)
    )
    db.add(sug_2)
    metrics["suggestions"] += 1

    # Suggestion 3 - REJECTED
    sug_3 = TempleSuggestion(
        id=uuid.uuid4(),
        reference_number="TS-2026-KL-000003",
        name="Sabarimala Duplicate Temple",
        deity="Ayyappa",
        description="Duplicate submission testing.",
        address_line_1="Sabarimala Hills",
        village_town="Sabarimala",
        district_id=district_objs["PTA"].id,
        state_id=state_kl.id,
        pincode="689662",
        submitted_by=devotee_user.id,
        submitter_affiliation="Devotee",
        confidence_score=30,
        original_submission_json={"name": "Sabarimala Duplicate"},
        status=TempleSuggestionStatus.REJECTED,
        rejection_reason="Duplicate entry",
        reviewed_by=super_admin_id,
        reviewed_at=datetime.now(timezone.utc)
    )
    db.add(sug_3)
    metrics["suggestions"] += 1

    # 6. Seed Claims
    # Claim 1 - PENDING
    claim_1 = TempleClaimRequest(
        id=uuid.uuid4(),
        temple_id=temple_a.id,
        claimant_id=manager_user.id,
        status="PENDING",
        proof_urls=["/static/uploads/legal_deed_claim1.pdf"],
        target_management_mode="SELF_MANAGED",
        target_subscription_plan="SELF_MANAGED_ENTERPRISE",
        claimant_notes="We are the traditional board trustees of Sabarimala."
    )
    db.add(claim_1)
    metrics["claims"] += 1

    # Claim 2 - REJECTED
    claim_2 = TempleClaimRequest(
        id=uuid.uuid4(),
        temple_id=temple_a.id,
        claimant_id=manager_user.id,
        status="REJECTED",
        proof_urls=["/static/uploads/forged_document.pdf"],
        target_management_mode="SELF_MANAGED",
        target_subscription_plan="GOVERNED_STANDARD",
        claimant_notes="Unofficial claimant attempt.",
        reviewed_by=super_admin_id,
        reviewed_at=datetime.now(timezone.utc),
        rejection_reason="Insufficient legal proof"
    )
    db.add(claim_2)
    metrics["claims"] += 1

    # 7. Seed Followers
    follower_1 = TempleFollower(
        id=uuid.uuid4(),
        user_id=devotee_user.id,
        temple_id=temple_c.id,
        is_active=True
    )
    db.add(follower_1)
    metrics["followers"] += 1

    await db.flush()
    logger.info("[Seed] [V1] - Seeding successful.")
    return metrics
