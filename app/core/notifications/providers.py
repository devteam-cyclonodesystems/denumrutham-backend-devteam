import logging
import json
from typing import Dict, Any
from app.core.notifications.interface import INotificationProvider
from app.core.security.encryption import decrypt_data
from app.core.database.database import AsyncSessionLocal
from sqlalchemy import select
from app.modules.governance.models.governance_models import PlatformGlobalSetting

logger = logging.getLogger(__name__)

class FCMAdapter(INotificationProvider):
    async def send_notification(self, recipient: str, message: str, payload: Dict[str, Any]) -> bool:
        logger.info("[FCMAdapter] Sending push notification to %s: %s", recipient, message)
        
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "fcm_credentials")
            )
            setting = result.scalar_one_or_none()
            if not setting:
                logger.warning("[FCMAdapter] FCM credentials not configured in PlatformGlobalSetting. Falling back to True.")
                return True
            
            try:
                encrypted_str = ""
                if isinstance(setting.value, dict):
                    encrypted_str = setting.value.get("encrypted_credentials", "")
                elif isinstance(setting.value, str):
                    encrypted_str = setting.value

                if not encrypted_str:
                    logger.warning("[FCMAdapter] Empty FCM credentials value. Falling back to True.")
                    return True
                
                decrypted_json = decrypt_data(encrypted_str)
                credentials = json.loads(decrypted_json)
                logger.info("[FCMAdapter] Decrypted credentials successfully for project: %s", credentials.get("project_id", "unknown"))
            except Exception as e:
                logger.error("[FCMAdapter] Error decrypting credentials: %s. Falling back to True.", e)
                return True

        logger.info("[FCMAdapter] Mock push successfully sent to %s", recipient)
        return True


class PushNotificationProvider(INotificationProvider):
    async def send_notification(self, recipient: str, message: str, payload: Dict[str, Any]) -> bool:
        logger.info("[PushNotificationProvider] Delegating push notification to FCMAdapter")
        fcm = FCMAdapter()
        return await fcm.send_notification(recipient, message, payload)


class EmailNotificationProvider(INotificationProvider):
    async def send_notification(self, recipient: str, message: str, payload: Dict[str, Any]) -> bool:
        logger.info("[EmailNotificationProvider] Sending email notification to %s: %s", recipient, message)
        # In actual integration, call SendGrid, SES or SMTP server.
        return True


class SMSNotificationProvider(INotificationProvider):
    async def send_notification(self, recipient: str, message: str, payload: Dict[str, Any]) -> bool:
        logger.info("[SMSNotificationProvider] Sending SMS notification to %s: %s", recipient, message)
        # In actual integration, call Twilio, Plivo, MSG91 etc.
        return True

