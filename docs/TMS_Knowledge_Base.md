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
