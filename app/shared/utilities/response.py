"""
Standardized API response wrapper for all endpoints.
Ensures consistent JSON structure across the entire API surface.
"""
from typing import Any, Optional, Dict
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder


def api_response(
    data: Any = None,
    message: str = "OK",
    success: bool = True,
    meta: Optional[Dict] = None,
    status_code: int = 200,
) -> JSONResponse:
    """Standard success response wrapper."""
    body = {
        "success": success,
        "message": message,
        "data": data,
    }
    if meta:
        body["meta"] = meta
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def paginated_response(
    data: Any,
    total_count: int,
    page: int,
    page_size: int,
    message: str = "OK",
) -> JSONResponse:
    """Paginated response with meta block."""
    return api_response(
        data=data,
        message=message,
        meta={
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": (total_count + page_size - 1) // page_size if page_size > 0 else 0,
        },
    )


def error_response(
    message: str = "Error",
    code: str = "UNKNOWN_ERROR",
    request_id: str = "-",
    status_code: int = 400,
) -> JSONResponse:
    """Standard error response."""
    from datetime import datetime, timezone
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "traceId": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        },
    )
