import logging
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException

from app.models.domain import TempleLead, utcnow, TempleOwnershipHistory
from app.modules.governance.schemas.leads import LeadCreate, LeadUpdate

logger = logging.getLogger("tms.services.leads_service")

class LeadsService:
    """
    CRUD and operational services for managing temple leads pipeline (CRM).
    """

    @staticmethod
    async def create_lead(db: AsyncSession, lead_data: LeadCreate) -> TempleLead:
        """Create a new temple lead."""
        lead = TempleLead(
            temple_name=lead_data.temple_name,
            contact_person=lead_data.contact_person,
            phone=lead_data.phone,
            email=lead_data.email,
            state=lead_data.state,
            district=lead_data.district,
            interested_plan=lead_data.interested_plan,
            lead_source=lead_data.lead_source,
            follow_up_date=lead_data.follow_up_date,
            status=lead_data.status or "NEW",
            notes=lead_data.notes,
        )
        db.add(lead)
        await db.flush()
        logger.info(f"[LeadsService] [CREATE] - Lead created: {lead.id} ({lead.temple_name})")
        return lead

    @staticmethod
    async def get_lead(db: AsyncSession, lead_id: UUID) -> TempleLead | None:
        """Fetch a lead by ID."""
        result = await db.execute(select(TempleLead).filter(TempleLead.id == lead_id))
        return result.scalars().first()

    @staticmethod
    async def get_leads(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None
    ) -> tuple[list[TempleLead], int]:
        """Fetch list of leads with pagination and optional filtering by status."""
        query = select(TempleLead)
        if status:
            query = query.filter(TempleLead.status == status)
        
        # Count query
        count_query = select(func.count()).select_from(query.subquery())
        count_res = await db.execute(count_query)
        total = count_res.scalar_one()

        # Paginated query ordered by created_at desc
        paginated_query = query.order_by(TempleLead.created_at.desc()).offset(skip).limit(limit)
        res = await db.execute(paginated_query)
        leads = res.scalars().all()

        return list(leads), total

    @staticmethod
    async def update_lead(db: AsyncSession, lead_id: UUID, lead_data: LeadUpdate) -> TempleLead | None:
        """Update fields of an existing lead."""
        result = await db.execute(select(TempleLead).filter(TempleLead.id == lead_id))
        lead = result.scalars().first()
        if not lead:
            return None

        update_data = lead_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(lead, key, value)

        lead.updated_at = utcnow()
        await db.flush()
        logger.info(f"[LeadsService] [UPDATE] - Lead updated: {lead.id} ({lead.temple_name})")
        return lead

    @staticmethod
    async def delete_lead(db: AsyncSession, lead_id: UUID) -> bool:
        """Delete a lead."""
        result = await db.execute(select(TempleLead).filter(TempleLead.id == lead_id))
        lead = result.scalars().first()
        if not lead:
            return False

        await db.delete(lead)
        await db.flush()
        logger.info(f"[LeadsService] [DELETE] - Lead deleted: {lead_id}")
        return True

    @staticmethod
    async def log_ownership_change(
        db: AsyncSession,
        temple_id: UUID,
        previous_mode: str | None,
        new_mode: str,
        previous_plan: str | None,
        new_plan: str,
        changed_by: UUID | None,
        reason: str | None = None
    ) -> TempleOwnershipHistory:
        """Log an entry in the TempleOwnershipHistory table."""
        history = TempleOwnershipHistory(
            id=uuid4(),
            temple_id=temple_id,
            previous_management_mode=previous_mode,
            new_management_mode=new_mode,
            previous_subscription_plan=previous_plan,
            new_subscription_plan=new_plan,
            changed_by=changed_by,
            reason=reason
        )
        db.add(history)
        await db.flush()
        return history

    @staticmethod
    async def convert_lead_to_temple(
        db: AsyncSession,
        lead_id: UUID,
        domain: str,
        manager_password: str,
        actor_id: UUID | None = None
    ) -> dict:
        """
        Convert a lead record into a registered Temple and TempleProfile,
        and provision a Demo/Temple Admin user.
        """
        # 1. Fetch lead
        result = await db.execute(select(TempleLead).filter(TempleLead.id == lead_id))
        lead = result.scalars().first()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        if lead.status == "CONVERTED":
            raise HTTPException(status_code=400, detail="Lead has already been converted")

        # 2. Check slug/domain conflict
        from app.models.domain import Temple, User, UserTemple, TempleProfile, TempleWebsiteSettings
        from app.models.system_rbac import SystemRole
        from app.core.security import get_password_hash
        
        dup = await db.execute(select(Temple).filter(Temple.domain == domain))
        if dup.scalars().first():
            raise HTTPException(status_code=400, detail=f"Domain '{domain}' is already in use")

        # 3. Create Temple
        temple = Temple(
            id=uuid4(),
            name=lead.temple_name,
            domain=domain,
            location=f"{lead.district}, {lead.state}",
            state=lead.state,
            district=lead.district,
            contact_number=lead.phone,
            email=lead.email,
            management_mode="GOVERNED" if lead.interested_plan == "GOVERNED_STANDARD" else "SELF_MANAGED",
            directory_status="ACTIVE",
            subscription_plan=lead.interested_plan or "SELF_MANAGED_PRO",
            status="APPROVED", # Directly approved upon conversion
            is_active=True,
        )
        db.add(temple)
        await db.flush()

        # 4. Create Temple Profile
        profile = TempleProfile(
            temple_id=temple.id,
            description=f"Directly created from CRM Lead conversion.",
            location=temple.location,
            district=temple.district,
            state=temple.state,
            contact_number=temple.contact_number,
            email=temple.email,
        )
        db.add(profile)

        # 5. Create default website settings
        ws = TempleWebsiteSettings(
            temple_id=temple.id,
            theme_name="default",
            primary_color="#ff6600",
            approval_status="APPROVED"
        )
        db.add(ws)

        # 6. Create Manager User
        manager_role = await db.execute(select(SystemRole).filter(SystemRole.name == "TEMPLE_ADMIN"))
        manager_role_obj = manager_role.scalars().first()

        manager = User(
            id=uuid4(),
            user_id=lead.email, # Use email as login ID
            name=lead.contact_person,
            email=lead.email,
            phone=lead.phone,
            password_hash=get_password_hash(manager_password),
            role="TEMPLE_MANAGER",
            system_role_id=manager_role_obj.id if manager_role_obj else None,
            status="ACTIVE",
            is_active=True,
            temple_id=temple.id,
            approval_status="APPROVED",
        )
        db.add(manager)
        await db.flush()

        # UserTemple mapping
        mapping = UserTemple(
            id=uuid4(),
            user_id=manager.id,
            temple_id=temple.id,
            role="TEMPLE_MANAGER",
            is_active=True,
        )
        db.add(mapping)

        # 7. Log ownership history entry for claim/conversion
        history = TempleOwnershipHistory(
            id=uuid4(),
            temple_id=temple.id,
            previous_management_mode=None,
            new_management_mode=temple.management_mode,
            previous_subscription_plan=None,
            new_subscription_plan=temple.subscription_plan,
            changed_by=actor_id,
            reason="CRM Lead conversion to approved temple",
        )
        db.add(history)

        # 8. Mark lead as CONVERTED
        lead.status = "CONVERTED"
        lead.notes = f"Converted to temple: {temple.name} (domain: {domain}) by admin."
        
        await db.flush()

        logger.info(f"[LeadsService] [CONVERT] - Lead {lead_id} successfully converted to temple {temple.id}")
        return {
            "temple_id": temple.id,
            "temple_name": temple.name,
            "domain": temple.domain,
            "manager_email": manager.email,
            "management_mode": temple.management_mode,
            "subscription_plan": temple.subscription_plan
        }
