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

api_router = APIRouter()

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

# ── Governance & RBAC ────────────────────────────────────────────────
api_router.include_router(rbac.router, prefix="/rbac", tags=["Access Control (RBAC)"])
api_router.include_router(audit.router, prefix="/audit-logs", tags=["Audit Trails"])
api_router.include_router(activity_logs.router, prefix="/manager/activity-logs", tags=["Activity Logs"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["Legacy Approvals"])
api_router.include_router(change_requests.router, prefix="/change-requests", tags=["Change Requests"])

# ── Admin & Management ───────────────────────────────────────────────
api_router.include_router(superadmin.router, prefix="/superadmin", tags=["Super Admin"])
api_router.include_router(manager_dashboard.router, prefix="/manager", tags=["Manager Dashboard"])
api_router.include_router(admin.router, prefix="/admin", tags=["Platform Admin"])
api_router.include_router(staff.router, prefix="/staff", tags=["Staff Management"])

# ── Module Specific Routers ──────────────────────────────────────────
api_router.include_router(halls.router, prefix="/manager", tags=["Hall Management"])
api_router.include_router(offerings.router, prefix="/manager", tags=["Offering Management"])
api_router.include_router(employees.router, prefix="/employees", tags=["HR & Payroll"])
api_router.include_router(archana_bookings.router, prefix="/archana-bookings", tags=["Archana Bookings"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["Financial Transactions"])
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
