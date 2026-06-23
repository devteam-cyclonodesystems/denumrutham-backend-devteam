import logging
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modules.governance.models.governance_models import PlatformGlobalSetting

logger = logging.getLogger("tms.services.platform_fee_engine")

class PlatformFeeEngine:
    @staticmethod
    def round_decimal(val: Decimal) -> Decimal:
        return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @classmethod
    async def calculate_fee(cls, db: AsyncSession, archana_amount: float) -> dict:
        """
        Calculate platform convenience fee and splits.
        Default config: 2% rate, min ₹2.00, max ₹10.00.
        All math uses Decimal for financial precision.
        """
        # Fetch configurations from database settings with fallback
        fee_rate = Decimal("0.02")
        min_fee = Decimal("2.00")
        max_fee = Decimal("10.00")

        try:
            stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "platform_fee_config")
            res = await db.execute(stmt)
            setting = res.scalar_one_or_none()
            if setting and isinstance(setting.value, dict):
                fee_rate = Decimal(str(setting.value.get("fee_rate", "0.02")))
                min_fee = Decimal(str(setting.value.get("min_fee", "2.00")))
                max_fee = Decimal(str(setting.value.get("max_fee", "10.00")))
        except Exception as e:
            logger.error("Failed to load platform_fee_config setting: %s. Using default fallback.", e)

        dec_amount = Decimal(str(archana_amount))
        
        # Calculate raw fee
        raw_fee = dec_amount * fee_rate
        
        # Clamp between min and max
        gross_convenience_fee = raw_fee
        if gross_convenience_fee < min_fee:
            gross_convenience_fee = min_fee
        elif gross_convenience_fee > max_fee:
            gross_convenience_fee = max_fee
            
        gross_convenience_fee = cls.round_decimal(gross_convenience_fee)
        
        # Split GST (18% inclusive GST)
        # Taxable Value = Gross / 1.18
        # GST Component = Gross - Taxable Value
        # CGST = GST / 2, SGST = GST - CGST
        taxable_fee = cls.round_decimal(gross_convenience_fee / Decimal("1.18"))
        gst_component = gross_convenience_fee - taxable_fee
        cgst_component = cls.round_decimal(gst_component / Decimal("2"))
        sgst_component = gst_component - cgst_component
        
        total_payable = dec_amount + gross_convenience_fee

        return {
            "archana_amount": float(dec_amount),
            "gross_convenience_fee": float(gross_convenience_fee),
            "taxable_fee": float(taxable_fee),
            "gst_component": float(gst_component),
            "cgst_component": float(cgst_component),
            "sgst_component": float(sgst_component),
            "total_payable": float(total_payable)
        }
