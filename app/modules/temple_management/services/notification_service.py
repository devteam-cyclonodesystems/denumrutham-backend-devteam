"""
Notification Service — event-driven, multi-role routing.

All write methods use flush() only.  The caller controls the commit boundary.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, or_
from uuid import UUID
from typing import Optional, List

from app.models.domain import Notification

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Event constants & role routing map
# ═══════════════════════════════════════════════════════════════════════

class NotificationEvent:
    APPROVAL_REQUEST_CREATED = "APPROVAL_REQUEST_CREATED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    FINANCIAL_CHANGE = "FINANCIAL_CHANGE"
    TEMPLE_UPDATE = "TEMPLE_UPDATE"
    EMPLOYEE_UPDATE = "EMPLOYEE_UPDATE"
    STAFF_REGISTERED = "STAFF_REGISTERED"


# Which roles should receive notifications for each event type.
# "REQUESTER" is a sentinel — resolved at runtime to the original requester's user_id.
EVENT_ROLE_MAP: dict[str, list[str]] = {
    NotificationEvent.FINANCIAL_CHANGE:         ["FINANCE_MANAGER", "SUPERADMIN"],
    NotificationEvent.TEMPLE_UPDATE:            ["TEMPLE_ADMIN", "SUPERADMIN"],
    NotificationEvent.EMPLOYEE_UPDATE:          ["HR_MANAGER", "SUPERADMIN"],
}


class NotificationService:
    """Transaction-safe notification creation with multi-role routing."""

    # ── Low-level: stage a single notification row ──────────────────────
    @staticmethod
    async def _stage_notification(
        db: AsyncSession,
        temple_id: UUID,
        title: str,
        message: str,
        user_id: Optional[UUID] = None,
        role: Optional[str] = None,
    ):
        """Insert one notification row and flush (no commit)."""
        notif = Notification(
            temple_id=temple_id,
            user_id=user_id,
            role=role,
            title=title,
            message=message,
        )
        db.add(notif)
        await db.flush()
        logger.info("Notification staged: %s (role=%s, user=%s)", title, role, user_id)

    # ── High-level: event-driven multi-role dispatch ────────────────────
    @staticmethod
    async def dispatch_event(
        db: AsyncSession,
        temple_id: UUID,
        event_type: str,
        title: str,
        message: str,
        requester_id: Optional[UUID] = None,
    ):
        """
        Create notifications for every target role defined in EVENT_ROLE_MAP.

        * Role-based targets  → one notification per role string
        * "REQUESTER" sentinel → one notification with user_id = requester_id
        * Deduplication        → each (role, user_id) pair is dispatched once
        """
        target_roles = EVENT_ROLE_MAP.get(event_type, [])
        if not target_roles:
            logger.warning("No routing for event type: %s", event_type)
            return

        dispatched: set[tuple] = set()

        for role in target_roles:
            if role == "REQUESTER":
                if requester_id is None:
                    continue
                key = (None, str(requester_id))
                if key in dispatched:
                    continue
                dispatched.add(key)
                await NotificationService._stage_notification(
                    db, temple_id, title, message,
                    user_id=requester_id, role=None,
                )
            else:
                key = (role, None)
                if key in dispatched:
                    continue
                dispatched.add(key)
                await NotificationService._stage_notification(
                    db, temple_id, title, message,
                    user_id=None, role=role,
                )

    # ── Backward-compatible simple creator (used outside approval) ──────
    @staticmethod
    async def create_notification(
        db: AsyncSession,
        temple_id: UUID,
        title: str,
        message: str,
        user_id: Optional[UUID] = None,
        role: Optional[str] = None,
    ):
        """Simple single-target notification (flush, no commit)."""
        await NotificationService._stage_notification(
            db, temple_id, title, message, user_id=user_id, role=role,
        )

    # ── Query: fetch for a specific user ────────────────────────────────
    @staticmethod
    async def get_user_notifications(
        db: AsyncSession,
        temple_id: UUID,
        user_id: UUID,
        role: str,
        limit: int = 50,
    ) -> List[Notification]:
        """
        Fetch notifications targeted at:
          - This specific user_id
          - This user's role string
          - Broadcast (role IS NULL and user_id IS NULL)
        """
        stmt = (
            select(Notification)
            .filter(Notification.temple_id == temple_id)
            .filter(
                or_(
                    Notification.user_id == user_id,
                    Notification.role == role,
                    (Notification.role.is_(None)) & (Notification.user_id.is_(None)),
                )
            )
            .order_by(desc(Notification.created_at))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    # ── Mutation: mark read ─────────────────────────────────────────────
    @staticmethod
    async def mark_as_read(
        db: AsyncSession, notification_id: UUID, user_id: UUID
    ) -> Optional[Notification]:
        stmt = select(Notification).filter(Notification.id == notification_id)
        result = await db.execute(stmt)
        notif = result.scalar_one_or_none()
        if notif:
            notif.is_read = True
            await db.flush()
        return notif
