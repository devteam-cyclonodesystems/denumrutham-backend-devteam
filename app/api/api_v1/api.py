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
from app.modules.billing.routes.settlements import router as settlements_router
from app.modules.analytics.routes.telemetry import (
    public_router as telemetry_public_router,
    manager_router as telemetry_manager_router,
    superadmin_router as telemetry_superadmin_router,
)

api_router = APIRouter()

# ── Public Temple Portal & Telemetry ─────────────────────────────────
api_router.include_router(public_portal.router, prefix="/public/temples", tags=["Public Temple Portal"])
api_router.include_router(public_portal.directory_router, prefix="/public/directory", tags=["Public Directory"])
api_router.include_router(public_portal.public_router, prefix="/public", tags=["Public Platform Directory"])
api_router.include_router(telemetry_public_router, prefix="/public", tags=["Public Telemetry"])

# ── Core Infrastructure ───────────────────────────────────────────────
api_router.include_router(sync.router, prefix="/sync", tags=["System Sync"])
api_router.include_router(health.router, prefix="/health", tags=["Health Check"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(system.router, prefix="/system", tags=["System Integrity"])

# ── Domain Entities & Operations ──────────────────────────────────────
api_router.include_router(devotees.router, prefix="/devotees", tags=["Devotees"])
api_router.include_router(poojas.router, prefix="/poojas", tags=["Poojas & Offerings"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["Bookings"])
api_router.include_router(donations.router, prefix="/donations", tags=["Donations"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(temples.router, prefix="/temples", tags=["Temples"])
api_router.include_router(upload.router, prefix="/upload", tags=["Media Uploads"])
api_router.include_router(payments.router, prefix="/payments", tags=["Payment Processing"])
api_router.include_router(subscriptions_router, prefix="/subscriptions", tags=["Subscriptions"])

# ── Governance & RBAC ────────────────────────────────────────────────
api_router.include_router(rbac.router, prefix="/rbac", tags=["Access Control (RBAC)"])
api_router.include_router(claims_router, prefix="/claims", tags=["Temple Claims"])
api_router.include_router(suggestions_router, prefix="/temple-suggestions", tags=["Temple Suggestions"])
api_router.include_router(audit.router, prefix="/audit-logs", tags=["Audit Trails"])
api_router.include_router(activity_logs.router, prefix="/manager/activity-logs", tags=["Activity Logs"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["Legacy Approvals"])
api_router.include_router(change_requests.router, prefix="/change-requests", tags=["Change Requests"])


# ── Admin & Management ───────────────────────────────────────────────
api_router.include_router(superadmin.router, prefix="/superadmin", tags=["Super Admin"])
api_router.include_router(platform_ads_router, prefix="/superadmin", tags=["Platform Advertisements"])
api_router.include_router(telemetry_superadmin_router, prefix="/superadmin", tags=["Super Admin Telemetry"])
api_router.include_router(manager_dashboard.router, prefix="/manager", tags=["Manager Dashboard"])
api_router.include_router(admin.router, prefix="/admin", tags=["Platform Admin"])
api_router.include_router(staff.router, prefix="/staff", tags=["Staff Management"])

# ── Module Specific Routers ──────────────────────────────────────────
api_router.include_router(halls.router, prefix="/manager", tags=["Hall Management"])
api_router.include_router(offerings.router, prefix="/manager", tags=["Offering Management"])
api_router.include_router(digital_experience.router, prefix="/manager", tags=["Digital Experience Portal"])
api_router.include_router(profile.router, prefix="/temple-profile", tags=["Temple Profile Management"])
api_router.include_router(recommendations.router, prefix="/manager", tags=["Recommendation Management"])
api_router.include_router(temple_ads_router, prefix="/manager", tags=["Temple Advertisements"])
api_router.include_router(telemetry_manager_router, prefix="/manager", tags=["Manager Telemetry"])
api_router.include_router(employees.router, prefix="/employees", tags=["HR & Payroll"])
api_router.include_router(archana_bookings.router, prefix="/archana-bookings", tags=["Archana Bookings"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["Financial Transactions"])
api_router.include_router(settlements_router, prefix="", tags=["Settlement Management"])
api_router.include_router(inventory_routes.router, prefix="/inventory", tags=["Inventory Management"])
api_router.include_router(dashboard_routes.router, prefix="/dashboard", tags=["Analytics Dashboard"])

# ── Devotee Features ──────────────────────────────────────────────────
api_router.include_router(devotee_bookings.router, prefix="/devotee", tags=["Devotee Portal"])
api_router.include_router(cart.router, prefix="/store", tags=["Store & Cart"])
api_router.include_router(store_routes.router, prefix="/store", tags=["Store Commerce"])
api_router.include_router(follow.router, prefix="/follow", tags=["Social / Follow"])
api_router.include_router(booking_history.router, prefix="/booking-history", tags=["Booking History"])

# ── Onboarding & Registration (Fix #8) ───────────────────────────────
# Public registration path
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["Temple Onboarding (Public)"])
# Admin onboarding management path
api_router.include_router(onboarding.admin_router, prefix="/admin/onboarding", tags=["Temple Onboarding (Admin)"])
