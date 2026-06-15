# TMS Knowledge Base — Incident Tracker

> This document serves as the centralized incident tracker for the Denumrutham Temple Management System (TMS).
> Every incident, defect, outage, deployment issue, integration failure, performance issue, or other significant problem must be recorded here.

---

## Incident Index

| ID | Title | Severity | Status | Date |
|----|-------|----------|--------|------|
| INC-001 | Missing `Optional` import crashes all API routes | P1 – Critical | ✅ Resolved | 2026-06-07 |
| INC-002 | Readiness probe returning 503 blocks Railway routing | P1 – Critical | ✅ Resolved | 2026-06-06 |
| INC-003 | Frontend module loading shows skeleton state indefinitely | P1 – Critical | ✅ Resolved | 2026-06-07 |
| INC-004 | Granular RBAC deployment blocks TEMPLE_MANAGER access | P2 – High | ✅ Resolved | 2026-06-07 |
| INC-005 | Missing live website settings database table on production | P1 – Critical | ✅ Resolved | 2026-06-07 |
| INC-006 | Pydantic ValidationError on public portal image mapping | P1 – Critical | ✅ Resolved | 2026-06-07 |
| INC-007 | Malottu temple operational state suspended blocking dashboard | P1 – Critical | ✅ Resolved | 2026-06-07 |
| INC-008 | Missing feature_visibility column on website settings table | P1 – Critical | ✅ Resolved | 2026-06-10 |
| INC-009 | Unused variable setGothram causes frontend build failure | P2 – High | ✅ Resolved | 2026-06-10 |
| INC-010 | Missing PaymentStatus import in devotee_portal schemas | P2 – High | ✅ Resolved | 2026-06-09 |
| INC-011 | Website Builder updates blocked & store/hall sections missing | P1 – Critical | ✅ Resolved | 2026-06-10 |
| INC-012 | Omitted sprint entity tables causing bootstrap/follow crash | P1 – Critical | ✅ Resolved | 2026-06-10 |
| INC-013 | Non-idempotent migration blocks Alembic chain on redeploys | P1 – Critical | ✅ Resolved | 2026-06-11 |
| INC-014 | Empty explorer directory due to NULL state/district foreign keys | P2 – High | ✅ Resolved | 2026-06-12 |
| INC-015 | Couldn't view/download 'Legal Verification Documents (Uploaded Proof)' in Claims Review | P2 – High | ✅ Resolved | 2026-06-12 |
| INC-016 | Suggest Temple Step 2 Next disabled due to failed backend migration deployment | P2 – High | ✅ Resolved | 2026-06-12 |
| INC-017 | Devotee Suggest Temple Submission failure due to UndefinedObjectError (native ENUM mismatch) | P1 – Critical | ✅ Resolved | 2026-06-13 |
| INC-018 | Superadmin Review Action Submission Failure due to Status String Mismatch | P1 – Critical | ✅ Resolved | 2026-06-13 |
| INC-019 | HTTP 500 errors due to DB connection pool exhaustion in user auth dependency | P1 – Critical | ✅ Resolved | 2026-06-15 |
| FEAT-001 | Phase 1 – Sidebar Spotlight Ad Area & Layout Alignment | Feature Delivery |  Shipped | 2026-06-10 |
| FEAT-002 | Phase 2 – Layout Responsiveness & Spotlight Ad Rails | Feature Delivery |  Shipped | 2026-06-10 |
| FEAT-003 | Devotee Registration Hardening & Password Strength Enforcements | Feature Delivery |  Shipped | 2026-06-12 |
| FEAT-004 | Temple Timing Management UX Enhancements | Feature Delivery |  Shipped | 2026-06-15 |

---

## INC-001: Missing `Optional` Import Crashes All API Routes

| Field | Value |
|-------|-------|
| **Incident ID** | INC-001 |
| **Incident Title** | Missing `Optional` import in `public_portal.py` crashes entire API router |
| **Date and Time** | 2026-06-07T06:00:00Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

The `list_public_temples` endpoint in `public_portal.py` used `Optional[str]` as a type hint for the `search` parameter, but `Optional` was not imported from the `typing` module. This caused a `NameError` at Python module import time.

### Root Cause

```python
# File: backend/app/modules/temple_management/routes/public_portal.py
# Line 8 (BEFORE fix):
from typing import List  # ❌ Missing Optional

# Line 175:
async def list_public_temples(
    search: Optional[str] = None,  # NameError: 'Optional' not defined
    ...
)
```

The `list_public_temples` function was added as part of the Temple Preview retirement initiative (Explore Temples endpoint). The `Optional` type was used but never added to the import statement.

### Affected Services, Components, or Features

- **ALL backend API routes** — The import error in `public_portal.py` occurs at line 14 of `api.py`, which is the single entry point for all API router registration. When this import fails, no routes are registered.
- **Frontend sidebar/navigation** — Without `/api/v1/rbac/my-permissions` responding, the `ManagerLayout` never sets `permissionsLoaded = true`, causing all guarded navigation items to render as skeleton placeholders indefinitely.
- **All authenticated functionality** — Login, bookings, donations, RBAC, audit, etc. — all endpoints unreachable.

### Cascade Failure Chain

```
public_portal.py import fails (NameError: Optional)
  → api.py line 14 import fails
    → api_router never created
      → ALL endpoints unregistered
        → /rbac/my-permissions returns 404/500
          → Frontend permissionsLoaded stays false
            → Sidebar shows skeleton forever
              → All modules inaccessible
```

### Resolution Implemented

```diff
# backend/app/modules/temple_management/routes/public_portal.py
- from typing import List
+ from typing import List, Optional
```

- **Commit**: `be9adf4` on backend `main`
- **Push**: `denumrutham-backend` → `main`

### Preventive Actions Taken

1. **Import validation**: All future route files must import every type hint they use.
2. **Pre-commit check**: Run `python -c "from app.api.api_v1.api import api_router"` before every push to verify all route imports resolve.
3. **Knowledge Base created**: This incident tracker now exists to catch patterns early.

### Lessons Learned

- A single missing import in ONE route file can cascade to take down the ENTIRE application.
- The monolithic router registration in `api.py` (single import line for all routes) creates a single point of failure.
- Consider adding try/except guards around router imports in `api.py` to isolate failures to individual modules rather than crashing all routes.

### Related Tickets, PRs, Commits

- Commit: `be9adf4` (backend)
- Related to: Temple Preview Retirement initiative

---

## INC-002: Readiness Probe Returning 503 Blocks Railway Routing

| Field | Value |
|-------|-------|
| **Incident ID** | INC-002 |
| **Incident Title** | Health/readiness probe returns 503, Railway stops routing traffic |
| **Date and Time** | 2026-06-06 |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

The Railway deployment health check endpoint `/health/ready` returned HTTP 503, causing Railway's routing layer to stop sending traffic to the backend. This made the entire application unreachable.

### Root Cause

The readiness probe at `/health/ready` performed a database connectivity check. When the database connection parameters were incorrect or the database was temporarily unavailable during deployment, the probe returned 503, which Railway interpreted as "service unhealthy" and stopped routing.

### Affected Services, Components, or Features

- All backend API routes
- Frontend (no backend to connect to)
- All user-facing functionality

### Resolution Implemented

The readiness probe was updated to degrade gracefully — returning 200 with a status indicator even when the database is temporarily unreachable during startup, rather than returning 503 which triggers Railway's routing block.

