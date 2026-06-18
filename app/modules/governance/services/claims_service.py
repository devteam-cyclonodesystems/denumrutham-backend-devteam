"""
Claims Service Layer — Business logic for claimant submissions and admin reviews.
"""
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload

import hashlib
from app.modules.temple_management.models.temple_models import PortalAnalyticsEvent
from app.models import Temple, User, UserTemple, TempleClaimRequest, TempleOwnershipHistory, Subscription
from app.modules.governance.schemas.claims import ClaimRequestCreate, ClaimRequestReview


def utcnow():
    return datetime.now(timezone.utc)


class ClaimsService:
    """Service to manage temple ownership claims lifecycle."""

    @staticmethod
    async def submit_claim(
        db: AsyncSession,
        claimant_id: UUID,
        schema: ClaimRequestCreate,
        visitor_hash: str | None = None,
        session_id: str | None = None
    ) -> TempleClaimRequest:
        # 1. Fetch Temple and check it is DIRECTORY_ONLY
        temple_res = await db.execute(select(Temple).filter(Temple.id == schema.temple_id))
        temple = temple_res.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")

        if temple.management_mode != "DIRECTORY_ONLY":
            raise HTTPException(
                status_code=400,
                detail="Only DIRECTORY_ONLY temples can be claimed."
            )

        # 2. Duplicate Check: No pending claim can exist for this temple (by anyone)
        dup_stmt = select(TempleClaimRequest).filter(
            TempleClaimRequest.temple_id == schema.temple_id,
            TempleClaimRequest.status == "PENDING"
        )
        if (await db.execute(dup_stmt)).scalars().first():
            raise HTTPException(
                status_code=400,
                detail="Claim request for this temple already submitted. Thanks"
            )

        # 3. Rate Limit Check: Max 5 submissions per user in the last 24 hours
        one_day_ago = utcnow() - timedelta(days=1)
        count_stmt = select(func.count(TempleClaimRequest.id)).filter(
            TempleClaimRequest.claimant_id == claimant_id,
            TempleClaimRequest.created_at >= one_day_ago
        )
        count_res = await db.execute(count_stmt)
        claim_count = count_res.scalar() or 0
        if claim_count >= 5:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded: Maximum 5 claim submissions per user per day."
            )

        # 4. Create the claim request
        claim = TempleClaimRequest(
            id=uuid4(),
            temple_id=schema.temple_id,
            claimant_id=claimant_id,
            status="PENDING",
            proof_urls=schema.proof_urls,
            target_management_mode=schema.target_management_mode or "GOVERNED",
            target_subscription_plan=schema.target_subscription_plan or "GOVERNED_STANDARD",
            trial_duration_days=30,
            claimant_notes=schema.claimant_notes,
            created_at=utcnow(),
            updated_at=utcnow()
        )
        db.add(claim)
        await db.flush()
        
        # Populate relationship strings for response serialization
        claim.temple_name = temple.name
        user_res = await db.execute(select(User).filter(User.id == claimant_id))
        user = user_res.scalars().first()
        claim.claimant_name = user.name if user else ""
        claim.claimant_email = user.email if user else None
        claim.claimant_phone = user.phone if user else None

        # Telemetry: Log CLAIM_SUBMISSION
        vh = visitor_hash or hashlib.sha256(str(claimant_id).encode()).hexdigest()
        telemetry = PortalAnalyticsEvent(
            temple_id=schema.temple_id,
            event_name="CLAIM_SUBMISSION",
            visitor_hash=vh,
            session_id=session_id,
            user_id=claimant_id,
            event_metadata={
                "target_management_mode": schema.target_management_mode,
                "target_subscription_plan": schema.target_subscription_plan
            }
        )
        db.add(telemetry)

        return claim

    @staticmethod
    async def list_claims(
        db: AsyncSession,
        status_filter: str | None = None,
        claimant_id: UUID | None = None,
        page: int = 1,
        limit: int = 10
    ) -> tuple[list[TempleClaimRequest], int]:
        stmt = (
            select(TempleClaimRequest)
            .options(
                selectinload(TempleClaimRequest.temple),
                selectinload(TempleClaimRequest.claimant)
            )
            .order_by(TempleClaimRequest.created_at.desc())
        )
        
        if status_filter:
            stmt = stmt.filter(TempleClaimRequest.status == status_filter.upper())
        if claimant_id:
            stmt = stmt.filter(TempleClaimRequest.claimant_id == claimant_id)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_res = await db.execute(count_stmt)
        total = count_res.scalar() or 0

        # Paginate
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        claims = result.scalars().all()

        # Decorate claims with names
        for c in claims:
            c.temple_name = c.temple.name if c.temple else ""
            c.claimant_name = c.claimant.name if c.claimant else ""
            c.claimant_email = c.claimant.email if c.claimant else None
            c.claimant_phone = c.claimant.phone if c.claimant else None

        return claims, total

    @staticmethod
    async def review_claim(
        db: AsyncSession,
        claim_id: UUID,
        reviewer_id: UUID,
        schema: ClaimRequestReview
    ) -> TempleClaimRequest:
        # 1. Fetch claim request
        stmt = (
            select(TempleClaimRequest)
            .options(
                selectinload(TempleClaimRequest.temple),
                selectinload(TempleClaimRequest.claimant)
            )
            .filter(TempleClaimRequest.id == claim_id)
        )
        result = await db.execute(stmt)
        claim = result.scalars().first()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim request not found")

        if claim.status != "PENDING":
            raise HTTPException(status_code=400, detail="Claim request has already been reviewed")

        temple = claim.temple
        if not temple:
            raise HTTPException(status_code=404, detail="Associated temple not found")

        claim.reviewed_by = reviewer_id
        claim.reviewed_at = utcnow()
        claim.updated_at = utcnow()

        # 2. Process rejection
        if schema.status == "REJECTED":
            claim.status = "REJECTED"
            claim.rejection_reason = schema.rejection_reason or "Claim documentation insufficient."
            await db.flush()
            
            # Decorate
            claim.temple_name = temple.name
            claim.claimant_name = claim.claimant.name if claim.claimant else ""
            claim.claimant_email = claim.claimant.email if claim.claimant else None
            claim.claimant_phone = claim.claimant.phone if claim.claimant else None
            return claim

        # 3. Process approval
        target_mode = (schema.target_management_mode or claim.target_management_mode).upper()
        target_plan = schema.target_subscription_plan or claim.target_subscription_plan
        trial_days = schema.trial_duration_days if schema.trial_duration_days is not None else claim.trial_duration_days

        # Log to TempleOwnershipHistory
        history = TempleOwnershipHistory(
            id=uuid4(),
            temple_id=temple.id,
            previous_management_mode=temple.management_mode,
            new_management_mode=target_mode,
            previous_subscription_plan=temple.subscription_plan,
            new_subscription_plan=target_plan,
            changed_by=reviewer_id,
            reason=f"Approved claim request (claim_id: {claim.id})",
            changed_at=utcnow()
        )
        db.add(history)

        # Update temple parameters
        temple.management_mode = target_mode
        temple.subscription_plan = target_plan
        temple.directory_status = "ACTIVE"
        temple.is_active = True
        temple.verification_level = 2
        temple.version = (temple.version or 1) + 1
        temple.updated_at = utcnow()

        # 4. Automatically create or update a TRIALING subscription record
        sub_stmt = select(Subscription).filter(Subscription.temple_id == temple.id)
        sub_res = await db.execute(sub_stmt)
        sub = sub_res.scalars().first()
        
        trial_start_dt = utcnow()
        trial_end_dt = trial_start_dt + timedelta(days=trial_days)
        
        if not sub:
            sub = Subscription(
                id=uuid4(),
                temple_id=temple.id,
                subscription_plan=target_plan,
                status="TRIALING",
                trial_start=trial_start_dt,
                trial_end=trial_end_dt,
                grace_period_ends_at=None,
                created_at=utcnow(),
                updated_at=utcnow()
            )
            db.add(sub)
        else:
            sub.subscription_plan = target_plan
            sub.status = "TRIALING"
            sub.trial_start = trial_start_dt
            sub.trial_end = trial_end_dt
            sub.grace_period_ends_at = None
            sub.updated_at = utcnow()

        # Assign user role AT THE TEMPLE LEVEL only (using UserTemple mapping)
        # Claimant's global user.role remains DEVOTEE or whatever they had.
        mapping_stmt = select(UserTemple).filter(
            UserTemple.user_id == claim.claimant_id,
            UserTemple.temple_id == temple.id
        )
        mapping_res = await db.execute(mapping_stmt)
        mapping = mapping_res.scalars().first()
        
        if not mapping:
            mapping = UserTemple(
                id=uuid4(),
                user_id=claim.claimant_id,
                temple_id=temple.id,
                role="TEMPLE_MANAGER",
                is_active=True,
                created_at=utcnow()
            )
            db.add(mapping)
        else:
            mapping.role = "TEMPLE_MANAGER"
            mapping.is_active = True
            mapping.deleted_at = None

        # Set claimant primary temple context if they do not have one assigned yet
        claimant = claim.claimant
        if claimant and not claimant.temple_id:
            claimant.temple_id = temple.id

        claim.status = "APPROVED"
        claim.target_management_mode = target_mode
        claim.target_subscription_plan = target_plan
        claim.trial_duration_days = trial_days

        # Telemetry: Log CLAIM_APPROVED
        vh = hashlib.sha256(str(claim.claimant_id).encode()).hexdigest()
        telemetry = PortalAnalyticsEvent(
            temple_id=temple.id,
            event_name="CLAIM_APPROVED",
            visitor_hash=vh,
            user_id=claim.claimant_id,
            event_metadata={
                "claim_id": str(claim.id),
                "reviewer_id": str(reviewer_id),
                "management_mode": target_mode,
                "subscription_plan": target_plan
            }
        )
        db.add(telemetry)

        await db.flush()

        # Decorate
        claim.temple_name = temple.name
        claim.claimant_name = claim.claimant.name if claim.claimant else ""
        claim.claimant_email = claim.claimant.email if claim.claimant else None
        claim.claimant_phone = claim.claimant.phone if claim.claimant else None
        return claim
