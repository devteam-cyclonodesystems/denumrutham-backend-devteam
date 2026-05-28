from fastapi import APIRouter, Depends, Request
from typing import List, Dict, Any
from app.services.sync_service import SyncService
from app.api.deps import get_current_user

router = APIRouter()

@router.post("")
async def sync_offline_actions(
    request: Request,
    actions: List[Dict[str, Any]],
    current_user: Any = Depends(get_current_user)
):
    """
    Process a batch of offline actions stored by the client.
    """
    results = await SyncService.process(actions)
    return {"status": "success", "data": results}
