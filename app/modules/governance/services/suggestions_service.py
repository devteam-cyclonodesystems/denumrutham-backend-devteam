"""
Suggestions Service Layer — Manages the devotee suggestion submission lifecycle.
"""
from typing import Optional
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app.models import Temple, User, StateMaster, DistrictMaster
from app.modules.governance.models.governance_models import (
    TempleSuggestion, TempleSuggestionContact, TempleSuggestionImage,
    TempleSuggestionAudit, TempleSuggestionStatus, Notification
)
from app.modules.governance.schemas.suggestions import (
    TempleSuggestionCreate, TempleSuggestionReview, DuplicateMatchResponse
)
from app.modules.temple_management.models.temple_models import TempleImage, ImageCategory, TempleProfile, TempleWebsiteSettings

def utcnow():
    return datetime.now(timezone.utc)

class SuggestionsService:
    @staticmethod
    def calculate_confidence_score(schema: TempleSuggestionCreate) -> int:
        score = 0
        # 1. Photo uploaded (+20)
        if schema.images:
            score += 20
        # 2. GPS Coords (+20)
        if schema.latitude is not None and schema.longitude is not None:
            score += 20
        # 3. Primary Contact (+20)
        if any(c.is_primary for c in schema.contacts) or schema.contacts:
            score += 20
        # 4. Secondary Contact (+10)
        if len(schema.contacts) > 1:
            score += 10
        # 5. Festival Info (+10)
        if schema.festival_info and schema.festival_info.strip():
            score += 10
        # 6. Website / Social Links (+10)
        has_social = False
        if schema.social_media_links:
            has_social = any(v for v in schema.social_media_links.values() if v)
        if (schema.website and schema.website.strip()) or has_social:
            score += 10
        # 7. Complete Address (+10)
        if (schema.address_line_1 and schema.address_line_1.strip() and
                schema.village_town and schema.village_town.strip() and
                schema.pincode and schema.pincode.strip()):
            score += 10
        return score

    @staticmethod
    async def get_fallback_temple_id(db: AsyncSession) -> UUID:
        """Finds any active temple ID to satisfy the foreign key constraint on notifications."""
        res = await db.execute(select(Temple.id).limit(1))
        temple_id = res.scalar()
        if not temple_id:
            # If no temple exists, we create a temporary system temple placeholder to prevent FK constraint failures
            fallback_temple = Temple(
                id=uuid4(),
                name="System Platform Placeholder",
                domain="system-platform-placeholder",
                management_mode="DIRECTORY_ONLY",
                is_active=True
            )
            db.add(fallback_temple)
            await db.flush()
            temple_id = fallback_temple.id
        return temple_id

    @staticmethod
    async def send_inapp_notification(db: AsyncSession, user_id: UUID, title: str, message: str, temple_id: Optional[UUID] = None):
        """Dispatches an in-app notification row linked to a user."""
        if not temple_id:
            temple_id = await SuggestionsService.get_fallback_temple_id(db)
        
        notif = Notification(
            id=uuid4(),
            temple_id=temple_id,
            user_id=user_id,
            title=title,
            message=message,
            is_read=False,
            created_at=utcnow()
        )
        db.add(notif)
        await db.flush()

    @staticmethod
    async def check_duplicates(db: AsyncSession, name: str, district_id: UUID, pincode: str) -> list[DuplicateMatchResponse]:
        clean_name = name.strip().lower()
        stmt = (
            select(Temple)
            .filter(Temple.is_active == True)
            .filter(or_(Temple.district_id == district_id, Temple.pincode == pincode))
        )
        res = await db.execute(stmt)
        temples = res.scalars().all()
        
        matches = []
        for t in temples:
            t_name = t.name.lower()
            # Fuzzy match if names contain each other
            if clean_name in t_name or t_name in clean_name:
                # Fetch district name
                d_stmt = select(DistrictMaster.name).filter(DistrictMaster.id == t.district_id)
                d_name = (await db.execute(d_stmt)).scalar() or ""
                matches.append(DuplicateMatchResponse(
                    temple_id=t.id,
                    name=t.name,
                    district=d_name,
                    pincode=t.pincode or "",
                    management_mode=t.management_mode
                ))
        return matches

    @staticmethod
    async def create_suggestion(db: AsyncSession, user_id: UUID, schema: TempleSuggestionCreate, client_ip: Optional[str] = None) -> TempleSuggestion:
        # 1. Rate limit check: max 3 submissions per devotee per 24 hours
        one_day_ago = utcnow() - timedelta(days=1)
        count_stmt = select(func.count(TempleSuggestion.id)).filter(
            TempleSuggestion.submitted_by == user_id,
            TempleSuggestion.created_at >= one_day_ago
        )
        count_res = await db.execute(count_stmt)
        if (count_res.scalar() or 0) >= 3:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded: Maximum 3 suggestions per devotee per day."
            )

        # 2. Get State Code for Reference Number
        state_stmt = select(StateMaster.code).filter(StateMaster.id == schema.state_id)
        state_code = (await db.execute(state_stmt)).scalar() or "XX"
        
        # 3. Sequence Number Generation
        year = utcnow().year
        seq_stmt = select(func.count(TempleSuggestion.id)).filter(
            TempleSuggestion.created_at >= datetime(year, 1, 1, tzinfo=timezone.utc)
        )
        seq_res = await db.execute(seq_stmt)
        seq_count = seq_res.scalar() or 0
        ref_num = f"TS-{year}-{state_code.upper()}-{seq_count + 1:06d}"

        # 4. Generate Confidence Score
        confidence = SuggestionsService.calculate_confidence_score(schema)

        # 5. Create suggestion
        suggestion = TempleSuggestion(
            id=uuid4(),
            reference_number=ref_num,
            name=schema.name.strip(),
            deity=schema.deity.strip(),
            description=schema.description,
            address_line_1=schema.address_line_1,
            address_line_2=schema.address_line_2,
            village_town=schema.village_town,
            district_id=schema.district_id,
            state_id=schema.state_id,
            pincode=schema.pincode,
            latitude=schema.latitude,
            longitude=schema.longitude,
            google_maps_url=schema.google_maps_url,
            website=schema.website,
            social_media_links=schema.social_media_links or {},
            festival_info=schema.festival_info,
            office_phone=schema.office_phone,
            submitter_affiliation=schema.submitter_affiliation,
            submitted_by=user_id,
            submitter_ip=client_ip,
            confidence_score=confidence,
            original_submission_json=schema.model_dump(mode="json"),
            status=TempleSuggestionStatus.PENDING,
            created_at=utcnow(),
            updated_at=utcnow()
        )
        db.add(suggestion)
        await db.flush()

        # Save staged contacts
        for idx, c in enumerate(schema.contacts):
            contact = TempleSuggestionContact(
                id=uuid4(),
                suggestion_id=suggestion.id,
                name=c.name.strip(),
                designation=c.designation.strip(),
                mobile_number=c.mobile_number.strip(),
                is_primary=c.is_primary if c.is_primary is not None else (idx == 0),
                created_at=utcnow()
            )
            db.add(contact)

        # Save staged images
        for idx, img in enumerate(schema.images or []):
            image = TempleSuggestionImage(
                id=uuid4(),
                suggestion_id=suggestion.id,
                image_url=img.image_url.strip(),
                is_primary=img.is_primary if img.is_primary is not None else (idx == 0),
                created_at=utcnow()
            )
            db.add(image)

        # Create submission audit log
        audit = TempleSuggestionAudit(
            id=uuid4(),
            suggestion_id=suggestion.id,
            action="SUBMIT",
            performed_by=user_id,
            notes=f"Devotee submitted temple suggestion (Ref: {ref_num})",
            created_at=utcnow()
        )
        db.add(audit)
        await db.flush()

        # Send submitter notification
        await SuggestionsService.send_inapp_notification(
            db=db,
            user_id=user_id,
            title="Temple Suggestion Submitted",
            message=f"We have received your temple suggestion for '{schema.name}'. Reference number: {ref_num}"
        )

        return suggestion

    @staticmethod
    async def list_suggestions(
        db: AsyncSession,
        status: Optional[str] = None,
        state_id: Optional[UUID] = None,
        district_id: Optional[UUID] = None,
        min_score: Optional[int] = None,
        max_score: Optional[int] = None,
        search_query: Optional[str] = None,
        sort_by: str = "newest",
        page: int = 1,
        limit: int = 10
    ) -> tuple[list[TempleSuggestion], int]:
        stmt = (
            select(TempleSuggestion)
            .options(
                selectinload(TempleSuggestion.contacts),
                selectinload(TempleSuggestion.images),
                selectinload(TempleSuggestion.state),
                selectinload(TempleSuggestion.district),
                selectinload(TempleSuggestion.submitter),
                selectinload(TempleSuggestion.reviewer)
            )
        )

        # Filtering
        if status:
            stmt = stmt.filter(TempleSuggestion.status == status.upper())
        if state_id:
            stmt = stmt.filter(TempleSuggestion.state_id == state_id)
        if district_id:
            stmt = stmt.filter(TempleSuggestion.district_id == district_id)
        if min_score is not None:
            stmt = stmt.filter(TempleSuggestion.confidence_score >= min_score)
        if max_score is not None:
            stmt = stmt.filter(TempleSuggestion.confidence_score <= max_score)
        if search_query:
            q = f"%{search_query.strip()}%"
            stmt = stmt.filter(or_(
                TempleSuggestion.name.ilike(q),
                TempleSuggestion.reference_number.ilike(q),
                TempleSuggestion.deity.ilike(q)
            ))

        # Sorting
        if sort_by == "highest_confidence":
            stmt = stmt.order_by(TempleSuggestion.confidence_score.desc(), TempleSuggestion.created_at.desc())
        elif sort_by == "lowest_confidence":
            stmt = stmt.order_by(TempleSuggestion.confidence_score.asc(), TempleSuggestion.created_at.desc())
        else:
            stmt = stmt.order_by(TempleSuggestion.created_at.desc())

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_res = await db.execute(count_stmt)
        total = count_res.scalar() or 0

        # Paginate
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)
        res = await db.execute(stmt)
        suggestions = res.scalars().all()

        # Decorate response names
        for s in suggestions:
            s.state_name = s.state.name if s.state else ""
            s.district_name = s.district.name if s.district else ""
            s.submitter_name = s.submitter.name if s.submitter else ""
            s.reviewer_name = s.reviewer.name if s.reviewer else ""

        return suggestions, total

    @staticmethod
    async def get_suggestion_details(db: AsyncSession, id: UUID) -> TempleSuggestion:
        stmt = (
            select(TempleSuggestion)
            .options(
                selectinload(TempleSuggestion.contacts),
                selectinload(TempleSuggestion.images),
                selectinload(TempleSuggestion.state),
                selectinload(TempleSuggestion.district),
                selectinload(TempleSuggestion.submitter),
                selectinload(TempleSuggestion.reviewer)
            )
            .filter(TempleSuggestion.id == id)
        )
        res = await db.execute(stmt)
        suggestion = res.scalars().first()
        if not suggestion:
            raise HTTPException(status_code=404, detail="Temple suggestion not found")
        
        suggestion.state_name = suggestion.state.name if suggestion.state else ""
        suggestion.district_name = suggestion.district.name if suggestion.district else ""
        suggestion.submitter_name = suggestion.submitter.name if suggestion.submitter else ""
        suggestion.reviewer_name = suggestion.reviewer.name if suggestion.reviewer else ""
        return suggestion

    @staticmethod
    async def review_suggestion(
        db: AsyncSession,
        id: UUID,
        reviewer_id: UUID,
        review: TempleSuggestionReview
    ) -> TempleSuggestion:
        # Load suggestion
        stmt = (
            select(TempleSuggestion)
            .options(
                selectinload(TempleSuggestion.contacts),
                selectinload(TempleSuggestion.images),
                selectinload(TempleSuggestion.submitter),
                selectinload(TempleSuggestion.state),
                selectinload(TempleSuggestion.district)
            )
            .filter(TempleSuggestion.id == id)
        )
        res = await db.execute(stmt)
        suggestion = res.scalars().first()
        if not suggestion:
            raise HTTPException(status_code=404, detail="Temple suggestion not found")

        if suggestion.status != TempleSuggestionStatus.PENDING:
            raise HTTPException(status_code=400, detail="Suggestion has already been reviewed")

        # Snapshot before edits for change logging
        original_values = {
            "name": suggestion.name,
            "deity": suggestion.deity,
            "description": suggestion.description,
            "address_line_1": suggestion.address_line_1,
            "address_line_2": suggestion.address_line_2,
            "village_town": suggestion.village_town,
            "district_id": str(suggestion.district_id),
            "state_id": str(suggestion.state_id),
            "pincode": suggestion.pincode,
            "latitude": suggestion.latitude,
            "longitude": suggestion.longitude,
            "google_maps_url": suggestion.google_maps_url,
            "website": suggestion.website,
            "social_media_links": suggestion.social_media_links,
            "festival_info": suggestion.festival_info,
            "office_phone": suggestion.office_phone
        }

        # Apply inline edit overrides if provided by the admin
        edited_fields = {}
        for field in original_values.keys():
            override_val = getattr(review, field, None)
            if override_val is not None:
                current_val = getattr(suggestion, field)
                if override_val != current_val:
                    setattr(suggestion, field, override_val)
                    edited_fields[field] = {"old": current_val, "new": override_val}

        if edited_fields:
            # Audit the admin's edit override
            edit_audit = TempleSuggestionAudit(
                id=uuid4(),
                suggestion_id=suggestion.id,
                action="EDIT",
                performed_by=reviewer_id,
                change_diff=edited_fields,
                notes="Admin corrected suggestion details before final action",
                created_at=utcnow()
            )
            db.add(edit_audit)

        suggestion.reviewed_by = reviewer_id
        suggestion.reviewed_at = utcnow()
        suggestion.moderator_notes = review.moderator_notes
        suggestion.updated_at = utcnow()

        # Handle actions
        action_status = review.status.upper()
        if action_status in ("APPROVED", "APPROVE"):
            action_status = "APPROVED"
        elif action_status in ("REJECTED", "REJECT"):
            action_status = "REJECTED"
        elif action_status in ("MERGED", "MERGE"):
            action_status = "MERGED"

        if action_status == "REJECTED":
            if not review.rejection_reason or not review.rejection_reason.strip():
                raise HTTPException(status_code=400, detail="Rejection reason is required for REJECTED status")
            suggestion.status = TempleSuggestionStatus.REJECTED
            suggestion.rejection_reason = review.rejection_reason.strip()
            
            # Audit log
            audit = TempleSuggestionAudit(
                id=uuid4(),
                suggestion_id=suggestion.id,
                action="REJECT",
                performed_by=reviewer_id,
                notes=f"Suggestion rejected. Reason: {suggestion.rejection_reason}",
                created_at=utcnow()
            )
            db.add(audit)
            await db.flush()

            # Notify devotee
            await SuggestionsService.send_inapp_notification(
                db=db,
                user_id=suggestion.submitted_by,
                title="Temple Suggestion Rejected",
                message=f"Your temple suggestion '{suggestion.name}' was rejected. Reason: {suggestion.rejection_reason}"
            )

        elif action_status == "MERGED":
            if not review.merged_temple_id:
                raise HTTPException(status_code=400, detail="Target duplicate Temple ID is required for MERGED status")
            
            # Validate target temple exists
            target_stmt = select(Temple.id).filter(Temple.id == review.merged_temple_id)
            if not (await db.execute(target_stmt)).scalar():
                raise HTTPException(status_code=404, detail="Target temple for merge not found")
                
            suggestion.status = TempleSuggestionStatus.MERGED
            suggestion.merged_temple_id = review.merged_temple_id
            
            # Audit log
            audit = TempleSuggestionAudit(
                id=uuid4(),
                suggestion_id=suggestion.id,
                action="MERGE",
                performed_by=reviewer_id,
                notes=f"Suggestion merged into existing temple (ID: {review.merged_temple_id})",
                created_at=utcnow()
            )
            db.add(audit)
            await db.flush()

            # Notify devotee
            await SuggestionsService.send_inapp_notification(
                db=db,
                user_id=suggestion.submitted_by,
                title="Temple Suggestion Merged",
                message=f"Your temple suggestion '{suggestion.name}' was merged with an existing directory listing.",
                temple_id=review.merged_temple_id
            )

        elif action_status == "APPROVED":
            # 1. Approval-Time Duplicate Revalidation
            dup_stmt = select(Temple.id).filter(
                Temple.district_id == suggestion.district_id,
                Temple.name.ilike(suggestion.name),
                Temple.is_active == True
            )
            if (await db.execute(dup_stmt)).scalars().first():
                raise HTTPException(
                    status_code=400,
                    detail="A temple with this name already exists in this district/pincode. Approval blocked."
                )

            # Generate domain slug
            from app.modules.governance.services.superadmin_service import slugify
            domain_slug = slugify(suggestion.name)
            domain_check = await db.execute(select(Temple).filter(Temple.domain == domain_slug))
            if domain_check.scalars().first():
                domain_slug = f"{domain_slug}-{str(uuid4())[:6]}"

            # 2. Create Temple in DIRECTORY_ONLY mode
            new_temple = Temple(
                id=uuid4(),
                name=suggestion.name,
                domain=domain_slug,
                location=suggestion.village_town,
                state=None, # Loaded via state_id reference
                address_line_1=suggestion.address_line_1,
                address_line_2=suggestion.address_line_2,
                district=None, # Loaded via district_id reference
                pincode=suggestion.pincode,
                description=suggestion.description,
                status="APPROVED",
                is_active=True,
                created_by=suggestion.submitted_by,
                management_mode="DIRECTORY_ONLY",
                directory_status="ACTIVE",
                subscription_plan="FREE",
                verification_level=0, # Level 0 = Directory visibility
                creation_source="DEVOTEE_SUGGESTION",
                source_suggestion_id=suggestion.id,
                state_id=suggestion.state_id,
                district_id=suggestion.district_id,
                created_at=utcnow(),
                updated_at=utcnow()
            )
            db.add(new_temple)
            await db.flush()

            # Create TempleProfile record
            new_profile = TempleProfile(
                id=uuid4(),
                temple_id=new_temple.id,
                description=suggestion.description or "",
                location=suggestion.village_town or "",
                district=suggestion.district.name if suggestion.district else "",
                state=suggestion.state.name if suggestion.state else "",
                contact_number=suggestion.office_phone or "",
                latitude=suggestion.latitude,
                longitude=suggestion.longitude,
                website_url=suggestion.website or "",
                facebook_url=suggestion.social_media_links.get("facebook", "") if suggestion.social_media_links else "",
                instagram_url=suggestion.social_media_links.get("instagram", "") if suggestion.social_media_links else "",
                youtube_url=suggestion.social_media_links.get("youtube", "") if suggestion.social_media_links else "",
                twitter_url=suggestion.social_media_links.get("twitter", "") if suggestion.social_media_links else "",
                festivals_description=suggestion.festival_info or "",
                created_at=utcnow()
            )
            db.add(new_profile)

            # Create default TempleWebsiteSettings draft record
            default_settings = TempleWebsiteSettings(
                id=uuid4(),
                temple_id=new_temple.id,
                theme_name="default",
                primary_color="#ff6600",
                secondary_color="#ffcc00",
                logo_url=None,
                hero_layout="split",
                section_order=["hero", "about", "timings", "gallery", "location"],
                feature_visibility={
                    "enablePoojaBooking": False,
                    "enableOfferings": False,
                    "enableStore": False,
                    "enableHallBooking": False,
                    "enableFollow": True
                },
                enable_mantras=True,
                enable_festivals=True,
                enable_donations=True,
                enable_hall_booking=True,
                enable_store=True,
                hero_title=new_temple.name,
                hero_subtitle=new_temple.location,
                approval_status="DRAFT",
                created_at=utcnow(),
                updated_at=utcnow()
            )
            db.add(default_settings)

            # 3. Promote staged images to Temple gallery
            for staged_img in suggestion.images:
                production_img = TempleImage(
                    id=uuid4(),
                    temple_id=new_temple.id,
                    image_url=staged_img.image_url,
                    caption=f"Submitted by submitter (Suggestion Ref: {suggestion.reference_number})",
                    category=ImageCategory.GALLERY,
                    is_visible=True,
                    created_at=utcnow()
                )
                db.add(production_img)

            suggestion.status = TempleSuggestionStatus.APPROVED
            suggestion.promoted_temple_id = new_temple.id

            # 4. Audit Log
            audit = TempleSuggestionAudit(
                id=uuid4(),
                suggestion_id=suggestion.id,
                action="APPROVE",
                performed_by=reviewer_id,
                notes=f"Suggestion approved. Created Temple ID: {new_temple.id}",
                created_at=utcnow()
            )
            db.add(audit)
            await db.flush()

            # Notify devotee
            await SuggestionsService.send_inapp_notification(
                db=db,
                user_id=suggestion.submitted_by,
                title="Temple Suggestion Approved",
                message=f"Congratulations! Your temple suggestion '{suggestion.name}' was approved and added to the directory.",
                temple_id=new_temple.id
            )

        else:
            raise HTTPException(status_code=400, detail="Invalid review status action")

        await db.flush()
        return suggestion
