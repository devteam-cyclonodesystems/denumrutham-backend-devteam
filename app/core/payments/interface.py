from abc import ABC, abstractmethod
from typing import Dict, Any
from uuid import UUID

class IPaymentProvider(ABC):
    @abstractmethod
    async def create_payment(self, amount: float, reference_id: UUID) -> Dict[str, Any]:
        """Create a payment order/transaction with the gateway."""
        pass

    @abstractmethod
    async def verify_payment(self, transaction_id: str, payload: Dict[str, Any]) -> bool:
        """Verify the payment with the gateway."""
        pass