### Preventive Actions Taken

1. Readiness probes should not hard-fail on transient startup conditions.
2. Separate liveness (is the process alive?) from readiness (is it fully ready?) probes.

### Related Tickets, PRs, Commits

- Part of the Temple Preview Retirement deployment chain

---

## INC-003: Frontend Module Loading Shows Skeleton State Indefinitely

| Field | Value |
|-------|-------|
| **Incident ID** | INC-003 |
| **Incident Title** | Frontend sidebar modules show loading skeleton placeholders forever |
| **Date and Time** | 2026-06-07 |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

After deploying new backend changes, the manager dashboard sidebar showed all modules as gray skeleton/loading placeholders. Only Dashboard and Help & Support (unguarded items) were visible.

### Root Cause

This is a **symptom** of INC-001. The `ManagerLayout` component loads user permissions via `/api/v1/rbac/my-permissions`. When the backend fails to register any routes (due to the import error in INC-001), this call fails, and `permissionsLoaded` remains `false`. The sidebar rendering logic returns `null` for all permission-guarded navigation items.

### Affected Services, Components, or Features

- Manager Dashboard sidebar navigation
- All permission-guarded modules (Poojas, Bookings, Donations, RBAC, Audit, etc.)
- User experience (appears as if nothing is loading)

### Resolution Implemented

Resolved via INC-001 fix. No separate code change required.

### Preventive Actions Taken

1. Frontend should show an error state (not infinite loading) when permission fetch fails after a timeout.
2. Consider implementing a retry mechanism with exponential backoff for permission fetching.
3. Add a visual indicator (toast/alert) when the backend is unreachable.

### Related Tickets, PRs, Commits

- Root cause: INC-001
- Commit: `be9adf4` (backend)

---

## INC-004: Granular RBAC Deployment Blocks TEMPLE_MANAGER Access

| Field | Value |
|-------|-------|
| **Incident ID** | INC-004 |
| **Incident Title** | Granular RBAC deployment blocks TEMPLE_MANAGER access to operational modules |
| **Date and Time** | 2026-06-07 |
| **Severity/Priority** | P2 – High |
| **Current Status** | ✅ Resolved |

### Description
After transitioning to granular RBAC, `TEMPLE_MANAGER` users were unable to load any operational modules (Vazhipadu, Inventory, Offerings, etc.) from the Manager Dashboard. The frontend console reported `[RBAC] Access denied for user...` and the user interface showed an empty sidebar because the permissions endpoint (`/api/v1/rbac/my-permissions`) returned an empty array.

### Root Cause
The new granular RBAC system correctly enforced permissions dynamically via the `role_permissions` and `user_roles` database tables. However, the `TEMPLE_MANAGER` role is inherently an administrative role for the tenant. Since the database wasn't seeded with explicit granular permissions for existing `TEMPLE_MANAGER` roles, they defaulted to zero permissions. Both the backend and frontend RBAC engines lacked a built-in system bypass for the `TEMPLE_MANAGER` role, unlike `SUPERADMIN` which correctly bypassed the granular checks.

### Affected Services, Components, or Features
- Manager Dashboard (Sidebar)
- All operational modules (except Dashboard and Website Builder)
- All `TEMPLE_MANAGER` and `ADMIN` users

### Resolution Implemented
1. Updated `app/modules/auth/services/rbac_service.py` to allow `TEMPLE_MANAGER` and `ADMIN` to automatically receive `all:all` full access permissions in `get_my_permissions()`.
2. Updated `app/core/security/deps.py` (`require_permission`) to allow `TEMPLE_MANAGER` and `ADMIN` to bypass the granular database permission checks.
3. Updated `frontend/src/utils/rbac.ts` (`RBACEngine`) to provide an immediate local bypass for `TEMPLE_MANAGER` and `ADMIN` without needing explicit database mappings.

### Preventive Actions Taken
- Ensuring that tenant administrator roles (`TEMPLE_MANAGER`) have built-in operational override rights parallel to system-wide `SUPERADMIN` roles.
- This prevents access lockouts when rolling out new modules or transitioning to more restrictive granular RBAC architectures.

### Related Tickets, PRs, Commits
- Commit: `9f1f32b` (Full Stack)

---

## INC-005: Missing Live Website Settings Database Table on Production

| Field | Value |
|-------|-------|
| **Incident ID** | INC-005 |
| **Incident Title** | Missing `temple_website_settings_live` database table on production PostgreSQL database |
| **Date and Time** | 2026-06-07T07:05:00Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

The devotee public portal ("Explore Temples" list view) failed to load and displayed an "Unable to Load Temples" error message. The developer console/API server logs showed `UndefinedTableError: relation "temple_website_settings_live" does not exist` when requesting `/api/v1/public/temples`.

### Root Cause

The migration file `add_website_publication_snapshots.py` (which creates the `temple_website_settings_live` table) had not been executed on the production PostgreSQL database. The `/api/v1/public/temples` endpoint uses an inner join with `TempleWebsiteSettingsLive`, meaning it failed immediately when the database lacked the table relation.

### Affected Services, Components, or Features

- Devotee Portal Homepage ("Explore Temples" listing)
- Public-facing temple listings and landing pages
- `/api/v1/public/temples` API endpoint

### Resolution Implemented

Ran `alembic upgrade head` on the production PostgreSQL database, creating the `temple_website_settings_live` table and running the safe data migration to populate settings for existing active, approved temples.

### Preventive Actions Taken

- Ensure database migrations are executed as part of the CD/deployment pipeline before launching backend service updates.
- Verify migration checks during local and staging environments are systematically run against target databases.

### Related Tickets, PRs, Commits
- Migration: `add_website_publication_snapshots.py`

---

## INC-006: Pydantic ValidationError on Public Portal Image Mapping

| Field | Value |
|-------|-------|
| **Incident ID** | INC-006 |
| **Incident Title** | Pydantic ValidationError in public temple portal endpoint when mapping gallery images |
| **Date and Time** | 2026-06-07T07:58:00Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

When loading the public devotee portal for a temple that has gallery images (such as Malottu Sree Bhadrakali Temple), the page crashed and failed to load modules. The backend server threw a `pydantic_core._pydantic_core.ValidationError`: field required `temple_id` and `created_at` in `TempleImageResponse` validation.

### Root Cause

The `/api/v1/public/temples/{slug}/portal` endpoint maps the query results of `temple.images` to `TempleImageResponse` models. However, the route handler forgot to specify the `temple_id` and `created_at` fields during mapping:
```python
# File: backend/app/modules/temple_management/routes/public_portal.py (BEFORE fix)
images.append(
    TempleImageResponse(
        id=img.id,
        image_url=img.image_url,
        caption=img.caption or "",
        category=img.category or "GALLERY"
    )
)
```
Since these fields are required by the `TempleImageResponse` Pydantic model (unlike other temples that had no images and skipped the loop), it raised a validation error immediately.

### Affected Services, Components, or Features

- Public Devotee Portal landing pages
- `/api/v1/public/temples/{slug}/portal` API endpoint
- Image gallery sections

### Resolution Implemented

Updated `app/modules/temple_management/routes/public_portal.py` to correctly map and pass `temple_id=img.temple_id` and `created_at=img.created_at` when instantiating `TempleImageResponse` for each image:
```python
# File: backend/app/modules/temple_management/routes/public_portal.py (AFTER fix)
images.append(
    TempleImageResponse(
        id=img.id,
        temple_id=img.temple_id,
        image_url=img.image_url,
        caption=img.caption or "",
        category=img.category or "GALLERY",
        created_at=img.created_at
    )
)
```

