import os
import logging

logger = logging.getLogger("tms.feature_flags")

# Default in-memory feature flag state
DEFAULT_FLAGS = {
    "auction_module": True,
    "advanced_procurement": True,
    "reservation_enforcement": True,
    "reconciliation_engine": True,
    "low_stock_automation": True,
    "observability_dashboards": True
}

class FeatureFlagManager:
    """Manages operational feature toggles for runtime system governance."""
    
    def __init__(self):
        self.flags = DEFAULT_FLAGS.copy()
        self.reload_flags()

    def reload_flags(self):
        """Load and override flags from environment variables."""
        for flag_name in DEFAULT_FLAGS:
            env_var = f"TMS_FEATURE_{flag_name.upper()}"
            env_val = os.getenv(env_var)
            if env_val is not None:
                parsed_val = env_val.lower() in ("true", "1", "yes")
                if self.flags[flag_name] != parsed_val:
                    logger.info(f"Feature Flag Override: {flag_name} = {parsed_val} (via {env_var})")
                    self.flags[flag_name] = parsed_val

    def is_enabled(self, feature_name: str) -> bool:
        """Check if a feature flag is currently active."""
        # Auto-reload in development mode if env updates, in production cached
        self.reload_flags()
        return self.flags.get(feature_name, False)

# Singleton manager instance
feature_flags = FeatureFlagManager()
