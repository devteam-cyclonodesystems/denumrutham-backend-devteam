# Import Base
from app.db.session import Base

# Import ALL models so Alembic detects them
from app.models.domain import *
from app.models.rbac import *
from app.models.system_rbac import *
from app.models.onboarding import *
from app.models.archana import *
from app.models.accounting import *
from app.models.system import *

# New models added in stabilization phase:
# - ChangeRequest (field-level change approval)
# - TempleFollower (devotee follows temple)
# - Cart, CartItem (shopping cart)
# - Address (self + gift delivery)
# - GuestBooking (unauthenticated booking)
# All imported via domain.py wildcard above.

# System RBAC models (system_rbac.py):
# - SystemRole, SystemPermission, SystemRolePermission
# Imported above for Alembic detection.

# Onboarding models (onboarding.py):
# - TempleRequest, UserRequest
# Imported above for Alembic detection.
