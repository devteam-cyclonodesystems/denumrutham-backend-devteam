import logging
import urllib.parse
from typing import Dict, Any
from uuid import UUID
from app.core.payments.interface import IPaymentProvider

logger = logging.getLogger(__name__)

class MockPaymentProvider(IPaymentProvider):
    async def create_payment(self, amount: float, reference_id: UUID) -> Dict[str, Any]:
        logger.info("[MockPaymentProvider] Creating mock payment of %s INR for reference %s", amount, reference_id)
        return {
            "status": "SUCCESS",
            "transaction_id": f"txn_mock_{reference_id}",
            "amount": amount,
            "provider": "MOCK"
        }

    async def verify_payment(self, transaction_id: str, payload: Dict[str, Any]) -> bool:
        logger.info("[MockPaymentProvider] Verifying mock payment transaction %s", transaction_id)
        return True


class UPIQRAdapter(IPaymentProvider):
    def __init__(self, base_provider: MockPaymentProvider = None):
        self.base_provider = base_provider or MockPaymentProvider()

    async def create_payment(self, amount: float, reference_id: UUID) -> Dict[str, Any]:
        base_txn = await self.base_provider.create_payment(amount, reference_id)
        
        # Build UPI QR parameters
        merchant_vpa = "temple@upi"
        merchant_name = "Denumrutham Temple"
        transaction_ref = base_txn["transaction_id"]
        notes = f"Pooja Offering reference {reference_id}"
        
        # Standard UPI deep link format
        upi_link = f"upi://pay?pa={merchant_vpa}&pn={urllib.parse.quote(merchant_name)}&am={amount:.2f}&tr={transaction_ref}&tn={urllib.parse.quote(notes)}"
        
        base_txn.update({
            "provider": "UPI_QR",
            "upi_link": upi_link
        })
        return base_txn

    async def verify_payment(self, transaction_id: str, payload: Dict[str, Any]) -> bool:
        return await self.base_provider.verify_payment(transaction_id, payload)

