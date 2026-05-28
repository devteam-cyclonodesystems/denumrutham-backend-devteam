import io
import base64
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.archana import EnterpriseArchanaBooking
from app.models.domain import Temple
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("tms.services.receipt")

class ReceiptService:
    @staticmethod
    def generate_qr(data: str) -> str:
        """Generates a base64 encoded QR code for thermal/digital receipts."""
        try:
            import qrcode
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode()
        except Exception as e:
            logger.error(f"Failed to generate QR: {str(e)}")
            return ""

    @staticmethod
    async def get_receipt_manifest(db: AsyncSession, booking: EnterpriseArchanaBooking) -> Dict[str, Any]:
        """Generates a complete enterprise receipt manifest including security tokens."""
        
        # Resolve Temple Name dynamically
        temple_name = "Temple Name Not Configured"
        try:
            res = await db.execute(select(Temple.name).filter(Temple.id == booking.temple_id))
            name = res.scalar()
            if name:
                temple_name = name
        except Exception as e:
            logger.error(f"Failed to resolve temple name for receipt: {str(e)}")
        
        # Security/Audit Token for offline verification
        verification_token = f"TMS|{booking.ref_id}|{booking.grand_total}|{booking.temple_id}"
        qr_code_b64 = ReceiptService.generate_qr(verification_token)
        
        manifest = {
            "header": {
                "temple_name": temple_name,
                "ref_id": booking.ref_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operator": "Counter Admin",
                "sync_status": "SYNCHRONIZED"
            },
            "devotee": {
                "name": booking.primary_devotee_name,
                "phone": booking.phone_number,
                "family_members": [
                    {
                        "name": m.name,
                        "nakshatra": m.nakshatra,
                        "items": [
                            {"name": i.ritual_name_snapshot, "price": i.price_at_booking, "qty": i.quantity} 
                            for i in m.items
                        ]
                    } for m in booking.members
                ]
            },
            "financial": {
                "subtotal": booking.total_amount,
                "dakshina": booking.dakshina,
                "grand_total": booking.grand_total,
                "payment_mode": booking.payment_mode,
                "currency": "INR"
            },
            "operational": {
                "token_number": booking.queue_entry.token_number if booking.queue_entry else "N/A",
                "queue_priority": "High" if booking.priority_slot else "Normal"
            },
            "security": {
                "qr_code": f"data:image/png;base64,{qr_code_b64}",
                "verification_hash": hash(verification_token) # Simplified hash for UI display
            }
        }
        
        return manifest