### Preventive Actions Taken

- Ensure rich data structures are systematically validated through backend unit tests.
- Added automated endpoint test coverage in the test suite that simulates temples with complete mock datasets (profile, settings, announcements, activities, and gallery images).

### Related Tickets, PRs, Commits
- Commit: `5040c52`

---

## INC-007: Malottu Temple Operational State Suspended Blocking Dashboard

| Field | Value |
|-------|-------|
| **Incident ID** | INC-007 |
| **Incident Title** | Malottu temple suspended operational state blocks manager dashboard access |
| **Date and Time** | 2026-06-07T14:09:00Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

The temple manager dashboard and operational APIs returned `403 (Forbidden)` with the message `"This temple is under administrative suspension. Operations are blocked."`, preventing modules from loading.

### Root Cause

The temple `operational_state` was set to `SUSPENDED` in the database. When the manager attempted to access any endpoint, the `TenantPolicy` middleware validated the capability (e.g. `CAN_LOGIN`) against `STATE_CAPABILITIES` for the temple's current state. Since `SUSPENDED` mode blocks all non-superadmin actions, the middleware raised a 403 Forbidden exception.

### Affected Services, Components, or Features

- Manager Dashboard
- All operational backend APIs (RBAC, summary, inventory, staff, etc.)
- `TEMPLE_MANAGER` and `STAFF` users

### Resolution Implemented

Updated the database record for Malottu temple (`id = f96f45a1-d3a3-422f-9260-abfcd8df1aaa`) to set `operational_state = 'ACTIVE'` and `is_active = True`, restoring all operational capabilities.

### Preventive Actions Taken

- Documented policy verification procedures.
- Ensured active status is synced with the correct operational state during onboarding and activation procedures.

### Related Tickets, PRs, Commits
- Database Update: `UPDATE temples SET operational_state = 'ACTIVE' ...`

---

## INC-008: Missing `feature_visibility` Column on Production PostgreSQL Database

| Field | Value |
|-------|-------|
| **Incident ID** | INC-008 |
| **Incident Title** | Missing `feature_visibility` column on website settings table on production PostgreSQL database |
| **Date and Time** | 2026-06-10T05:14:36Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

Temple managers attempting to load or update timings/settings in the Website Builder module encountered an internal server database error (HTTP 500). The frontend console log showed `Failed to load portal configuration: DATABASE_ERROR`.

### Root Cause

The production Neon PostgreSQL database was missing the `feature_visibility` column on the `temple_website_settings` table. This column was introduced in a local hardening pass migration but had not been executed on the production instance, leading to `UndefinedColumnError: column "feature_visibility" of relation "temple_website_settings" does not exist` when accessing the website builder configuration.

### Affected Services, Components, or Features

- Website Builder module in the Manager Dashboard
- Portal settings retrieval and update API endpoints
- Dynamic feature toggling on the devotee preview pages

### Resolution Implemented

Executed a database schema patch directly altering the `temple_website_settings` table on the production Neon PostgreSQL database to append the missing `feature_visibility` column. Also updated the local SQLite database instances to ensure environments were aligned.

### Preventive Actions Taken

- Ensure schema alignment is fully validated against production environments.
- Re-run/verify Alembic head migrations on production database to apply any pending changes before running application code.

### Related Tickets, PRs, Commits

- Fix script: `scratch/fix_prod_columns.py` (archived)
- Migration reference: `hardening_pass_007_live_temple_experience`

---

## INC-009: Unused Variable `setGothram` Causes Frontend Build Failure

| Field | Value |
|-------|-------|
| **Incident ID** | INC-009 |
| **Incident Title** | Unused state hook setter variable `setGothram` causes frontend compilation build failure |
| **Date and Time** | 2026-06-10T05:56:05Z |
| **Severity/Priority** | P2 – High |
| **Current Status** | ✅ Resolved |

### Description

Vercel frontend deployment failed during the build phase (`npm run build`), which executes `tsc -b && vite build`. The compiler crashed with error: `src/components/checkout/OfferingsModal.tsx(28,19): error TS6133: 'setGothram' is declared but its value is never read.`

### Root Cause

The Gothram input field was removed from the offerings form layout as requested, but the state setter `setGothram` was left declared in `useState` on line 28. In strict build mode (`tsc -b`), the `noUnusedLocals` configuration is enabled by default, raising a compilation error when any local variable is declared but never read.

### Affected Services, Components, or Features

- Vercel frontend deployments / CI CD pipeline.
- Offerings Checkout Modal module.

### Resolution Implemented

Replaced the unused `useState` hook with a static constant declaration (`const gothram = '';`) since the value is now static and no longer mutated by any input fields.

### Preventive Actions Taken

- Always verify changes locally using strict build commands (`npm run build` or `tsc -b`) rather than basic compilation checks (`tsc --noEmit`).

### Related Tickets, PRs, Commits

- Commit: `61544cf` (frontend)
- Submodule Update Commit: `9288dff` (root)

---

## INC-010: Missing `PaymentStatus` Import in Devotee Portal Bookings Schemas

| Field | Value |
|-------|-------|
| **Incident ID** | INC-010 |
| **Incident Title** | Missing `PaymentStatus` import in `bookings/schemas/devotee_portal.py` |
| **Date and Time** | 2026-06-09T22:20:00Z |
| **Severity/Priority** | P2 – High |
| **Current Status** | ✅ Resolved |

### Description

During the devotee portal integration, the backend failed to register or execute bookings schemas properly. The schema module threw a `NameError: name 'PaymentStatus' is not defined` when attempting to load the Pydantic definition for `PaymentResponse`.

### Root Cause

The `PaymentResponse` schema in `app/modules/bookings/schemas/devotee_portal.py` references the `PaymentStatus` enum. Although the enum was defined in the billing models, it was not imported in the schema file, leading to a compilation/runtime NameError upon route router registration.

### Affected Services, Components, or Features

- Devotee Portal Bookings API endpoints.
- Devotee Checkout flow.
- Schema verification pipelines.

### Resolution Implemented

Imported `PaymentStatus` from `app.modules.billing.models.billing_models` inside the `devotee_portal.py` schema file.

### Preventive Actions Taken

1. Leverage strict static type checkers (`mypy` or `pyright`) on the codebase to identify unresolved dependencies and names.
2. Added mock endpoint tests to fully cover devotee public portal endpoints and dependencies.

### Related Tickets, PRs, Commits

- Commit: `01acbc6` (backend)

---

## INC-011: Website Builder Updates Blocked & Store/Hall Sections Missing

| Field | Value |
|-------|-------|
| **Incident ID** | INC-011 |
| **Incident Title** | Website Builder updates blocked on already published sites, and store/hall booking sections missing |
| **Date and Time** | 2026-06-10T11:41:00Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

Temple managers noticed that updates saved in the manager website builder (such as darshan timings and daily activities) were not reflecting on the devotee portal. Additionally, the Temple Store and Hall Booking buttons in the hero header did not scroll or navigate to any section on the devotee portal.

### Root Cause

