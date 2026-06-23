import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import select
from app.core.database.database import AsyncSessionLocal
from app.models.domain import Temple, User
from app.models.archana import (
    EnterpriseArchanaBooking, NotificationTemplate, NotificationDeliveryLog,
    OnlineSettlementLedger, ArchanaRefund, RitualQueue
)
from app.core.notifications.providers import (
    PushNotificationProvider, EmailNotificationProvider, SMSNotificationProvider
)

logger = logging.getLogger(__name__)

# Fallback default templates if database does not contain templates
DEFAULT_TEMPLATES = {
    "PAYMENT_CAPTURED": {
        "PUSH": ("Booking Confirmed!", "Your booking {ref_id} at {temple_name} is confirmed. Token: {token_number}."),
        "SMS": ("Booking Confirmed!", "Hi {devotee_name}, your booking {ref_id} at {temple_name} is confirmed. Token: {token_number}."),
        "EMAIL": ("Booking Confirmed!", "Hi {devotee_name}, your booking {ref_id} at {temple_name} is confirmed. Token: {token_number}.\n\n--- Tax Invoice ---\nPlatform Fee: INR {convenience_fee:.2f}\nCGST (9%): INR {cgst:.2f}\nSGST (9%): INR {sgst:.2f}\nTotal Paid: INR {total_payable:.2f}\nThank you!"),
    },
    "RITUAL_COMPLETED": {
        "PUSH": ("Ritual Completed!", "The Archana ritual for booking {ref_id} has been successfully executed at {temple_name}."),
        "SMS": ("Ritual Completed!", "Hi {devotee_name}, the Archana ritual for booking {ref_id} at {temple_name} is completed. Prasadam collection mode: {prasadam_mode}."),
        "EMAIL": ("Ritual Completed!", "Hi {devotee_name}, the Archana ritual for booking {ref_id} at {temple_name} is completed. Prasadam collection mode: {prasadam_mode}."),
    },
    "BOOKING_REJECTED": {
        "PUSH": ("Booking Rejected", "Your booking {ref_id} at {temple_name} was rejected. Refund of INR {refund_amount:.2f} has been initiated."),
        "SMS": ("Booking Rejected", "Hi {devotee_name}, your booking {ref_id} at {temple_name} was rejected. Refund of INR {refund_amount:.2f} has been initiated."),
        "EMAIL": ("Booking Rejected", "Hi {devotee_name}, your booking {ref_id} at {temple_name} was rejected. Refund of INR {refund_amount:.2f} has been initiated."),
    },
    "REFUNDED": {
        "PUSH": ("Refund Processed", "Your refund of INR {refund_amount:.2f} for booking {ref_id} has been processed successfully."),
        "SMS": ("Refund Processed", "Hi {devotee_name}, refund of INR {refund_amount:.2f} for booking {ref_id} has been processed successfully."),
        "EMAIL": ("Refund Processed", "Hi {devotee_name}, refund of INR {refund_amount:.2f} for booking {ref_id} has been processed successfully."),
    }
}

