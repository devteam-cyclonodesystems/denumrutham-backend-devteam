from fastapi import APIRouter
from app.api.api_v1.endpoints import (
    auth, devotees, poojas, bookings, donations, rbac,
    temples, devotee_bookings, superadmin,
    halls, employees, archana_bookings, transactions,
    inventory_routes, dashboard_routes, health, sync, system, store_routes
)
from app.api.api_v1.routes import audit, approvals, activity_logs
from app.api.routes import (
    notifications, change_requests, cart, follow, 
    booking_history, manager_dashboard, upload, 
    payments, onboarding, admin, staff, offerings
)
from app.modules.temple_management.routes import digital_experience, public_portal, recommendations, profile
from app.modules.governance.routes.platform_advertisements import router as platform_ads_router
from app.modules.temple_management.routes.temple_advertisements import router as temple_ads_router
from app.modules.governance.routes.claims import router as claims_router
from app.modules.governance.routes.suggestions import router as suggestions_router
from app.modules.billing.routes.subscriptions import router as subscriptions_router
from app.modules.finance.routes.finance_routes import router as finance_router
from app.modules.analytics.routes.telemetry import (
    public_router as telemetry_public_router,
    manager_router as telemetry_manager_router,
    superadmin_router as telemetry_superadmin_router,
)

api_router = APIRouter()

# ── Public Temple Portal & Telemetry ─────────────────────────────────
api_router.include_router(public_portal.router, prefix="/public/temples", tags=["Discovery"])
api_router.include_router(public_portal.directory_router, prefix="/public/directory", tags=["Discovery"])
api_router.include_router(public_portal.public_router, prefix="/public", tags=["Discovery"])
api_router.include_router(telemetry_public_router, prefix="/public", tags=["Analytics"])

# ── Core Infrastructure ───────────────────────────────────────────────
api_router.include_router(sync.router, prefix="/sync", tags=["System"])
api_router.include_router(health.router, prefix="/health", tags=["System"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(system.router, prefix="/system", tags=["System"])

# ── Domain Entities & Operations ──────────────────────────────────────
api_router.include_router(devotees.router, prefix="/devotees", tags=["Bookings"])
api_router.include_router(poojas.router, prefix="/poojas", tags=["Poojas"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["Bookings"])
api_router.include_router(donations.router, prefix="/donations", tags=["Finance"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(temples.router, prefix="/temples", tags=["Platform Governance"])
api_router.include_router(upload.router, prefix="/upload", tags=["System"])
api_router.include_router(payments.router, prefix="/payments", tags=["Finance"])
api_router.include_router(subscriptions_router, prefix="/subscriptions", tags=["Platform Governance"])

# ── Governance & RBAC ────────────────────────────────────────────────
api_router.include_router(rbac.router, prefix="/rbac", tags=["Settings"])
api_router.include_router(claims_router, prefix="/claims", tags=["Platform Governance"])
api_router.include_router(suggestions_router, prefix="/temple-suggestions", tags=["Platform Governance"])
api_router.include_router(audit.router, prefix="/audit-logs", tags=["Audit"])
api_router.include_router(activity_logs.router, prefix="/manager/activity-logs", tags=["Audit"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["Platform Governance"])
api_router.include_router(change_requests.router, prefix="/change-requests", tags=["Platform Governance"])


# ── Admin & Management ───────────────────────────────────────────────
api_router.include_router(superadmin.router, prefix="/superadmin", tags=["Platform Governance"])
api_router.include_router(platform_ads_router, prefix="/superadmin", tags=["Advertisements"])
api_router.include_router(telemetry_superadmin_router, prefix="/superadmin", tags=["Analytics"])
api_router.include_router(manager_dashboard.router, prefix="/manager", tags=["Dashboard"])
api_router.include_router(admin.router, prefix="/admin", tags=["Platform Governance"])
api_router.include_router(staff.router, prefix="/staff", tags=["Temple Governance"])

# ── Module Specific Routers ──────────────────────────────────────────
api_router.include_router(halls.router, prefix="/manager", tags=["Hall Booking"])
api_router.include_router(offerings.router, prefix="/manager", tags=["Poojas"])
api_router.include_router(digital_experience.router, prefix="/manager", tags=["Website Builder"])
api_router.include_router(profile.router, prefix="/temple-profile", tags=["Temple Profile"])
api_router.include_router(recommendations.router, prefix="/manager", tags=["Discovery"])
api_router.include_router(temple_ads_router, prefix="/manager", tags=["Advertisements"])
api_router.include_router(telemetry_manager_router, prefix="/manager", tags=["Analytics"])
api_router.include_router(employees.router, prefix="/employees", tags=["Temple Governance"])
api_router.include_router(archana_bookings.router, prefix="/archana-bookings", tags=["Bookings"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["Finance"])
api_router.include_router(finance_router, prefix="", tags=["Finance"])
api_router.include_router(inventory_routes.router, prefix="/inventory", tags=["Inventory"])
api_router.include_router(dashboard_routes.router, prefix="/dashboard", tags=["Dashboard"])

# ── Devotee Features ──────────────────────────────────────────────────
api_router.include_router(devotee_bookings.router, prefix="/devotee", tags=["Bookings"])
api_router.include_router(cart.router, prefix="/store", tags=["Bookings"])
api_router.include_router(store_routes.router, prefix="/store", tags=["Inventory"])
api_router.include_router(follow.router, prefix="/follow", tags=["Discovery"])
api_router.include_router(booking_history.router, prefix="/booking-history", tags=["Bookings"])

# ── Onboarding & Registration (Fix #8) ───────────────────────────────
# Public registration path
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["Platform Governance"])
# Admin onboarding management path
api_router.include_router(onboarding.admin_router, prefix="/admin/onboarding", tags=["Platform Governance"])
