"""Structured JSON logging with tenant/user/request context."""
import logging
import logging.handlers
import sys
import json
from pathlib import Path
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit structured JSON log lines for production observability."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Attach context fields if present
        for field in ("request_id", "tenant_id", "user_id", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        # Attach exception info
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class ReadableFormatter(logging.Formatter):
    """Human-readable formatter for console output during development."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", "-")
        tenant_id = getattr(record, "tenant_id", "-")
        user_id = getattr(record, "user_id", "-")
        
        operation = getattr(record, "operation", None)
        status = getattr(record, "status", None)
        
        # Standardized format: [module] [tenant] [operation] [status]
        if operation and status:
            module_name = record.name.replace("tms.", "").capitalize()
            base = f"[{module_name}] [{tenant_id}] [{operation}] [{status}] - {record.getMessage()}"
        else:
            base = f"{record.levelname:<8} | {record.name} | req={request_id} tenant={tenant_id} user={user_id} | {record.getMessage()}"
            
        if record.exc_info and record.exc_info[0] is not None:
            base += "\n" + self.formatException(record.exc_info)
        return base


from app.core.config import settings

def setup_logging():
    """Configure structured logging with file rotation and console output."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # --- JSON file handler (production) ---
    json_handler = logging.handlers.RotatingFileHandler(
        log_dir / "tms_app.json.log", maxBytes=10_485_760, backupCount=5, encoding="utf-8"
    )
    json_handler.setLevel(logging.INFO)
    json_handler.setFormatter(JSONFormatter())

    # --- Error file handler ---
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "tms_error.log", maxBytes=10_485_760, backupCount=5, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())

    # --- Access log handler ---
    access_handler = logging.handlers.RotatingFileHandler(
        log_dir / "tms_access.log", maxBytes=10_485_760, backupCount=5, encoding="utf-8"
    )
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(JSONFormatter())

    # --- Console handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    if settings.LOG_LEVEL.lower() == "production":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ReadableFormatter())

    root_logger = logging.getLogger("tms")
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(json_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(access_handler)
    root_logger.addHandler(console_handler)

    return root_logger
