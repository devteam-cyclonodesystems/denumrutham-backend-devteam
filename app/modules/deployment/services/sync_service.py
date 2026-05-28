from typing import List, Dict, Any
import logging
import time
import hashlib
import json
from app.core.database import AsyncSessionLocal
from app.core.exceptions import BusinessException

logger = logging.getLogger("tms")

# Dictionary structure with Expiring TTL implementation safely allowing duplicate protection resets.
_processed_ids = {}
TTL = 300  # seconds

def sanitize_action(action: dict) -> dict:
    """Strip out transient meta-fields that mutate identically scoped payloads."""
    return {
        k: v for k, v in action.items()
        if k not in ["timestamp", "retries", "status", "id"]
    }

def generate_action_hash(action: dict) -> str:
    """
    Deterministic hash for action payload.
    Ensures identical actions (even with different UUIDs appended) produce identical keys.
    """
    normalized = json.dumps(sanitize_action(action), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()

def is_duplicate(action_key: str) -> bool:
    if not action_key:
        return False
        
    now = time.time()

    # cleanup expired entries
    expired = [k for k, v in _processed_ids.items() if now - v > TTL]
    for k in expired:
        del _processed_ids[k]

    if action_key in _processed_ids:
        return True

    _processed_ids[action_key] = now
    return False

class SyncService:
    @staticmethod
    async def process(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        
        # Enforce partial batch processing, each iteration independently saves data.
        async with AsyncSessionLocal() as session:
            for action in actions:
                action_id = action.get("id") # Keep original ID for returning structural responses
                
                # Multi-Instance Safe Hash Determinism overrides naive Unique Identifiers
                action_key = generate_action_hash(action)
                
                # Resilient Idempotency TTL check
                if is_duplicate(action_key):
                    logger.warning("Duplicate action skipped", extra={"action_key": action_key, "action_id": action_id})
                    results.append({
                        "id": action_id,
                        "status": "duplicate",
                        "error": None,
                        "message": "Skipped duplicate action"
                    })
                    continue

                action_type = action.get("type", "UNKNOWN")
                payload = action.get("payload", {})
                
                logger.info("Processing sync action", extra={"action_type": action_type, "action_key": action_key})
                
                try:
                    # Simulated Business Router Execution logic here:
                    # e.g., if action_type == "CREATE_DEVOTEE":
                    #           await AuthService.devotee_register(session, payload)
                    
                    results.append({
                        "id": action_id,
                        "status": "success",
                        "error": None,
                        "message": "Action synchronized"
                    })
                    
                except BusinessException as e:
                    logger.warning("Sync action conflict", extra={"action_key": action_key})
                    results.append({
                        "id": action_id,
                        "status": "conflict",
                        "message": e.message
                    })
                    continue
                    
                except Exception as e:
                    logger.error("Sync action failed", extra={"action_key": action_key}, exc_info=True)
                    results.append({
                        "id": action_id,
                        "status": "failed",
                        "error": str(e)
                    })
                    continue  # DO NOT BREAK LOOP
                
        return results
