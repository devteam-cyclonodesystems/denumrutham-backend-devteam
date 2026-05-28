import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.hall_booking import PricingRule

logger = logging.getLogger("tms.services.booking_pricing")

class PricingEngineService:
    @staticmethod
    async def calculate_price(
        db: AsyncSession,
        temple_id: str,
        hall_id: str,
        base_amount: float,
        discount_amount: float = 0.0,
        booking_date: str = None
    ) -> dict:
        """
        Calculate total price applying any active pricing rules.
        """
        tid = UUID(str(temple_id))
        hid = UUID(str(hall_id))
        
        # Get active rules
        rules_query = select(PricingRule).filter(
            PricingRule.temple_id == tid,
            PricingRule.is_active == True
        )
        result = await db.execute(rules_query)
        rules = result.scalars().all()
        
        # Filter rules for this hall or global rules
        applicable_rules = [r for r in rules if r.hall_id is None or r.hall_id == hid]
        applicable_rules.sort(key=lambda r: r.priority, reverse=True)
        
        final_amount = base_amount
        applied_rules_info = []
        
        for rule in applicable_rules:
            if rule.adjustment_type == "PERCENTAGE":
                adj = (final_amount * rule.adjustment_value) / 100
                final_amount += adj
                applied_rules_info.append({"rule": rule.name, "adjustment": adj})
            elif rule.adjustment_type == "FIXED_AMOUNT":
                final_amount += rule.adjustment_value
                applied_rules_info.append({"rule": rule.name, "adjustment": rule.adjustment_value})
                
        # Apply manual discount
        final_amount -= discount_amount
        if final_amount < 0:
            final_amount = 0
            
        return {
            "base_amount": base_amount,
            "discount_amount": discount_amount,
            "final_amount": final_amount,
            "applied_rules": applied_rules_info
        }
