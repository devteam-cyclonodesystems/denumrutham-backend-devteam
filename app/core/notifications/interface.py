from abc import ABC, abstractmethod
from typing import Dict, Any

class INotificationProvider(ABC):
    @abstractmethod
    async def send_notification(self, recipient: str, message: str, payload: Dict[str, Any]) -> bool:
        """Send notification via a specific channel (SMS, Email, Push)."""
        pass
