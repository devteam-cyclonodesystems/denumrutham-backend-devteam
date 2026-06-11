import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.billing.models.subscription_model import Subscription, SubscriptionEvent, SubscriptionStatus
from app.modules.temple_management.models.temple_models import Temple

logger = logging.getLogger(__name__)

def utcnow():
    return datetime.now(timezone.utc)

def ensure_tz_aware(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def map_plan_id_to_plan_name(plan_id: str) -> str:
    if not plan_id:
        return "SELF_MANAGED_PRO"
    p_lower = plan_id.lower()
    if "governed" in p_lower:
        return "GOVERNED_STANDARD"
    if "pro" in p_lower:
        return "SELF_MANAGED_PRO"
    if "free" in p_lower:
        return "FREE"
    return "SELF_MANAGED_PRO"

PLAN_PRICING = {
    "FREE": 0.0,
    "GOVERNED_STANDARD": 1000.0,
    "SELF_MANAGED_PRO": 5000.0
}

class SubscriptionService:
    @staticmethod
    async def handle_webhook_event(db: AsyncSession, event_name: str, payload: dict) -> Subscription:
        """
        Processes Razorpay subscription webhook events and transitions states.
        """
        entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        if not entity:
            entity = payload  # fallback if entity is passed directly in tests
        
        razorpay_sub_id = entity.get("id")
        razorpay_plan_id = entity.get("plan_id")
        rp_status = entity.get("status")
        notes = entity.get("notes", {})
        temple_id_str = notes.get("temple_id")

        # Convert epoch timestamps to timezone-aware datetimes
        c_start = entity.get("current_start")
        c_end = entity.get("current_end")
        t_start = entity.get("trial_start")
        t_end = entity.get("trial_end")

        current_period_start = datetime.fromtimestamp(c_start, tz=timezone.utc) if c_start else None
        current_period_end = datetime.fromtimestamp(c_end, tz=timezone.utc) if c_end else None
        trial_start = datetime.fromtimestamp(t_start, tz=timezone.utc) if t_start else None
        trial_end = datetime.fromtimestamp(t_end, tz=timezone.utc) if t_end else None

        # Resolve temple ID
        temple_id = None
        if temple_id_str:
            try:
                temple_id = UUID(temple_id_str)
            except ValueError:
                pass
        
        # If temple ID not in notes, search by Razorpay Subscription ID
        subscription = None
        if not temple_id and razorpay_sub_id:
            sub_stmt = select(Subscription).filter(Subscription.razorpay_subscription_id == razorpay_sub_id)
            sub_res = await db.execute(sub_stmt)
            subscription = sub_res.scalars().first()
            if subscription:
                temple_id = subscription.temple_id
        
        if not temple_id:
            logger.error("Could not resolve temple_id for subscription event %s, payload: %s", event_name, payload)
            raise ValueError("Could not resolve temple_id for subscription event.")

        # Find or create subscription
        if not subscription:
            sub_stmt = select(Subscription).filter(Subscription.temple_id == temple_id)
            sub_res = await db.execute(sub_stmt)
            subscription = sub_res.scalars().first()

        previous_status = None
        if not subscription:
            subscription = Subscription(
                temple_id=temple_id,
                subscription_plan="FREE",
                status=SubscriptionStatus.ACTIVE.value
            )
            db.add(subscription)
            await db.flush()
        else:
            previous_status = subscription.status

        # Map plan name
        sub_plan = notes.get("subscription_plan") or map_plan_id_to_plan_name(razorpay_plan_id)

        # Determine new status and grace period based on Razorpay events
        new_status = subscription.status
        grace_period_ends_at = subscription.grace_period_ends_at

        trial_end_aware = ensure_tz_aware(trial_end)
        utcnow_aware = ensure_tz_aware(utcnow())
        grace_ends_aware = ensure_tz_aware(grace_period_ends_at)

        if event_name in ("subscription.activated", "subscription.charged"):
            # Set to ACTIVE (or TRIALING if trial end is future)
            if trial_end_aware and trial_end_aware > utcnow_aware:
                new_status = SubscriptionStatus.TRIALING.value
            else:
                new_status = SubscriptionStatus.ACTIVE.value
            grace_period_ends_at = None
        elif event_name in ("subscription.pending", "subscription.halted"):
            new_status = SubscriptionStatus.PAST_DUE.value
            if not grace_ends_aware or grace_ends_aware <= utcnow_aware:
                grace_period_ends_at = utcnow() + timedelta(days=7)
        elif event_name == "subscription.cancelled":
            new_status = SubscriptionStatus.CANCELLED.value
            # Note: We do NOT change subscription_plan on cancellation to preserve reporting context.
        elif event_name == "subscription.expired":
            new_status = SubscriptionStatus.EXPIRED.value

        # Update fields
        subscription.razorpay_subscription_id = razorpay_sub_id or subscription.razorpay_subscription_id
        subscription.razorpay_plan_id = razorpay_plan_id or subscription.razorpay_plan_id
        
        # Don't change plan name upon cancellation/expiration
        if event_name not in ("subscription.cancelled", "subscription.expired") and sub_plan:
            subscription.subscription_plan = sub_plan

        subscription.status = new_status
        subscription.current_period_start = current_period_start or subscription.current_period_start
        subscription.current_period_end = current_period_end or subscription.current_period_end
        subscription.trial_start = trial_start or subscription.trial_start
        subscription.trial_end = trial_end or subscription.trial_end
        subscription.grace_period_ends_at = grace_period_ends_at
        subscription.updated_at = utcnow()

        # Synchronize local Temple subscription plan
        temple_stmt = select(Temple).filter(Temple.id == temple_id)
        temple_res = await db.execute(temple_stmt)
        temple = temple_res.scalars().first()
        if temple:
            temple.subscription_plan = subscription.subscription_plan

        # Record audit log
        event_log = SubscriptionEvent(
            subscription_id=subscription.id,
            event_name=event_name,
            previous_status=previous_status,
            new_status=new_status,
            payload_snapshot=payload,
            received_at=utcnow()
        )
        db.add(event_log)

        await db.commit()
        await db.refresh(subscription)
        return subscription

    @staticmethod
    async def get_subscription_status(db: AsyncSession, temple_id: UUID) -> dict:
        """
        Retrieves active plan status and evaluates warnings and write lockouts.
        """
        stmt = select(Subscription).filter(Subscription.temple_id == temple_id)
        res = await db.execute(stmt)
        sub = res.scalars().first()

        if not sub:
            # Return active FREE default if no subscription record exists yet
            return {
                "id": None,
                "temple_id": temple_id,
                "subscription_plan": "FREE",
                "status": "ACTIVE",
                "current_period_start": None,
                "current_period_end": None,
                "trial_start": None,
                "trial_end": None,
                "grace_period_ends_at": None,
                "past_due_warning": False,
                "write_locked": False
            }

        now = ensure_tz_aware(utcnow())
        past_due_warning = False
        write_locked = False

        if sub.status == "PAST_DUE":
            if sub.grace_period_ends_at:
                grace_ends = ensure_tz_aware(sub.grace_period_ends_at)
                if grace_ends >= now:
                    past_due_warning = True
                else:
                    write_locked = True
            else:
                write_locked = True
        elif sub.status in ("CANCELLED", "HALTED", "EXPIRED"):
            write_locked = True

        return {
            "id": sub.id,
            "temple_id": sub.temple_id,
            "razorpay_subscription_id": sub.razorpay_subscription_id,
            "subscription_plan": sub.subscription_plan,
            "status": sub.status,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "trial_start": sub.trial_start,
            "trial_end": sub.trial_end,
            "grace_period_ends_at": sub.grace_period_ends_at,
            "past_due_warning": past_due_warning,
            "write_locked": write_locked
        }

    @staticmethod
    async def get_revenue_report(db: AsyncSession) -> dict:
        """
        Compiles subscription counts and revenue/forecasting calculations.
        """
        stmt = select(Subscription)
        res = await db.execute(stmt)
        subs = res.scalars().all()

        counts = {
            "PENDING": 0,
            "TRIALING": 0,
            "ACTIVE": 0,
            "PAST_DUE": 0,
            "HALTED": 0,
            "CANCELLED": 0,
            "EXPIRED": 0
        }
        
        mrr = 0.0
        expected_renewal = 0.0
        now = ensure_tz_aware(utcnow())

        for s in subs:
            status_upper = s.status.upper()
            if status_upper in counts:
                counts[status_upper] += 1
            else:
                # Fallback / unrecognized
                counts["ACTIVE"] += 1

            price = PLAN_PRICING.get(s.subscription_plan, 0.0)

            # MRR counts only active paid plans
            if s.status == SubscriptionStatus.ACTIVE.value:
                mrr += price

            # Expected Renewal Revenue: ACTIVE + PAST_DUE still in grace period
            if s.status == SubscriptionStatus.ACTIVE.value:
                expected_renewal += price
            elif s.status == SubscriptionStatus.PAST_DUE.value:
                grace_ends = ensure_tz_aware(s.grace_period_ends_at)
                if grace_ends and grace_ends >= now:
                    expected_renewal += price

        return {
            "status_counts": counts,
            "mrr": mrr,
            "expected_renewal_revenue": expected_renewal
        }
