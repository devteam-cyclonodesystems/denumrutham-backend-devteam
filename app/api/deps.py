from app.core.database import get_db
from app.core.deps import (
    get_current_user,
    get_current_user_optional,
    get_current_active_admin,
    get_current_superadmin,
    get_current_devotee,
    get_current_temple_manager,
    get_current_staff,
    get_accessible_temple_ids,
    get_current_temple_id,
    require_permission,
    require_system_permission,
    apply_tenant_filter,
    enforce_active_subscription,
    enforce_management_mode,
)

# Alias for tenant enforcement — extracts temple_id from JWT token
get_current_tenant = get_current_temple_id

# This file consolidates core dependencies to serve as the single source for the API layer.