1. **Blocked Republishing UI**: The manager dashboard website builder layout hid the "Publish Live" button when the site was already live, displaying only an "Unpublish" button. This prevented managers from pushing new draft changes to live without first completely taking the site down.
2. **Missing Layout Sections**: The `store` and `hall_booking` sections were missing from the default `section_order` list in both the database fallbacks and the devotee public portal code. As a result, even if the features were enabled, their sections were never rendered on the homepage, causing the hero CTA buttons (which scroll to `#store` and `#hall_booking`) to fail silently.

### Affected Services, Components, or Features

- Website Builder Module.
- Devotee Portal homepage layouts.
- Temple Store and Hall Booking integration.

### Resolution Implemented

1. Modified `WebsiteModuleLayout.tsx` to render the "Publish Changes" button alongside the "Unpublish" button when the site is already published, allowing updates to be published cleanly.
2. Modified `TemplePublicPortal.tsx` and `PortalWebsitePreview.tsx` to dynamically inject the `store` and `hall_booking` sections into `sectionOrder` if they are enabled in settings, ensuring their components are always rendered in the layout flow.
3. Modified `WebsiteSettings.tsx` to dynamically sync `store` and `hall_booking` in the draft `section_order` array when their toggles are updated.

### Preventive Actions Taken

1. Ensure features that require layout rendering dynamically register themselves or fall back gracefully, rather than relying on a static array in the database.
2. Allow continuous publishing of draft settings without blocking the publisher button based on live status.

### Related Tickets, PRs, Commits

- Commit: `dbe0020` (frontend)

---

## INC-012: Omitted Sprint Entity Tables causing Bootstrap & Follow Crashes

| Field | Value |
|-------|-------|
| **Incident ID** | INC-012 |
| **Incident Title** | Omission of sprint entities tables (advertisements, recommendations, preferences) on production database causing bootstrap and follow crashes |
| **Date and Time** | 2026-06-10T12:00:00Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

When devotees accessed the public temple portal landing page, the app failed to load layout sections, returning an HTTP 500 error on the `/api/v1/public/temples/{slug}/bootstrap` configuration endpoint. In addition, authenticated devotees trying to interact with the page (such as checking follow status) received an HTTP 500 error on `/api/v1/follow/check/{id}`.

Because the configuration failed to load, the devotee portal frontend fell back to its stale offline cache. Crucially, because the cache lacked the dynamically computed features (`enableStore`, `enableHallBooking`), the Temple Store and Hall Booking layout sections were not rendered on the page, rendering their hero buttons non-functional (clicking them did nothing).

### Root Cause

The production Neon PostgreSQL database was missing multiple tables introduced in early sprints, namely:
- `temple_advertisements`
- `platform_advertisements`
- `advertisement_analytics`
- `campaign_revenue_metrics`
- `portal_analytics_events`
- `service_recommendations`
- `temple_follower_preferences`
- `platform_global_settings`

Although the production database recorded its `alembic_version` as the latest head `48bd9fc73314`, these tables had either been dropped or omitted during past database restores/resets. Consequently, SQL queries attempting to access these models raised `UndefinedTableError` exceptions, causing the API router to crash and return 500 database errors.

### Affected Services, Components, or Features

- **Devotee Portal Homepage** (entire page layout configuration and announcements block).
- **Temple Store & Hall Booking sections** (completely missing from devotee portal layout).
- **Devotee Follow Service** (follow status check endpoint crashed).

### Resolution Implemented

1. Created and executed a schema recovery script `scratch/recreate_missing_tables.py` utilizing SQLAlchemy's metadata `create_all` engine to automatically inspect the target database and safely recreate all missing table definitions.
2. Verified the `/bootstrap` endpoint successfully responds with `200 OK` and returns correct configuration payloads containing layout sections and feature visibility toggles.
3. Confirmed that both the Temple Store and Hall Booking sections are now correctly injected and scrollable from their hero buttons.

### Preventive Actions Taken

1. Avoid manual database operations or resets that desynchronize the database schema from Alembic's tracking states.
2. Introduce a metadata checker script in the startup diagnostics to alert on any mismatches between defined models and physical database tables.

### Related Tickets, PRs, Commits

- Recovery script: `scratch/recreate_missing_tables.py`
- Alembic Head: `48bd9fc73314`

---

## INC-013: Non-Idempotent Migration Blocks Alembic Chain on Redeploys

| Field | Value |
|-------|-------|
| **Incident ID** | INC-013 |
| **Incident Title** | Non-idempotent migration blocks Alembic chain causing backend 500 on redeploys |
| **Date and Time** | 2026-06-11T23:50:00Z |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

After deploying Phase 6/6.5 backend updates, public devotee portal APIs (e.g. `/api/v1/public/states`) returned `HTTP 500 Internal Server Error (DATABASE_ERROR)`. The explorer view in the frontend failed to load, displaying the "Unable to Load Directory Internal database error" status.

### Root Cause

1. **Non-Idempotent Migration**: The migration `add_public_directory_indexes.py` (which sits just before Phase 1 in the migration chain) attempted to create composite indexes (`idx_temple_profiles_state_district`, etc.) using bare `op.create_index()` calls without checking for their existence. Because these indexes were already present in the production database (manually created during previous runs/sprints), Alembic crashed with a `DuplicateTable/DuplicateObject` error.
2. **Invalid Merge Topology**: The merge migration `phase6_directory_changes.py` had `down_revision = ('48bd9fc73314', '05757f236a11')` which bypassed `add_public_directory_indexes` and caused Alembic to see multiple unmerged heads. Correcting this `down_revision` to include `add_public_directory_indexes` solved the merge topology, but since `add_public_directory_indexes` is an ancestor of `05757f236a11` in the main chain, the merge itself was topologically redundant.
3. **Redeployment Failure Cascade**: When the Alembic upgrade command `alembic upgrade head` failed on container startup during Railway deployment, the new container crashed and failed its health checks. Railway kept the *old* container running, which served the old codebase. However, queries from the frontend triggered database queries that referenced newer columns (e.g., `directory_status`, `management_mode`, etc.) that were never created in the database, leading to `DATABASE_ERROR` exceptions.

### Affected Services, Components, or Features

- Devotee Portal Explorer (States, Districts directories)
- Public Portal APIs (`/api/v1/public/states`, `/api/v1/public/temples`)
- Backend Deployment pipeline (Railway containers rolled back to legacy code)

### Resolution Implemented

1. **Idempotent Migration Patch**: Rewrote `add_public_directory_indexes.py` to inspect existing indexes via `sa.inspect(bind)` and only create the indexes if they are not already present.
2. **Topology Correction**: Corrected `phase6_directory_changes.py` down_revision from `('48bd9fc73314', '05757f236a11')` to `('add_public_directory_indexes', '05757f236a11')` to correctly reference the branch tip.
3. **Manual Migration Run**: Executed `alembic upgrade head` manually against the production Neon PostgreSQL database using local terminal context. This successfully applied all migrations up to `phase6_directory_changes`, creating the state master tables, district master tables, search index tables, and adding missing columns to the `temples` table.
4. **Successful Validation**: Hitting the production API endpoints now returns a list of states and temples with zero errors.

### Preventive Actions Taken

1. **Migration Audits**: Enforce that *all* migrations must be fully idempotent, checking for table, column, index, and constraint existence before modification.
2. **Health Check Isolation**: Ensure backend health checks distinguish database migration states from container liveness.

### Related Tickets, PRs, Commits

- Commit: `c4894fd` (backend migration fixes)
- Manual database update executed successfully on 2026-06-11

---

## INC-014: Empty Explorer Directory Due to NULL State/District Foreign Keys

