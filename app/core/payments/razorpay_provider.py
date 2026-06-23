import hmac
import hashlib
import logging
import httpx
import os
from typing import Dict, Any
from sqlalchemy import select
from app.core.database.database import AsyncSessionLocal
from app.modules.governance.models.governance_models import PlatformGlobalSetting

logger = logging.getLogger("tms.payments.razorpay")

class RazorpayProvider:
    @classmethod
    async def get_credentials(cls) -> tuple[str, str]:
        """
        Get Razorpay key_id and key_secret from environment or PlatformGlobalSetting.
        """
        key_id = os.getenv("RAZORPAY_KEY_ID", "")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
        
        if not key_id or not key_secret:
            try:
                async with AsyncSessionLocal() as db:
                    stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "razorpay_config")
                    res = await db.execute(stmt)
                    setting = res.scalar_one_or_none()
                    if setting and isinstance(setting.value, dict):
                        key_id = setting.value.get("key_id", key_id)
                        key_secret = setting.value.get("key_secret", key_secret)
            except Exception as e:
                logger.error("Failed to load razorpay_config from database: %s", e)
                
        return key_id, key_secret

    @classmethod
    async def create_order(cls, amount: float, receipt_ref: str) -> Dict[str, Any]:
        """
        Create a Razorpay Order.
        amount is in INR (e.g., 102.00). It is converted to paise internally.
        """
        key_id, key_secret = await cls.get_credentials()
        amount_in_paise = int(round(amount * 100))
        
        # If no credentials, behave in mock mode
        if not key_id or key_id == "mock":
            logger.info("[RazorpayProvider] Running in MOCK mode. Creating mock order.")
            return {
                "id": f"order_mock_{receipt_ref}",
                "entity": "order",
                "amount": amount_in_paise,
                "amount_paid": 0,
                "amount_due": amount_in_paise,
                "currency": "INR",
                "receipt": receipt_ref,
                "status": "created",
                "created_at": 1600000000
            }
            
        url = "https://api.razorpay.com/v1/orders"
        data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": receipt_ref,
            "payment_capture": 1
        }
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    url,
                    json=data,
                    auth=(key_id, key_secret),
                    headers={"Content-Type": "application/json"},
                    timeout=10.0
                )
                if resp.status_code != 200:
                    logger.error("Razorpay order creation failed: %s %s", resp.status_code, resp.text)
                    raise Exception(f"Razorpay API error: {resp.text}")
                return resp.json()
            except Exception as e:
                logger.error("Error calling Razorpay API: %s", e)
                raise

    @classmethod
    def verify_webhook_signature(cls, payload_body: bytes, signature: str, secret: str) -> bool:
        """
        Verify the signature of incoming webhook events from Razorpay.
        """
        if not secret or secret == "mock":
            logger.warning("[RazorpayProvider] Webhook secret not configured or is mock. Verification skipped.")
            return True
            
        expected = hmac.new(
            secret.encode("utf-8"),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)

    @classmethod
    async def create_refund(cls, payment_id: str, amount: float) -> Dict[str, Any]:
        """
        Initiate a refund on Razorpay.
        amount is in INR.
        """
        key_id, key_secret = await cls.get_credentials()
        amount_in_paise = int(round(amount * 100))
        
        if not key_id or key_id == "mock" or payment_id.startswith("pay_mock_"):
            logger.info("[RazorpayProvider] Running in MOCK mode. Refunding payment %s.", payment_id)
            return {
                "id": f"rfnd_mock_{payment_id}",
                "entity": "refund",
                "amount": amount_in_paise,
                "currency": "INR",
                "payment_id": payment_id,
                "status": "processed",
                "created_at": 1600000000
            }
            
        url = f"https://api.razorpay.com/v1/payments/{payment_id}/refund"
        data = {
            "amount": amount_in_paise
        }
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    url,
                    json=data,
                    auth=(key_id, key_secret),
                    headers={"Content-Type": "application/json"},
                    timeout=10.0
                )
                if resp.status_code not in (200, 201):
                    logger.error("Razorpay refund failed: %s %s", resp.status_code, resp.text)
                    raise Exception(f"Razorpay API refund error: {resp.text}")
                return resp.json()
            except Exception as e:
                logger.error("Error calling Razorpay refund API: %s", e)
                raise
