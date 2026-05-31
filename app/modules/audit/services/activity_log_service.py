import json
import hashlib
import re
import uuid
import logging
from typing import Optional, Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.modules.audit.models.audit_models import ActivityOutbox
from app.core.config import settings

logger = logging.getLogger(__name__)

REDACT_KEYS_REGEX = re.compile(
    r'(password|otp|token|secret|pin|account_number|aadhaar|card_number|cvv)',
    re.IGNORECASE
)

EMAIL_REGEX = re.compile(r'^([^@]{1,3})[^@]*(@.*)$')
PHONE_REGEX = re.compile(r'^(\+?\d{1,5})?\d{5}$') # Match last 5 digits

class ActivityLogService:
    @staticmethod
    def determine_risk_and_severity(module_name: str, action: str) -> tuple[str, int]:
        """Dynamically compute risk score and severity for operational actions."""
        action_upper = str(action).upper()
        module_upper = str(module_name).upper()
        
        # 1. Critical actions
        if any(w in action_upper for w in ["SUSPEND", "DELETE_TEMPLE", "TENANT", "UNAUTHORIZED"]):
            return "CRITICAL", 100
            
        # 2. Very High actions
        if any(w in action_upper for w in ["PERMISSION", "ROLE", "PASSWORD_RESET", "RBAC", "STATUS_CHANGE", "ASSIGN"]):
            return "VERY_HIGH", 80
            
        # 3. High actions
        if any(w in action_upper for w in ["MODIFY", "UPDATE", "EDIT", "CANCEL", "REFUND", "DAILY_CLOSING", "CORRECTION"]):
            return "HIGH", 50
            
        # 4. Medium actions
        if any(w in action_upper for w in ["CREATE", "ADD", "REQUEST", "APPROVE", "ISSUE", "RECEIVE"]):
            return "MEDIUM", 30
            
        # 5. Low actions
        return "LOW", 10

    @staticmethod
    def redact_secrets(data: Any) -> Any:
        """Recursively redact sensitive secrets from dictionaries and lists."""
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if REDACT_KEYS_REGEX.search(k):
                    redacted[k] = "[REDACTED]"
                else:
                    redacted[k] = ActivityLogService.redact_secrets(v)
            return redacted
        elif isinstance(data, list):
            return [ActivityLogService.redact_secrets(item) for item in data]
        return data

    @staticmethod
    def mask_pii_string(val: str, key_name: str) -> str:
        """Apply masking rules to emails and phone numbers based on key and pattern matches."""
        val_str = str(val).strip()
        key_lower = key_name.lower()
        
        # Email masking
        if "@" in val_str or "email" in key_lower:
            match = EMAIL_REGEX.match(val_str)
            if match:
                return f"{match.group(1)}****{match.group(2)}"
            return "******@*****"
            
        # Phone masking
        if "phone" in key_lower or "mobile" in key_lower or val_str.isdigit():
            if len(val_str) > 5:
                return f"{val_str[:-5]}*****"
            return "*****"
            
        # Name masking
        if "name" in key_lower or "customer" in key_lower:
            parts = val_str.split()
            if len(parts) > 1:
                return f"{parts[0]} {parts[1][0]}***"
            elif len(val_str) > 2:
                return f"{val_str[:2]}***"
            return "***"
            
        return "*****"

    @staticmethod
    def hash_pii_value(val: str) -> str:
        """Hash PII strings using salted SHA-256 for search matching."""
        salt = settings.SECRET_KEY or "default_audit_salt"
        hasher = hashlib.sha256()
        hasher.update(f"{salt}:{str(val).strip().lower()}".encode())
        return hasher.hexdigest()

    @staticmethod
    def extract_and_process_pii(before: Optional[dict], after: Optional[dict]) -> tuple[dict, dict]:
        """Extract PII candidates (name, email, phone, etc.), generate masks and salted hashes."""
        masked = {}
        hashed = {}
        
        pii_keys = {"email", "phone", "mobile", "name", "customer_name", "customer", "address"}
        
        combined = {}
        if before:
            combined.update(before)
        if after:
            combined.update(after)
            
        for k, v in combined.items():
            k_lower = k.lower()
            if any(p in k_lower for p in pii_keys) and v:
                v_str = str(v)
                masked[k] = ActivityLogService.mask_pii_string(v_str, k)
                hashed[k] = ActivityLogService.hash_pii_value(v_str)
                
        return masked, hashed

    @staticmethod
    async def emit_event(
        db: AsyncSession,
        temple_id: UUID,
        module_name: str,
        entity_name: str,
        entity_id: Optional[str],
        action_type: str,
        action_category: str,
        description: str,
        before_value: Optional[dict] = None,
        after_value: Optional[dict] = None,
        performed_by_user_id: Optional[UUID] = None,
        performed_by_name: str = "System",
        performed_by_role: str = "SYSTEM",
        ip_address: str = "127.0.0.1",
        correlation_id: Optional[UUID] = None,
        request_id: Optional[str] = None,
        severity: str = "LOW",
        risk_score: int = 10,
    ) -> ActivityOutbox:
        """
        Stage an operational audit event in the transaction outbox.
        Does NOT commit — uses db.add() and db.flush() so it shares the caller's transaction.
        """
        # 1. Redact secrets
        clean_before = ActivityLogService.redact_secrets(before_value) if before_value else None
        clean_after = ActivityLogService.redact_secrets(after_value) if after_value else None
        
        # 2. Extract and hash PII fields
        masked_pii, hashed_pii = ActivityLogService.extract_and_process_pii(clean_before, clean_after)
        
        # 3. Generate correlation ID if not provided
        cid = correlation_id or uuid.uuid4()
        
        # 4. Instantiate Outbox entry
        outbox_entry = ActivityOutbox(
            temple_id=temple_id,
            module_name=module_name,
            entity_name=entity_name,
            entity_id=entity_id,
            action_type=action_type,
            action_category=action_category,
            description=description,
            before_value=clean_before,
            after_value=clean_after,
            performed_by_user_id=performed_by_user_id or UUID("00000000-0000-0000-0000-000000000000"),
            performed_by_name=performed_by_name,
            performed_by_role=performed_by_role,
            masked_pii=masked_pii,
            hashed_pii=hashed_pii,
            ip_address=ip_address,
            correlation_id=cid,
            request_id=request_id,
            severity=severity,
            risk_score=risk_score
        )
        
        db.add(outbox_entry)
        await db.flush()
        
        logger.info(f"Activity event queued in Outbox for module {module_name} -> {action_type}")
        return outbox_entry