| Field | Value |
|-------|-------|
| **Incident ID** | INC-014 |
| **Incident Title** | Empty explorer directory due to NULL state_id and district_id on existing temples |
| **Date and Time** | 2026-06-12T09:40:00Z |
| **Severity/Priority** | P2 – High |
| **Current Status** | ✅ Resolved |

### Description

Devotees accessing the public directory ("Explore Temples" state/district listing) saw zero active states or counties with temple counts > 0, and no temples listed in the explore directory despite active, approved temples existing in the database.

### Root Cause

The Phase 6 database migration introduced canonical tables (`state_master` and `district_master`) and foreign key columns (`state_id` and `district_id`) on the `temples` table. However, because the migration did not include a data migration step to map existing temples' text-based `state` and `district` columns to these new foreign key columns, they defaulted to `NULL` for all existing temples.
As a result, the outer joins on the public portal endpoints (which group and count temples by `state_id` and `district_id`) returned a `temple_count` of `0` for all states and districts, showing no temples in the directory.

### Affected Services, Components, or Features

- Explore Directory Page (Devotee Portal)
- `/api/v1/public/states`, `/api/v1/public/states/{state}/districts` API endpoints

### Resolution Implemented

1. **Sync Script Execution**: Developed and ran `scratch/sync_temples_directory_ids.py` to:
   - Load existing state and district lookup tables.
   - Read text-based `state` and `district` fields from the `temples` and `temple_profiles` tables for each temple.
   - Resolve and map these to canonical `StateMaster.id` and `DistrictMaster.id` values (including normalization of `"Trivandrum"` to `"Thiruvananthapuram"`).
   - Update `state_id` and `district_id` for all 12 temples in the Neon production database.
2. **Endpoint Validation**: Confirmed `/api/v1/public/states` now returns `Kerala` with `temple_count = 7`, and the explorer directory functions perfectly.

### Preventive Actions Taken

1. **Data Migration in Schema Updates**: Ensure future schema migrations adding foreign key relations or structural mappings include SQL queries to backfill or map existing records from legacy/flat columns.

### Related Tickets, PRs, Commits

- Data migration script: `scratch/sync_temples_directory_ids.py`
- Database synchronization executed successfully on 2026-06-12



---

## INC-015: Couldn't View/Download 'Legal Verification Documents (Uploaded Proof)' in Claims Review

| Field | Value |
|-------|-------|
| **Incident ID** | INC-015 |
| **Incident Title** | Couldn't view/download 'Legal Verification Documents (Uploaded Proof)' in Claims Review |
| **Date and Time** | 2026-06-12T11:26:00Z |
| **Severity/Priority** | P2 – High |
| **Current Status** | ✅ Resolved |

### Description

Superadmins reviewing temple claims in the Claims Governance dashboard were unable to view or download uploaded legal verification documents. Clicking the "View/Download" link either failed to load or opened the wrong hostname, pointing back to development or incorrect ports.

### Root Cause

1. **Hardcoded Origin Prepending**: The devotee portal file uploader in `ClaimTempleModal.tsx` prefixed relative backend upload paths (like `/static/uploads/{filename}`) with the frontend host's `window.location.origin` (evaluating to `http://localhost:5173` in development or the Vercel domain in production) before saving to the database.
2. **Missing Base URL Resolver**: The Claims Governance review screen (`ClaimsGovernance.tsx`) rendered `proof_urls` directly via `<a href={url}>` without wrapping them in the frontend's `getMediaUrl()` utility. This caused absolute links with the wrong port/origin to fail during cross-environment review.
3. **HTML5 URL Validation**: The text input field in `ClaimTempleModal.tsx` was typed as `type="url"`, throwing native browser validation errors when saving purely relative paths like `/static/uploads/{filename}`.

### Affected Services, Components, or Features

- Superadmin Claims Governance review page (`ClaimsGovernance.tsx`)
- Devotee Claim Temple Modal (`ClaimTempleModal.tsx`)
- Media URL resolver (`mediaUrl.ts`)

### Resolution Implemented

1. **Self-Healing URL Resolver**: Enhanced the global `getMediaUrl()` utility in `mediaUrl.ts` to detect paths containing `/static/uploads/`, extract the relative segment, and resolve it properly to the backend server domain or Vercel proxy rewrite target. This dynamically fixes all legacy records stored with wrong hostnames.
2. **Dashboard Integration**: Modified `ClaimsGovernance.tsx` to wrap proof links in `getMediaUrl(url)`.
3. **Form Upload Improvements**: Modified `ClaimTempleModal.tsx` to save the relative path from the backend file uploader directly (no frontend origin prefixing) and converted the input field to `type="text"` to bypass native browser URL validation blocks.

### Preventive Actions Taken

1. **Consistent URL Resolver**: Always use the `getMediaUrl()` utility for displaying or linking to assets and documents uploaded to the backend server.
2. **Relative Path Storage**: Store only relative paths (e.g. `/static/uploads/filename.ext`) in the database instead of absolute URLs containing environment-specific hostnames or ports.

### Related Tickets, PRs, Commits

- Commit: `279fcfc` (frontend fixes)

---

## INC-016: Suggest Temple Step 2 Next Disabled Due to Failed Backend Migration Deployment

| Field | Value |
|-------|-------|
| **Incident ID** | INC-016 |
| **Incident Title** | Suggest Temple Step 2 Next disabled due to failed backend migration deployment |
| **Date and Time** | 2026-06-12T23:26:00+05:30 |
| **Severity/Priority** | P2 – High |
| **Current Status** | ✅ Resolved |

### Description

In the devotee portal Suggest Temple flow (Step 2/5), the "Next: Duplicates & Map" button remained disabled even after all required fields were filled. Checking browser console logs revealed `401 Unauthorized` errors when fetching `/api/v1/auth/me`. Additionally, the state selection field did not successfully validate state IDs, causing the form's validity check to fail and blocking the user from proceeding.

### Root Cause

1. **Alembic Migration UUID Typing Mismatch**: The backend migration `phase6_directory_changes.py` performed a `bulk_insert` of state and district records using hardcoded UUID strings. Because SQLite and Neon PostgreSQL drivers expect Python `uuid.UUID` objects for columns defined as `sa.UUID()`, SQLAlchemy raised a `StatementError: (builtins.AttributeError) 'str' object has no attribute 'hex'` during container startup.
2. **FastAPI Module Import NameError**: The new suggestions service layer (`suggestions_service.py`) introduced type annotations using `Optional[UUID]` but omitted importing `Optional` from the `typing` module. This triggered a `NameError: name 'Optional' is not defined` at application import time.
3. **Railway Silent Rollback / Deploy Stall**: Both errors caused container startup to fail on new deployments on Railway. As a result, Railway kept routing traffic to the older container instance running an outdated build.
4. **Outdated API Payload**: The old container served a legacy version of the `/api/v1/public/states` endpoint which did not return the state `id` key. The frontend Suggest Temple form could not map the selected state to an ID, leaving the form invalid and the "Next" button disabled.

### Affected Services, Components, or Features

- Devotee Portal Suggest Temple Flow (Step 2 validation)
- `/api/v1/public/states` endpoint
- Backend Deployment pipeline on Railway (master branch)

### Resolution Implemented

