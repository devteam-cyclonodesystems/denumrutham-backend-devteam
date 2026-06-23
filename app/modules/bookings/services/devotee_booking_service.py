"""Devotee Booking Service — Service bookings, payments, and profile management."""
from uuid import UUID
from datetime import datetime, timezone
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.modules.temple_management.models.temple_models import TempleService, Temple, TempleProfile
from app.modules.bookings.models.booking_models import ServiceBooking, ServiceBookingStatus, PaymentMethod, DevoteeProfile
from app.modules.billing.models.billing_models import Payment, PaymentStatus


class DevoteeBookingService:

    @staticmethod
    async def create_booking(db: AsyncSession, data, user_id: str):
        uid = UUID(user_id)

        # Verify service exists and is active
        service_result = await db.execute(
            select(TempleService).filter(
                TempleService.id == data.service_id,
                TempleService.temple_id == data.temple_id,
                TempleService.active == True,
            )
        )
        service = service_result.scalars().first()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found or inactive")

        # Parse booking date
        try:
            booking_date = datetime.fromisoformat(data.booking_date)
            if booking_date.tzinfo is None:
                booking_date = booking_date.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid booking date format")

        # Create booking
        booking = ServiceBooking(
            temple_id=data.temple_id,
            devotee_user_id=uid,
            service_id=data.service_id,
            booking_date=booking_date,
            amount=service.price,
            status=ServiceBookingStatus.PENDING,
            devotee_name=data.devotee_name,
            devotee_phone=data.devotee_phone,
            notes=data.notes or "",
        )
        db.add(booking)
        await db.flush()

        # Create payment record
        payment = Payment(
            temple_id=data.temple_id,
            reference_id=booking.id,
            amount=service.price,
            status=PaymentStatus.PENDING,
            payment_method=PaymentMethod.UPI_QR,
            service_booking_id=booking.id,
        )
        db.add(payment)
        await db.commit()
        await db.refresh(booking)

        return booking, service

    @staticmethod
    async def get_my_bookings(db: AsyncSession, user_id: str):
        uid = UUID(user_id)

        result = await db.execute(
            select(ServiceBooking)
            .filter(ServiceBooking.devotee_user_id == uid)
            .order_by(ServiceBooking.created_at.desc())
        )
        bookings = result.scalars().all()

        enriched = []
        for b in bookings:
            service_name = None
            temple_name = None
            srv = await db.execute(select(TempleService).filter(TempleService.id == b.service_id))
            srv_obj = srv.scalars().first()
            if srv_obj:
                service_name = srv_obj.service_name
            tmpl = await db.execute(select(Temple).filter(Temple.id == b.temple_id))
            tmpl_obj = tmpl.scalars().first()
            if tmpl_obj:
                temple_name = tmpl_obj.name

            # Query execution details if execution exists
            from app.models.archana import ArchanaExecution, ArchanaBookingItem, ArchanaBookingMember, EnterpriseArchanaBooking
            exec_stmt = select(ArchanaExecution).join(ArchanaBookingItem).join(ArchanaBookingMember).join(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == b.id)
            exec_res = await db.execute(exec_stmt)
            execution = exec_res.scalars().first()
            
            acknowledged_at = None
            start_time = None
            completed_at = None
            execution_status = None
            
            if execution:
                acknowledged_at = execution.acknowledged_at
                start_time = execution.start_time
                completed_at = execution.completed_at
                execution_status = execution.status.value

            enriched.append({
                "id": b.id,
                "temple_id": b.temple_id,
                "service_id": b.service_id,
                "booking_date": b.booking_date,
                "amount": b.amount,
                "status": b.status,
                "devotee_name": b.devotee_name,
                "devotee_phone": b.devotee_phone,
                "notes": b.notes,
                "created_at": b.created_at,
                "service_name": service_name,
                "temple_name": temple_name,
                "acknowledged_at": acknowledged_at,
                "start_time": start_time,
                "completed_at": completed_at,
                "execution_status": execution_status,
            })
        return enriched

    @staticmethod
    async def get_booking_payment(db: AsyncSession, booking_id: str, user_id: str):
        bid = UUID(booking_id)

        booking_result = await db.execute(
            select(ServiceBooking).filter(ServiceBooking.id == bid)
        )
        booking = booking_result.scalars().first()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        if str(booking.devotee_user_id) != user_id:
            raise HTTPException(status_code=403, detail="Not your booking")

        payment_result = await db.execute(
            select(Payment).filter(Payment.service_booking_id == bid)
        )
        payment = payment_result.scalars().first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        profile_result = await db.execute(
            select(TempleProfile).filter(TempleProfile.temple_id == booking.temple_id)
        )
        profile = profile_result.scalars().first()
        upi_id = profile.upi_id if profile else ""

        return payment, upi_id

    @staticmethod
    async def get_devotee_profile(db: AsyncSession, user_id: str):
        uid = UUID(user_id)
        result = await db.execute(
            select(DevoteeProfile).filter(DevoteeProfile.user_id == uid)
        )
        profile = result.scalars().first()
        if not profile:
            from app.modules.auth.models.auth_models import User
            user_res = await db.execute(select(User).filter(User.id == uid))
            user = user_res.scalars().first()
            if not user:
                raise HTTPException(status_code=404, detail="Devotee user not found")
            profile = DevoteeProfile(
                user_id=uid,
                name=user.name or ""
            )
            db.add(profile)
            await db.commit()
            await db.refresh(profile)
        return profile

    @staticmethod
    async def update_devotee_profile(db: AsyncSession, user_id: str, data):
        uid = UUID(user_id)
        result = await db.execute(
            select(DevoteeProfile).filter(DevoteeProfile.user_id == uid)
        )
        profile = result.scalars().first()
        if not profile:
            from app.modules.auth.models.auth_models import User
            user_res = await db.execute(select(User).filter(User.id == uid))
            user = user_res.scalars().first()
            if not user:
                raise HTTPException(status_code=404, detail="Devotee user not found")
            profile = DevoteeProfile(
                user_id=uid,
                name=user.name or ""
            )
            db.add(profile)
            await db.flush()

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(profile, field, value)

        # Sync profile name to User table
        if "name" in update_data and update_data["name"]:
            from app.modules.auth.models.auth_models import User
            user_res = await db.execute(select(User).filter(User.id == uid))
            user = user_res.scalars().first()
            if user:
                user.name = update_data["name"]

        await db.commit()
        await db.refresh(profile)
        return profile


    @staticmethod
    async def get_devotee_notifications(db: AsyncSession, user_id: str, limit: int = 50):
        uid = UUID(user_id)
        # 1. Fetch temples followed by the devotee
        from app.modules.temple_management.models.temple_models import TempleFollower
        follower_stmt = select(TempleFollower.temple_id).filter(TempleFollower.user_id == uid)
        follower_res = await db.execute(follower_stmt)
        followed_temple_ids = [row[0] for row in follower_res.all()]
        
        # 2. Query notifications
        from app.modules.governance.models.governance_models import Notification
        from sqlalchemy import or_, desc
        
        conditions = [
            Notification.user_id == uid,
            Notification.role == "DEVOTEE"
        ]
        if followed_temple_ids:
            conditions.append(Notification.temple_id.in_(followed_temple_ids))
            
        stmt = (
            select(Notification)
            .filter(or_(*conditions))
            .order_by(desc(Notification.created_at))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def create_online_archana_booking(db: AsyncSession, data, user_id: str):
        import logging
        import uuid
        from datetime import datetime, timezone, timedelta
        from fastapi import HTTPException
        from app.models.archana import ArchanaCatalog, EnterpriseArchanaBooking, ArchanaBookingMember, ArchanaBookingItem
        from app.modules.temple_management.models.temple_models import Temple
        from app.modules.auth.models.auth_models import User
        from app.services.platform_fee_engine import PlatformFeeEngine
        from app.core.payments.razorpay_provider import RazorpayProvider
        from app.repositories.archana_repository import ArchanaRepository

        srv_logger = logging.getLogger("tms.services.devotee_booking")
        uid = UUID(user_id)

        # 0. Global Kill Switch Check
        from app.modules.governance.models.governance_models import PlatformGlobalSetting
        kill_switch_stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "online_archana_payments_enabled")
        kill_switch_res = await db.execute(kill_switch_stmt)
        kill_switch = kill_switch_res.scalar_one_or_none()
        if kill_switch:
            is_enabled = kill_switch.value
            if isinstance(is_enabled, dict):
                is_enabled = is_enabled.get("enabled", True)
            if is_enabled is False:
                raise HTTPException(
                    status_code=503,
                    detail="Online Archana bookings are temporarily unavailable. Please try again later or contact the temple."
                )

        from sqlalchemy.orm import selectinload

        # 1. Fetch catalog item
        stmt = select(ArchanaCatalog).filter(
            ArchanaCatalog.id == data.catalog_id,
            ArchanaCatalog.is_active == True,
            ArchanaCatalog.is_online_enabled == True
        ).options(selectinload(ArchanaCatalog.deity))
        res = await db.execute(stmt)
        catalog_item = res.scalar_one_or_none()
        if not catalog_item:
            raise HTTPException(status_code=404, detail="Archana service not found or not enabled for online booking")

        # 2. Verify temple is active
        temple_stmt = select(Temple).filter(Temple.id == catalog_item.temple_id)
        temple_res = await db.execute(temple_stmt)
        temple = temple_res.scalar_one_or_none()
        if not temple or temple.status != "APPROVED" or not temple.is_active:
            raise HTTPException(status_code=400, detail="Temple is currently inactive or not approved")

        # 3. Verify prasadam mode
        available_prasadam_modes = catalog_item.available_prasadam_modes or ["COLLECT", "NONE"]
        if data.prasadam_mode.upper() not in [m.upper() for m in available_prasadam_modes]:
            raise HTTPException(status_code=400, detail="Requested prasadam mode is not available for this service")

        # 4. Fetch devotee user profile info
        user_stmt = select(User).filter(User.id == uid)
        user_res = await db.execute(user_stmt)
        user = user_res.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # 5. Calculate prices and platform fee splits
        num_members = len(data.members)
        if num_members == 0:
            raise HTTPException(status_code=400, detail="At least one booking member is required")

        archana_amount = catalog_item.price * num_members
        fee_info = await PlatformFeeEngine.calculate_fee(db, archana_amount)
        gross_convenience_fee = fee_info["gross_convenience_fee"]
        total_payable = fee_info["total_payable"]

        # 6. Generate sequential Ref ID
        count = await ArchanaRepository.get_booking_count(db, catalog_item.temple_id)
        now = datetime.now(timezone.utc)
        ref_id = f"AR-{now.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"

        # 7. Call Razorpay API to create order
        try:
            order = await RazorpayProvider.create_order(total_payable, ref_id)
            gateway_order_id = order["id"]
        except Exception as e:
            srv_logger.error("Failed to create Razorpay order: %s", e)
            raise HTTPException(status_code=502, detail="Failed to initialize payment gateway order")

        # 8. Create EnterpriseArchanaBooking
        booking = EnterpriseArchanaBooking(
            temple_id=catalog_item.temple_id,
            ref_id=ref_id,
            devotee_user_id=uid,
            primary_devotee_name=data.members[0].name,
            phone_number=user.phone or "",
            email=user.email or "",
            booking_date=now,
            booking_channel="ONLINE",
            booking_mode="ONLINE",
            prasadam_collection=data.prasadam_mode.upper(),
            online_status="PAYMENT_PENDING",
            total_amount=archana_amount,
            grand_total=archana_amount,
            total_payable=total_payable,
            gateway_order_id=gateway_order_id,
            payment_expiry_at=now + timedelta(minutes=15),
            created_by=uid
        )

        # 9. Create members and items
        for m_in in data.members:
            member = ArchanaBookingMember(
                name=m_in.name,
                nakshatra=m_in.nakshatra,
                is_primary=m_in.is_primary
            )
            item = ArchanaBookingItem(
                service_id=catalog_item.id,
                quantity=1,
                price_at_booking=catalog_item.price,
                ritual_name_snapshot=catalog_item.name,
                ritual_deity_snapshot=catalog_item.deity.deity_name if catalog_item.deity else "General",
                ritual_duration_snapshot=catalog_item.duration_minutes,
                ritual_version_id=catalog_item.version,
                total_price=catalog_item.price
            )
            member.items.append(item)
            booking.members.append(member)

        db.add(booking)
        await db.commit()
        await db.refresh(booking)

        key_id, _ = await RazorpayProvider.get_credentials()
        if not key_id:
            key_id = "rzp_test_mockkeyid"

        return booking, gross_convenience_fee, key_id

    @classmethod
    async def process_payment_webhook(cls, db: AsyncSession, event_data: dict) -> bool:
        import logging
        from app.models.archana import (
            EnterpriseArchanaBooking, ArchanaBookingPayment, OnlineSettlementLedger,
            RitualQueue, QueueStatus, ArchanaStatus, ArchanaBookingMember, ArchanaRefund
        )
        from app.modules.audit.services.activity_log_service import ActivityLogService
        from sqlalchemy.orm import selectinload
        from sqlalchemy import func
        from datetime import datetime, timezone, timedelta
        from app.services.platform_fee_engine import PlatformFeeEngine

        srv_logger = logging.getLogger("tms.services.devotee_booking.webhook")

        event_name = event_data.get("event")
        payload = event_data.get("payload", {})

        if event_name == "payment.captured":
            payment_entity = payload.get("payment", {}).get("entity", {})
            gateway_payment_id = payment_entity.get("id")
            gateway_order_id = payment_entity.get("order_id")
            gateway_method = payment_entity.get("method", "upi")
            
            # Convert fee/tax from paise to INR
            gateway_fee = float(payment_entity.get("fee", 0)) / 100.0
            gateway_tax = float(payment_entity.get("tax", 0)) / 100.0
            amount_charged = float(payment_entity.get("amount", 0)) / 100.0

            # 1. Idempotency Check: check if payment already processed
            pay_stmt = select(ArchanaBookingPayment).filter(
                ArchanaBookingPayment.gateway_payment_id == gateway_payment_id
            )
            pay_res = await db.execute(pay_stmt)
            existing_pay = pay_res.scalar_one_or_none()
            if existing_pay:
                srv_logger.info("Payment %s already processed. Skipping.", gateway_payment_id)
                return True

            # 2. Fetch booking by order_id
            book_stmt = select(EnterpriseArchanaBooking).filter(
                EnterpriseArchanaBooking.gateway_order_id == gateway_order_id
            ).options(
                selectinload(EnterpriseArchanaBooking.members)
                .selectinload(ArchanaBookingMember.items)
            )
            book_res = await db.execute(book_stmt)
            booking = book_res.scalar_one_or_none()
            if not booking:
                srv_logger.error("Booking with gateway_order_id %s not found.", gateway_order_id)
                return False

            archana_amount = booking.total_amount
            fee_info = await PlatformFeeEngine.calculate_fee(db, archana_amount)
            convenience_fee = fee_info["gross_convenience_fee"]

            # 3. Transition booking status
            booking.online_status = "PAYMENT_SUCCESS"
            booking.status = ArchanaStatus.CONFIRMED

            # 4. Create ArchanaBookingPayment record
            now_utc = datetime.now(timezone.utc)
            payment_record = ArchanaBookingPayment(
                booking_id=booking.id,
                amount=amount_charged,
                payment_mode="Online",
                transaction_ref=gateway_payment_id,
                status="SUCCESS",
                created_at=now_utc,
                gateway_payment_id=gateway_payment_id,
                gateway_order_id=gateway_order_id,
                gateway_method=gateway_method,
                gateway_fee=gateway_fee,
                gateway_tax=gateway_tax,
                archana_amount=archana_amount,
                convenience_fee=convenience_fee,
                total_amount_charged=amount_charged,
                webhook_payload=event_data,
                webhook_received_at=now_utc,
                settlement_status="PENDING"
            )
            db.add(payment_record)
            await db.flush()

            # 5. Append OnlineSettlementLedger CREDIT entry
            ledger_entry = OnlineSettlementLedger(
                temple_id=booking.temple_id,
                booking_id=booking.id,
                payment_id=payment_record.id,
                entry_type="CREDIT",
                archana_amount=archana_amount,
                temple_net_amount=archana_amount,
                gross_convenience_fee=convenience_fee,
                taxable_fee=fee_info["taxable_fee"],
                gst_component=fee_info["gst_component"],
                cgst_component=fee_info["cgst_component"],
                sgst_component=fee_info["sgst_component"],
                gateway_fee=gateway_fee,
                gateway_tax=gateway_tax,
                net_platform_revenue=convenience_fee - fee_info["gst_component"] - gateway_fee,
                total_charged_to_devotee=amount_charged,
                gateway_payment_id=gateway_payment_id,
                is_settled=False,
                created_at=now_utc
            )
            db.add(ledger_entry)

            # 6. Place in RitualQueue
            today = now_utc.date()
            token_stmt = select(func.count(RitualQueue.id)).filter(
                RitualQueue.temple_id == booking.temple_id,
                func.date(RitualQueue.estimated_start_time) == today
            )
            token_res = await db.execute(token_stmt)
            token_seq = (token_res.scalar() or 0) + 1
            token_number = f"T-{token_seq:03d}"

            waiting_count_res = await db.execute(
                select(func.count(RitualQueue.id)).filter(
                    RitualQueue.temple_id == booking.temple_id,
                    RitualQueue.status == QueueStatus.WAITING
                )
            )
            waiting_count = waiting_count_res.scalar() or 0
            est_start = now_utc + timedelta(minutes=waiting_count * 10)

            queue_entry = RitualQueue(
                temple_id=booking.temple_id,
                booking_id=booking.id,
                token_number=token_number,
                status=QueueStatus.WAITING,
                priority=10 if booking.priority_slot else 0,
                estimated_start_time=est_start
            )
            db.add(queue_entry)
            await db.flush()

            # Initialize executions
            from app.services.archana_lifecycle_service import ArchanaLifecycleService
            await ArchanaLifecycleService.initialize_executions(db, queue_entry.id)

            # 7. Write to ActivityOutbox
            await ActivityLogService.emit_event(
                db=db,
                temple_id=booking.temple_id,
                module_name="BOOKINGS",
                entity_name="ArchanaBooking",
                entity_id=str(booking.id),
                action_type="PAYMENT_CAPTURED",
                action_category="BOOKING_PAYMENT",
                description=f"Online payment of {amount_charged} captured for booking {booking.ref_id}.",
                before_value={"online_status": "PAYMENT_PENDING"},
                after_value={"online_status": "PAYMENT_SUCCESS", "payment_id": str(payment_record.id)},
                performed_by_user_id=booking.devotee_user_id,
                performed_by_name="System Gateway",
                performed_by_role="SYSTEM",
                severity="INFO",
                risk_score=0
            )

            await db.commit()
            srv_logger.info("Payment %s processed successfully for booking %s.", gateway_payment_id, booking.ref_id)
            return True

        elif event_name == "refund.processed":
            refund_entity = payload.get("refund", {}).get("entity", {})
            gateway_refund_id = refund_entity.get("id")
            gateway_payment_id = refund_entity.get("payment_id")
            gateway_refund_status = refund_entity.get("status")
            refund_amount = float(refund_entity.get("amount", 0)) / 100.0

            ref_stmt = select(ArchanaRefund).filter(
                ArchanaRefund.gateway_refund_id == gateway_refund_id
            )
            ref_res = await db.execute(ref_stmt)
            refund_record = ref_res.scalar_one_or_none()
            
            if not refund_record:
                pay_stmt = select(ArchanaBookingPayment).filter(
                    ArchanaBookingPayment.gateway_payment_id == gateway_payment_id
                )
                pay_res = await db.execute(pay_stmt)
                payment_record = pay_res.scalar_one_or_none()
                if payment_record:
                    ref_stmt = select(ArchanaRefund).filter(
                        ArchanaRefund.booking_id == payment_record.booking_id
                    )
                    ref_res = await db.execute(ref_stmt)
                    refund_record = ref_res.scalar_one_or_none()

            if not refund_record:
                srv_logger.error("Refund with gateway_refund_id %s not found.", gateway_refund_id)
                return False

            if refund_record.status == "SUCCESS":
                book_stmt = select(EnterpriseArchanaBooking).filter(
                    EnterpriseArchanaBooking.id == refund_record.booking_id
                )
                book_res = await db.execute(book_stmt)
                booking = book_res.scalar_one_or_none()
                if booking and booking.online_status != "REFUNDED":
                    booking.online_status = "REFUNDED"
                    await db.commit()
                srv_logger.info("Refund %s already processed. Skipping.", gateway_refund_id)
                return True

            now_utc = datetime.now(timezone.utc)
            refund_record.status = "SUCCESS"
            refund_record.gateway_refund_status = gateway_refund_status
            refund_record.refund_settled_at = now_utc

            book_stmt = select(EnterpriseArchanaBooking).filter(
                EnterpriseArchanaBooking.id == refund_record.booking_id
            )
            book_res = await db.execute(book_stmt)
            booking = book_res.scalar_one_or_none()
            if booking:
                booking.online_status = "REFUNDED"
                
                await ActivityLogService.emit_event(
                    db=db,
                    temple_id=booking.temple_id,
                    module_name="BOOKINGS",
                    entity_name="ArchanaBooking",
                    entity_id=str(booking.id),
                    action_type="REFUND_COMPLETED",
                    action_category="BOOKING_REFUND",
                    description=f"Refund of {refund_amount} processed for booking {booking.ref_id}.",
                    before_value={"online_status": "REFUND_INITIATED"},
                    after_value={"online_status": "REFUNDED"},
                    performed_by_user_id=booking.devotee_user_id,
                    performed_by_name="System Gateway",
                    performed_by_role="SYSTEM",
                    severity="INFO",
                    risk_score=0
                )

            await db.commit()
            srv_logger.info("Refund %s completed successfully.", gateway_refund_id)
            return True

        return False

    @classmethod
    async def process_payment_expiries(cls, db: AsyncSession):
        import logging
        from datetime import datetime, timezone
        from app.models.archana import EnterpriseArchanaBooking
        from app.modules.audit.services.activity_log_service import ActivityLogService
        
        srv_logger = logging.getLogger("tms.services.devotee_booking.expiry")
        now = datetime.now(timezone.utc)
        
        # Select pending online bookings that have expired
        stmt = select(EnterpriseArchanaBooking).filter(
            EnterpriseArchanaBooking.online_status == "PAYMENT_PENDING",
            EnterpriseArchanaBooking.payment_expiry_at < now
        )
        res = await db.execute(stmt)
        expired_bookings = res.scalars().all()
        
        if not expired_bookings:
            return
            
        srv_logger.info("Found %d expired online bookings to clean up", len(expired_bookings))
        
        for booking in expired_bookings:
            try:
                booking.online_status = "EXPIRED"
                
                # Emit activity outbox event
                await ActivityLogService.emit_event(
                    db=db,
                    temple_id=booking.temple_id,
                    module_name="BOOKINGS",
                    entity_name="ArchanaBooking",
                    entity_id=str(booking.id),
                    action_type="PAYMENT_EXPIRED",
                    action_category="BOOKING_PAYMENT",
                    description=f"Online booking {booking.ref_id} payment expired after 15 minutes.",
                    before_value={"online_status": "PAYMENT_PENDING"},
                    after_value={"online_status": "EXPIRED"},
                    performed_by_user_id=None,
                    performed_by_name="System Expiry Worker",
                    performed_by_role="SYSTEM",
                    severity="INFO",
                    risk_score=0
                )
            except Exception as e:
                srv_logger.error("Error expiring booking %s: %s", booking.id, e)
                
        await db.commit()

    @classmethod
    async def initiate_online_refund(cls, db: AsyncSession, booking, actor_id: UUID) -> bool:
        import logging
        from datetime import datetime, timezone
        from app.models.archana import (
            ArchanaBookingPayment, OnlineSettlementLedger, ArchanaRefund, ArchanaStatus
        )
        from app.core.payments.razorpay_provider import RazorpayProvider
        from app.modules.audit.services.activity_log_service import ActivityLogService
        
        srv_logger = logging.getLogger("tms.services.devotee_booking.refund")
        
        # 1. Fetch payment details
        pay_stmt = select(ArchanaBookingPayment).filter(
            ArchanaBookingPayment.booking_id == booking.id,
            ArchanaBookingPayment.status == "SUCCESS"
        )
        pay_res = await db.execute(pay_stmt)
        payment = pay_res.scalar_one_or_none()
        if not payment:
            srv_logger.warning("No successful payment found for booking %s. Cannot refund.", booking.id)
            return False
            
        if payment.settlement_status == "REFUNDED":
            srv_logger.info("Payment for booking %s already refunded.", booking.id)
            return True

        # Update payment status
        payment.settlement_status = "REFUNDED"
        booking.online_status = "REFUND_INITIATED"
        booking.status = ArchanaStatus.CANCELLED # Ensure it's cancelled

        # 2. Call Razorpay Refund API
        refund_amount = payment.total_amount_charged  # 100% refund of devotee payment
        try:
            rzp_refund = await RazorpayProvider.create_refund(payment.gateway_payment_id, refund_amount)
            gateway_refund_id = rzp_refund.get("id")
            gateway_refund_status = rzp_refund.get("status", "processed")
        except Exception as e:
            srv_logger.error("Failed to create Razorpay refund: %s. Proceeding with database records in pending refund status.", e)
            gateway_refund_id = f"rfnd_failed_{booking.id.hex[:8]}"
            gateway_refund_status = "failed"

        # 3. Create ArchanaRefund record
        from sqlalchemy import func
        count_stmt = select(func.count(ArchanaRefund.id)).filter(ArchanaRefund.temple_id == booking.temple_id)
        count_res = await db.execute(count_stmt)
        refund_count = count_res.scalar() or 0
        ref_id = f"REF-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(refund_count + 1).zfill(4)}"

        now_utc = datetime.now(timezone.utc)
        refund_record = ArchanaRefund(
            temple_id=booking.temple_id,
            ref_id=ref_id,
            booking_id=booking.id,
            refund_method="UPI",
            refund_status="Full",
            status="SUCCESS" if gateway_refund_status == "processed" else "PENDING",
            amount=refund_amount,
            reason="Temple Rejection / Devotee Cancellation",
            created_by=actor_id,
            created_at=now_utc,
            gateway_refund_id=gateway_refund_id,
            gateway_refund_status=gateway_refund_status,
            refund_initiated_at=now_utc,
            archana_refund_amount=payment.archana_amount,
            fee_refund_amount=payment.convenience_fee,
            total_refund_amount=refund_amount
        )
        db.add(refund_record)

        # 4. Append OnlineSettlementLedger REFUND_DEBIT entry
        ledger_entry = OnlineSettlementLedger(
            temple_id=booking.temple_id,
            booking_id=booking.id,
            payment_id=payment.id,
            entry_type="REFUND_DEBIT",
            archana_amount=-payment.archana_amount,
            temple_net_amount=-payment.archana_amount,
            gross_convenience_fee=-payment.convenience_fee,
            taxable_fee=-cls.round_decimal_float(payment.convenience_fee / 1.18),
            gst_component=-(payment.convenience_fee - cls.round_decimal_float(payment.convenience_fee / 1.18)),
            cgst_component=-(cls.round_decimal_float((payment.convenience_fee - cls.round_decimal_float(payment.convenience_fee / 1.18)) / 2)),
            sgst_component=-((payment.convenience_fee - cls.round_decimal_float(payment.convenience_fee / 1.18)) - cls.round_decimal_float((payment.convenience_fee - cls.round_decimal_float(payment.convenience_fee / 1.18)) / 2)),
            gateway_fee=-payment.gateway_fee,
            gateway_tax=-payment.gateway_tax,
            net_platform_revenue=-(payment.convenience_fee - (payment.convenience_fee - cls.round_decimal_float(payment.convenience_fee / 1.18)) - payment.gateway_fee),
            total_charged_to_devotee=-refund_amount,
            gateway_payment_id=payment.gateway_payment_id,
            is_settled=False,
            created_at=now_utc
        )
        db.add(ledger_entry)

        # 5. Emit outbox event
        await ActivityLogService.emit_event(
            db=db,
            temple_id=booking.temple_id,
            module_name="BOOKINGS",
            entity_name="ArchanaBooking",
            entity_id=str(booking.id),
            action_type="BOOKING_REJECTED",
            action_category="BOOKING_REFUND",
            description=f"Online booking {booking.ref_id} rejected/cancelled. Refund of {refund_amount} initiated.",
            before_value={"online_status": "PAYMENT_SUCCESS"},
            after_value={"online_status": "REFUND_INITIATED", "refund_id": str(refund_record.id)},
            performed_by_user_id=actor_id,
            performed_by_name="Temple Manager / Staff",
            performed_by_role="STAFF",
            severity="INFO",
            risk_score=0
        )

        await db.flush()

        return True

    @staticmethod
    def round_decimal_float(val: float) -> float:
        from decimal import Decimal, ROUND_HALF_UP
        return float(Decimal(str(val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


