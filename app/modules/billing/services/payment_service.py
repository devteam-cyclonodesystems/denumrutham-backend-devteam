import logging
from typing import Optional, Dict, Any
from uuid import UUID

logger = logging.getLogger("tms")

class PaymentService:
    """
    Abstracts calls to external payment gateways like Razorpay or Stripe.
    """

    @staticmethod
    async def create_razorpay_order(amount: float, receipt_id: str) -> Dict[str, Any]:
        """
        Stub: Create an order in Razorpay.
        In production, use razorpay-python SDK.
        """
        logger.info(f"Initiated mock Razorpay order for {amount} INR (receipt: {receipt_id})")
        return {
            "id": f"order_mock_{receipt_id}",
            "amount": amount * 100, # paise
            "currency": "INR",
            "receipt": receipt_id,
            "status": "created"
        }

    @staticmethod
    async def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
        """
        Stub: Verify Razorpay webhook/signature.
        """
        logger.info(f"Verified mock signature for order {order_id}")
        return True
