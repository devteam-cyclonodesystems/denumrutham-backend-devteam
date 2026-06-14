import logging
from sqlalchemy import inspect
from app.core.config import settings
from app.modules.temple_management.models.temple_models import Temple

logger = logging.getLogger("TempleResolver")

class TempleWebsiteLifecycleResolver:
    @staticmethod
    def resolve_stage(temple: Temple) -> str:
        """
        Determines the active website maturity stage for a temple.
        Safely inspects preloaded relationships to catch eager-loading omissions early.
        """
        if temple.management_mode in ("GOVERNED", "SELF_MANAGED"):
            return "TEMPLE_MANAGED"
            
        if temple.management_mode == "DIRECTORY_ONLY":
            insp = inspect(temple)
            if "website_settings_live" in insp.unloaded:
                # Eager-loading omission detected!
                msg = f"Developer Error: website_settings_live relationship was not preloaded for temple {temple.id} ({temple.name})."
                
                # Fail-fast during development/testing
                if settings.ENVIRONMENT.lower() in ("development", "test", "testing"):
                    raise AssertionError(msg)
                else:
                    # In production, check if the session is detached
                    if insp.detached:
                        logger.error(msg + " Instance is detached; cannot lazy load. Falling back to Stage 1.")
                        return "DIRECTORY_TEMPLATE"
                    else:
                        # Warn about the N+1 query but allow lazy-loading to get the correct state
                        logger.warning(msg + " Lazy-loading from database (N+1 query).")
                
            if temple.website_settings_live is not None:
                return "DENUMRUTHAM_MANAGED"
                
            return "DIRECTORY_TEMPLATE"
            
        return "DIRECTORY_TEMPLATE"