1. **Migration UUID Conversion**: Patched `phase6_directory_changes.py` to import `uuid` and map string IDs to Python `uuid.UUID` instances before calling `op.bulk_insert`.
2. **Suggestions Service Import Correction**: Added `from typing import Optional` to `app/modules/governance/services/suggestions_service.py`.
3. **Local Validation**: Verified that `alembic upgrade head` runs and completes successfully against SQLite, and that the backend app imports cleanly without NameErrors.
4. **Submodule Deployment Sync**: Committed the fixes to backend `main`, merged into `master`, and pushed to remote origin. The backend submodule commit in the root repository was also updated and pushed to trigger a clean deployment.
5. **API Verification**: Checked that `/api/v1/public/states` now returns state `id` keys and that `/health/live` correctly reports the new commit.

### Preventive Actions Taken

1. **Strict Type Conversion in Migrations**: Ensure all bulk-inserted data records containing UUID fields are explicitly parsed using Python `uuid.UUID()` objects in Alembic scripts to avoid driver-specific SQL execution errors.
2. **Pre-commit Import Checks**: Ensure that static checks or a quick import check (`python -c "from app.real_main import app"`) is executed as part of local verification or CI to catch NameErrors before pushing code.
3. **Deployment Alerting**: Check build and startup logs on Railway whenever backend submodule updates are pushed.

### Related Tickets, PRs, Commits

- Commit (backend): `cfdb84a` (migration UUID fix), `fd0b59a` (suggestions service Optional import fix)
- Commit (root): `323c043` (submodule reference update)

---

## INC-017: Devotee Suggest Temple Submission Failure Due to DB Enum Mismatch and Base64 image_url Length Limit

| Field | Value |
|-------|-------|
| **Incident ID** | INC-017 |
| **Incident Title** | Devotee Suggest Temple Submission failure due to DB Enum mismatch and Base64 image_url length limit |
| **Date and Time** | 2026-06-13T10:09:45+05:30 |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

When devotees completed Step 5 of 5 of the Suggest Temple flow and clicked submit, the API returned an HTTP 500 Internal Server Error (`DATABASE_ERROR`) with the message `Internal database error`. Devotees encountered two distinct failure modes on submission:
1. First failure mode (traceId: `42c93ef1-608`): Blocked submissions due to a type mapping error on the status column.
2. Second failure mode (traceId: `9348a2f4-b74`): Blocked submissions containing images due to a length overflow on the image URL column.

Additionally, during form validation and submission, the developer console logged devotee details in plain text, raising privacy concerns.

### Root Cause

1. **SQLAlchemy vs Alembic Schema Mismatch (Status Enum)**: The `status` column in `TempleSuggestion` was defined as `Column(Enum(TempleSuggestionStatus))` (which by default maps to a native PostgreSQL ENUM type named `templesuggestionstatus`). However, the Alembic migration `253cb6f74d6c_add_temple_suggestions_staging_tables.py` had defined the `status` column as `sa.String(30)`.
2. **UndefinedObjectError (Status Enum)**: When SQLAlchemy executed the INSERT statement, it generated SQL that cast the status parameter to `$24::templesuggestionstatus`. Since the native type did not exist, Postgres threw `asyncpg.exceptions.UndefinedObjectError: type "templesuggestionstatus" does not exist`.
3. **Image URL Column Size Limit**: The `image_url` column in `temple_suggestion_images` table was defined as `VARCHAR(512)` in the Alembic migration and `String(512)` in `governance_models.py`. However, the backend image upload endpoint compresses and returns images as base64 data URIs (which are thousands of characters long). Inserting these base64 strings caused Postgres to raise `asyncpg.exceptions.StringDataRightTruncationError: value too long for type character varying(512)`.
4. **Verbose Client-Side Logging**: A debug `console.log` statement was left in `SuggestTempleModal.tsx` from development, which outputted the entire form state dynamically.

### Affected Services, Components, or Features

- Devotee Portal Suggest Temple Flow (Submission API)
- `/api/v1/temple-suggestions` POST API
- Devotee Portal UI components (`SuggestTempleModal.tsx`)

### Resolution Implemented

1. **Configure Non-Native Enum Mapping**: Modified the `status` column definition on the `TempleSuggestion` model in `governance_models.py` to use `native_enum=False`. This tells SQLAlchemy to map the enum values to a standard string/varchar column (matching the database schema) instead of trying to cast it to a native PostgreSQL enum type.
2. **Altered Column Type in Production**: Altered the `temple_suggestion_images.image_url` column type in the production database to `TEXT` (unlimited length).
3. **Modified Model Column Type**: Changed `image_url` in the `TempleSuggestionImage` model in `governance_models.py` to `Column(String)` without length limits, letting it map to `TEXT` in production.
4. **Remove Client-Side Debug Logs**: Removed the debug `console.log` from `SuggestTempleModal.tsx` to prevent exposing user-entered fields in the browser console.
5. **Rerun Verification**: Verified that simulated devotee suggestions are successfully created in the production database and cleaned up the test record afterwards.

### Preventive Actions Taken

1. **Strict Enum Mapping Policy**: Enforce `native_enum=False` on model Enum columns where the underlying database table uses a standard `String` or `VARCHAR` type.
2. **Handle Base64 URL Lengths**: Ensure all database columns storing file/image references use `TEXT` or length-free `String` types if the application supports inline base64 data URIs.
3. **Code Reviews for Console Logging**: Review console logging rules to ensure debug/validation logs are not pushed to production build targets.

### Related Tickets, PRs, Commits

- Commit (backend): `b06df9d` (Configure status native_enum=False), `8dcd5eb` (Alter image_url to String and document in kb)
- Commit (frontend): `1ed27a2` (Remove debug console.log)

---

## INC-018: Superadmin Review Action Submission Failure due to Status String Mismatch

| Field | Value |
|-------|-------|
| **Incident ID** | INC-018 |
| **Incident Title** | Superadmin Review Action Submission Failure due to Status String Mismatch |
| **Date and Time** | 2026-06-13T11:15:30+05:30 |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

When superadmins attempted to approve, reject, or merge devotee suggestions in the Governance Triage dashboard, the API returned an HTTP 400 Bad Request error (`BAD_REQUEST`) with the message `Invalid review status action` (traceId: `d1af126e-274`). This blocked moderators from processing incoming devotee suggestions.

### Root Cause

The frontend `SuggestionsGovernance.tsx` component was building the review payload by sending the active/verb forms of the action (`status: "APPROVE"`, `"REJECT"`, or `"MERGE"`). However, the backend suggestions service `review_suggestion` was strictly expecting the past-participle states of the status enum (`"APPROVED"`, `"REJECTED"`, or `"MERGED"`). Since they didn't match, the backend raised an HTTP 400 exception.

### Affected Services, Components, or Features

- Superadmin Suggestions Governance Triage Dashboard (`SuggestionsGovernance.tsx` frontend page)
- `/api/v1/temple-suggestions/admin/{id}/review` POST API
- Backend Suggestions Service (`suggestions_service.py`)

### Resolution Implemented

