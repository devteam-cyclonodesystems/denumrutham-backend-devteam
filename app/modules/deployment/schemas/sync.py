"""
Sync Schemas — Request/Response contracts for hybrid offline sync.

Phase 4: Defines the data shapes for:
  - Pull (server → client): get all changes since a timestamp
  - Push (client → server): batch-submit offline changes
  - Conflict reporting: version mismatch details
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ── Pull (Server → Client) ───────────────────────────────────────────

class SyncPullItem(BaseModel):
    """A single temple record in the sync pull response."""
    id: str
    name: str
    domain: str
    status: str
    is_active: bool
    version: int
    updated_at: Optional[str] = None
    location: Optional[str] = ""
    state: Optional[str] = ""
    district: Optional[str] = ""
    contact_number: Optional[str] = ""
    email: Optional[str] = ""
    description: Optional[str] = ""
    image_url: Optional[str] = ""


class SyncPullResponse(BaseModel):
    """Server response for pull sync."""
    temples: List[SyncPullItem]
    count: int
    since: str
    server_time: str  # Current server time — client uses as next 'since'
    has_more: bool


# ── Push (Client → Server) ───────────────────────────────────────────

class SyncPushItem(BaseModel):
    """A single temple update from the client."""
    id: str
    version: int  # Client's version — must match server for update to apply
    changes: Dict[str, Any]  # field → new value (only safe fields allowed)
    local_change_id: Optional[str] = None  # Client-side tracking ID


class SyncPushRequest(BaseModel):
    """Client pushes batch updates."""
    updates: List[SyncPushItem] = Field(..., max_length=50)


class SyncPushResultItem(BaseModel):
    """Result for a single sync push item."""
    id: str
    status: str  # "applied" | "conflict" | "error"
    message: Optional[str] = None
    server_version: Optional[int] = None
    server_data: Optional[Dict[str, Any]] = None
    client_data: Optional[Dict[str, Any]] = None
    local_change_id: Optional[str] = None


class SyncPushResponse(BaseModel):
    """Server response for push sync."""
    results: List[SyncPushResultItem]
    applied: int
    conflicts: int
    errors: int
    server_time: str