class NotificationDispatcher:
    """
    Asynchronous notification dispatcher running out-of-band of the request transaction.
    Resolves templates from db, renders variables, routes notifications, and logs status.
    """

    @classmethod
    async def dispatch_notifications(cls, outbox_event_id: UUID, temple_id: UUID, entity_name: str, entity_id: str, action_type: str) -> None:
        if entity_name != "ArchanaBooking":
            return

        # Canonicalize completed action types to RITUAL_COMPLETED
        event_code = action_type
        if action_type in ("RITUAL_AUTO_COMPLETED", "RITUAL_MANUAL_COMPLETED", "RITUAL_COMPLETED"):
            event_code = "RITUAL_COMPLETED"
        elif action_type in ("REFUNDED", "REFUND_COMPLETED"):
            event_code = "REFUNDED"

        if event_code not in DEFAULT_TEMPLATES:
            logger.debug("Action type %s not registered for notifications", action_type)
            return

        logger.info("Dispatching notifications for event %s (event_id=%s)", event_code, outbox_event_id)

        async with AsyncSessionLocal() as db:
            try:
                # 1. Fetch booking details
                booking_stmt = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == UUID(entity_id))
                booking_res = await db.execute(booking_stmt)
                booking = booking_res.scalar_one_or_none()
                if not booking:
                    logger.error("Booking %s not found. Skipping notifications.", entity_id)
                    return

                # 2. Fetch temple details
                temple_stmt = select(Temple).filter(Temple.id == temple_id)
                temple_res = await db.execute(temple_stmt)
                temple = temple_res.scalar_one_or_none()
                temple_name = temple.name if temple else "Temple"

                # 3. Fetch token number if any
                token_stmt = select(RitualQueue.token_number).filter(RitualQueue.booking_id == booking.id).limit(1)
                token_res = await db.execute(token_stmt)
                token_number = token_res.scalar() or "N/A"

                # 4. Fetch fee splits from ledger
                ledger_stmt = select(OnlineSettlementLedger).filter(OnlineSettlementLedger.booking_id == booking.id).limit(1)
                ledger_res = await db.execute(ledger_stmt)
                ledger = ledger_res.scalar_one_or_none()
                convenience_fee = ledger.gross_convenience_fee if ledger else 0.0
                cgst = ledger.cgst_component if ledger else 0.0
                sgst = ledger.sgst_component if ledger else 0.0
                total_payable = booking.total_payable or booking.grand_total

                # 5. Fetch refund details
                refund_stmt = select(ArchanaRefund).filter(ArchanaRefund.booking_id == booking.id).limit(1)
                refund_res = await db.execute(refund_stmt)
                refund = refund_res.scalar_one_or_none()
                refund_amount = refund.amount if refund else total_payable

                # Render payload dictionary
                context = {
                    "devotee_name": booking.primary_devotee_name or "Devotee",
                    "ref_id": booking.ref_id,
                    "temple_name": temple_name,
                    "token_number": token_number,
                    "convenience_fee": convenience_fee,
                    "cgst": cgst,
                    "sgst": sgst,
                    "total_payable": total_payable,
                    "prasadam_mode": booking.prasadam_collection or "COLLECT",
                    "refund_amount": refund_amount
                }

                # 6. Query NotificationTemplates for this event code
                # Try temple specific active templates
                tmpl_stmt = select(NotificationTemplate).filter(
                    NotificationTemplate.temple_id == temple_id,
                    NotificationTemplate.event_code == event_code,
                    NotificationTemplate.is_active == True
                )
                tmpl_res = await db.execute(tmpl_stmt)
                templates = tmpl_res.scalars().all()

                # If none, try global active templates
                if not templates:
                    tmpl_stmt = select(NotificationTemplate).filter(
                        NotificationTemplate.temple_id == None,
                        NotificationTemplate.event_code == event_code,
                        NotificationTemplate.is_active == True
                    )
                    tmpl_res = await db.execute(tmpl_stmt)
                    templates = tmpl_res.scalars().all()

                # Map templates to channels
                channels_to_dispatch = {}
                for t in templates:
                    channels_to_dispatch[t.channel.upper()] = (t.title_template, t.body_template)

                # Merge with default fallbacks if some channels are missing
                fallback_templates = DEFAULT_TEMPLATES.get(event_code, {})
                for channel, (def_title, def_body) in fallback_templates.items():
                    if channel not in channels_to_dispatch:
                        channels_to_dispatch[channel] = (def_title, def_body)

                # 7. Send notifications across all active channels
                for channel, (title_tmpl, body_tmpl) in channels_to_dispatch.items():
                    title = title_tmpl.format(**context) if title_tmpl else ""
                    body = body_tmpl.format(**context)

                    recipient = ""
                    provider = None

                    if channel == "PUSH":
                        # Recipient address is devotee user_id (FCM lookup) or device token
                        recipient = str(booking.devotee_user_id) if booking.devotee_user_id else (booking.phone_number or "")
                        provider = PushNotificationProvider()
                    elif channel == "SMS":
                        recipient = booking.phone_number or ""
                        provider = SMSNotificationProvider()
                    elif channel == "EMAIL":
                        recipient = booking.email or ""
                        provider = EmailNotificationProvider()

                    if not recipient or not provider:
                        logger.warning("Recipient or provider missing for channel %s, skipping.", channel)
                        continue

                    # Send notification asynchronously and safely
                    success = False
                    err_msg = None
                    try:
                        success = await provider.send_notification(recipient, body, {"title": title, "ref_id": booking.ref_id})
                    except Exception as e:
                        err_msg = str(e)
                        logger.error("Failed to send notification via %s: %s", channel, e)

                    # Log delivery details
                    delivery_log = NotificationDeliveryLog(
                        temple_id=temple_id,
                        outbox_event_id=outbox_event_id,
                        recipient_user_id=booking.devotee_user_id,
                        channel=channel,
                        recipient_address=recipient,
                        status="SENT" if success else "FAILED",
                        failure_reason=err_msg,
                        sent_at=datetime.now(timezone.utc)
                    )
                    db.add(delivery_log)

                # Commit delivery logs
                await db.commit()

            except Exception as e:
                logger.error("Error dispatching notifications for outbox event %s: %s", outbox_event_id, e, exc_info=True)