1. **Backend Status Normalization**: Modified the backend [suggestions_service.py](file:///c:/Denumrutham/backend/app/modules/governance/services/suggestions_service.py#L403-L410) to map incoming review status values (accepting both verb forms like `"APPROVE"` and past-participle states like `"APPROVED"`) into their canonical past-participle representations.
2. **Frontend Payload Update**: Updated the frontend [SuggestionsGovernance.tsx](file:///c:/Denumrutham/frontend/src/pages/admin/governance/SuggestionsGovernance.tsx#L251-L253) to send `"APPROVED"`, `"REJECTED"`, or `"MERGED"`, aligning with the documented API contract.
3. **Verification**: Successfully submitted suggestion creations as a devotee and approved/processed them using both status formats, confirming HTTP 200 responses.

### Preventive Actions Taken

1. **Align API Contracts**: Ensure frontend and backend contracts are synchronized during feature implementation.
2. **Robust Input Normalization**: Implement input-tolerant enum mapping or casing standardization in the service layer.

### Related Tickets, PRs, Commits

- Commit (backend): `16b9060` (Normalize review status to accept both short verb and past participle)
- Commit (frontend): `a8d0ec5` (Send past-participle review status to match API contract)

---

## INC-019: HTTP 500 Internal Server Errors due to Database Connection Pool Exhaustion in Current User Authentication Dependency

| Field | Value |
|-------|-------|
| **Incident ID** | INC-019 |
| **Incident Title** | HTTP 500 Internal Server Errors due to Database Connection Pool Exhaustion in Current User Authentication Dependency |
| **Date and Time** | 2026-06-15T12:45:00+05:30 |
| **Severity/Priority** | P1 – Critical |
| **Current Status** | ✅ Resolved |

### Description

All database-dependent endpoints (such as `/api/v1/auth/me`, `/api/v1/manager/website-settings/...`, `/api/v1/auth/login/redirect`) began failing with HTTP 500 Internal Server Errors under load or after several consecutive requests.

### Root Cause

The authentication dependency function `get_current_user` (duplicated across `app/core/database/deps.py`, `app/core/security/deps.py`, and `app/core/tenancy/deps.py`) was retrieving a database session using `db_gen = get_db()` and `db = await anext(db_gen)`.
Because `get_db()` is an asynchronous generator wrapping a session context manager, calling `anext` suspends the generator at the `yield` statement without exiting the context manager. Since `get_current_user` did not resume or close the generator, the database connection remained checked out from the pool indefinitely. Every authenticated API request leaked a connection, eventually exhausting the pool and causing all subsequent database operations to timeout and return HTTP 500.

### Affected Services, Components, or Features

- FastAPI Backend dependency injections (`get_current_user`)
- Database Connection Pool (Neon Postgres / local Postgres)
- All authenticated REST API endpoints

### Resolution Implemented

1. **Replaced Session Retrieval**: Modified `get_current_user` in `database/deps.py`, `security/deps.py`, and `tenancy/deps.py` to directly instantiate the database session:
   ```python
   from app.core.database import AsyncSessionLocal
   db = AsyncSessionLocal()
   ```
2. **Ensured Proper Cleanup**: Leveraged the existing `try...finally` block to call `await db.close()`, guaranteeing the session is closed and the connection is returned to the pool immediately upon completion of the authentication checks.
3. **Validation**: Verified successful syntax compilation (`python -m py_compile`).

### Related Tickets, PRs, Commits

- Commit (backend): `8c992ae` (resolve database connection pool leak in get_current_user)

---

## Incident Management Process

### When a New Incident Is Reported

1. **Search this Knowledge Base** for similar or related incidents before creating a new entry.
2. If a matching or related incident exists:
   - Update the existing entry with new information.
   - Link the related incidents.
3. If no match exists:
   - Create a new incident entry using the template below.
   - Assign the next sequential ID (`INC-XXX`).
   - Add it to the Incident Index table at the top.

### Incident Template

```markdown
## INC-XXX: [Title]

| Field | Value |
|-------|-------|
| **Incident ID** | INC-XXX |
| **Incident Title** | [Brief description] |
| **Date and Time** | YYYY-MM-DDTHH:MM:SSZ |
| **Severity/Priority** | P1/P2/P3/P4 |
| **Current Status** | 🔴 Open / 🟡 In Progress / ✅ Resolved / ⬛ Closed |

### Description
[Detailed description of what happened]

### Root Cause
[Technical root cause analysis]

### Affected Services, Components, or Features
[List affected areas]

### Resolution Implemented
[What was done to fix it]

### Preventive Actions Taken
[What was done to prevent recurrence]

### Lessons Learned
[Key takeaways]

### Related Tickets, PRs, Commits
[Links to related items]
```

### Severity Definitions

| Level | Definition |
|-------|-----------|
| **P1 – Critical** | Complete service outage or data loss. All users affected. Requires immediate action. |
| **P2 – High** | Major feature broken. Many users affected. Requires action within hours. |
| **P3 – Medium** | Minor feature degraded. Some users affected. Can be scheduled for next sprint. |
| **P4 – Low** | Cosmetic or minor issue. Few users affected. Can be addressed at convenience. |

---

## Recurring Patterns & Systemic Issues

### Pattern: Single Import Failure Cascades to Full Outage

**Occurrences**: INC-001, INC-003

**Root Issue**: The API router registration in `api.py` uses a single `from ... import` statement. If ANY imported route module has a Python error, ALL routes fail to register.

**Recommended Fix**: Wrap each router import in a try/except block with logging, so a failure in one module only disables that module's endpoints, not the entire API.

### Pattern: Backend Failures Manifest as Frontend Loading States

**Occurrences**: INC-002, INC-003

**Root Issue**: The frontend has no timeout or error state for critical API calls like permission loading. When the backend is down, the UI shows infinite loading instead of an actionable error message.

**Recommended Fix**: Add timeout handling and error states to all critical frontend API calls (permissions, auth, config).

---

## FEAT-001: Phase 1 – Sidebar Spotlight Ad Area & Layout Alignment

| Field | Value |
|-------|-------|
| **Feature ID** | FEAT-001 |
| **Type** | Feature Delivery – Phase 1 |
| **Status** | ✅ Shipped |
| **Date** | 2026-06-10 |
| **Commit (frontend)** | `84e69b5` |
| **Commit (backend)** | `a7bb114` |

### Problem

The devotee public portal had two issues:
1. **Layout misalignment**: `PortalActivitiesPreview` and `PortalGalleryPreview` lacked `max-w-6xl mx-auto` constraints, causing their left edges to float relative to sections that did have the constraint.
2. **No right-rail space**: There was no mechanism to place sponsored advertisements beside content sections.

### Solution

**Phase 1 delivers three things:**

#### 1. Shared Layout Token (`SECTION_WRAP`)

```ts
const SECTION_WRAP = 'max-w-6xl mx-auto w-full px-8';
```

Applied to all inline sections in `TemplePublicPortal.tsx` and corrected in `PortalActivitiesPreview.tsx` and `PortalGalleryPreview.tsx`. This ensures all portal sections have a consistent left margin.

#### 2. Two-Column Layout Architecture

New component `TwoColumnContentLayout` wraps the "About the Temple" and "Upcoming Activities & Rituals" sections in a flex layout:
- **Left column** (`flex-1`): existing content sections
- **Right column** (`w-[300px]`, `lg:sticky`): sidebar widget

The set of sections that get the sidebar is controlled by the `SIDEBAR_SECTIONS` config array — not by hardcoded string checks. Adding a new section to the sidebar requires only a single array change.

Responsive behaviour:
- `≥ 1024px (lg)`: side-by-side, sidebar is sticky
- `< 1024px`: content stacks vertically, sidebar appears below Activities

#### 3. SidebarWidgetResolver

New future-proof right-rail component. Currently renders `SIDEBAR_SPOTLIGHT` placement ads in IMAGE and CAROUSEL formats. Architected to accept additional widget types (Announcements, Notices, Countdowns) in future sprints.

**Analytics Integration** (Sprint 3 reuse):
- `AD_IMPRESSION`: tracked via `IntersectionObserver` when widget enters 50% viewport
- `AD_CLICK`: tracked on target URL click

### Files Changed

| File | Change |
|------|--------|
| `src/components/layout/TwoColumnContentLayout.tsx` | **NEW** — Flex layout wrapper |
| `src/components/ads/SidebarWidgetResolver.tsx` | **NEW** — Sidebar right-rail widget |
| `src/pages/devotee/TemplePublicPortal.tsx` | SECTION_WRAP applied, TwoColumnContentLayout + SidebarWidgetResolver integrated |
| `src/pages/manager/website/preview/PortalActivitiesPreview.tsx` | Added `max-w-6xl mx-auto w-full px-8` |
| `src/pages/manager/website/preview/PortalGalleryPreview.tsx` | Added `max-w-6xl mx-auto w-full px-8` |
| `src/pages/manager/TempleAdsDashboard.tsx` | Added `SIDEBAR_SPOTLIGHT` placement; removed phantom options |
| `src/pages/manager/website/WebsiteSettings.tsx` | Added `enableSidebarSpotlight` toggle |
| `backend/app/modules/temple_management/models/temple_models.py` | Updated placement registry comment |

### New Feature Flag

| Flag | Default | Description |
|------|---------|-------------|
| `featureVisibility.enableSidebarSpotlight` | `true` (opt-out) | Temple managers can disable the sidebar from Website Builder |

### Ad Placement Registry (Canonical)

| Placement Value | Location |
|----------------|----------|
| `TEMPLE_DETAILS_AFTER_ABOUT` | Banner between About and Activities |
| `TEMPLE_DETAILS_BEFORE_GALLERY` | Banner immediately before Gallery |
| `TEMPLE_DETAILS_INLINE` | Header leaderboard / top-of-page |
| `SIDEBAR_SPOTLIGHT` | Right-rail sidebar beside About + Activities |

### Deferred to Phase 2

The following ad formats were intentionally deferred to a separate sprint:
- `VIDEO` — requires video hosting strategy and bandwidth decisions
- `VIDEO_CAROUSEL` — requires mixed media rendering + storage
- `COLLECTION` — requires per-item URL support and CTA design

Phase 1 supports: `IMAGE` and `CAROUSEL` only.

---

## FEAT-002: Phase 2 — Layout Responsiveness & Spotlight Ad Rails

| Field | Value |
|-------|-------|
| **Feature ID** | FEAT-002 |
| **Feature Title** | Phase 2 — Layout Responsiveness & Spotlight Ad Rails |
| **Date and Time** | 2026-06-10T16:00:00Z |
| **Status** | ✅ Shipped |

### Description

Implemented global layout standardisation, responsive explorer grids, desktop ad spotlight rails, and website builder controls to optimize large viewport styling and introduce ad monetization options.

### Changes Completed

1. **Global Layout Standardization**: Defined `PAGE_CONTAINER` in `src/constants/layout.ts` and locked all public headers, pages, and components to a maximum width of `1600px` with fluid responsive horizontal padding (`px-4 sm:px-6 lg:px-8`).
2. **Header Alignment**: Applied `PAGE_CONTAINER` to `MainLayout.tsx` and `DenumruthamShell.tsx` inner topbars, resolving elements floating to the absolute edges on wide displays.
3. **Explore Temples Page Responsive Grid**: Replaced rigid 3-column layouts with `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4` and set min height to `320px` for temple cards, preventing squeezed presentation.
4. **Spotlight Ad Rails**:
   - Left Spotlight Rail (Platform advertisements only).
   - Right Spotlight Rail (Temple advertisements only).
   - Responsive visibility: visible side-by-side on desktop (xl+), stacked below grid on tablet, hidden completely on mobile.
5. **Website Builder Controls**: Added `showLeftSpotlight`, `showRightSpotlight`, and `showSidebarRail` toggles to website settings and builder preview engines.

---

## FEAT-003: Devotee Registration Hardening & Password Strength Enforcements

| Field | Value |
|-------|-------|
| **Feature ID** | FEAT-003 |
| **Feature Title** | Devotee Registration Hardening & Password Strength Enforcements |
| **Date and Time** | 2026-06-12T11:10:00Z |
| **Status** | ✅ Shipped |

### Description

Enforced strong password policy verification checks during devotee and staff registrations across the Denumrutham ecosystem while maintaining a simple user interface by excluding a "confirm password" field from devotee and staff sign-ups.

### Changes Completed

1. **Frontend Validation**:
   - Integrated `PASSWORD_REGEX` validation check in `Register.tsx` to ensure passwords are at least 8 characters long and contain at least 1 uppercase letter, 1 lowercase letter, 1 digit, and 1 special character.
2. **Backend Validation**:
   - Updated the `UnifiedRegister` schema in `app/modules/auth/schemas/auth.py` to enforce the strong password validator.
   - Updated the `TempleManagerRegister` schema in `app/modules/auth/schemas/auth.py` to enforce the strong password validator.
   - Updated the legacy `DevoteeRegister` schema in `app/modules/bookings/schemas/devotee_portal.py` to check for strong password compliance.
   - Updated the onboarding (`TempleOnboardingRequest` in `onboarding.py`) and leads conversion (`LeadConvertRequest` in `leads.py`) schemas to validate manager password strength.
3. **Unit Tests**:
   - Added automated tests to `tests/test_auth.py` to verify devotee unified registration and legacy devotee registration validation under weak and strong passwords.

---

## FEAT-004: Temple Timing Management UX Enhancements

| Field | Value |
|-------|-------|
| **Feature ID** | FEAT-004 |
| **Feature Title** | Temple Timing Management UX Enhancements |
| **Date and Time** | 2026-06-15T12:30:00+05:30 |
| **Status** | ✅ Shipped |

### Description

Enhanced the Temple Timing Management panel (`TimingsSettings.tsx`) inside the manager's Website Builder, improving chronological sorting, adding a visual gaps alert panel, and replacing manual text time inputs with custom dropdown clock selectors.

### Changes Completed

1. **Chronological Sorting**: Sorted the session cards by opening time using `sortedTimings` while maintaining `originalIndex` references for edit/delete functions.
2. **Timing Gaps Warning Panel**: Added an warning panel immediately above the timing card grid that identifies gaps between consecutive operating windows and displays them formatted (e.g. "30 mins gap").
3. **Dropdown Clock Selectors**: Implemented dropdown-based hour (`01`-`12`), minute (`00`-`59`), and period (`AM`/`PM`) selectors. Enhanced `parseTimeParts` with a 24-hour military time fallback parser to handle legacy data formats safely.
4. **Tab State Retention**: Introduced an `initialized` state variable in `WebsiteModuleLayout.tsx` to prevent `fetchPortalState` from re-fetching settings on sub-tab navigation click, retaining unsaved changes across website builder tabs.
5. **Validation**: Ran full compilation build (`npm run build`) successfully with no TypeScript compiler errors.

### Related Tickets, PRs, Commits

- Commit (frontend): `f640d35` (enhance temple timing management with sorted cards, timing gaps, and clock dropdown selectors)
- Commit (frontend): `913ddcd` (fix(website): retain unsaved changes state across tab navigation in WebsiteModuleLayout)

