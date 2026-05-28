"""Production middleware stack for TMS API."""
import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from jose import jwt, JWTError
from app.core.config import settings

logger = logging.getLogger("tms")


# ---------------------------------------------------------------------------
# 1. Request ID Middleware — generates unique ID per request
# ---------------------------------------------------------------------------
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:12])
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# 2. Structured Logging Middleware — logs method, path, status, tenant, user
# ---------------------------------------------------------------------------
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()

        # Extract context from request state or token
        request_id = getattr(request.state, "request_id", "-")
        tenant_id = "-"
        user_id = "-"

        # Try to extract tenant/user from Authorization header (non-blocking)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ", 1)[1]
                payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.ALGORITHM])
                tenant_id = payload.get("temple_id", "-") or "-"
                user_id = payload.get("sub", "-") or "-"
                
                # Store in request state for RLS and context
                request.state.temple_id = payload.get("temple_id")
                request.state.user_role = payload.get("role")
            except (JWTError, Exception):
                request.state.temple_id = None
                request.state.user_role = None

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # Skip noisy health checks from access logs
        if request.url.path != "/health":
            logger.info(
                "%s %s → %s (%sms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={
                    "request_id": request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        return response


# ---------------------------------------------------------------------------
# 3. Security Headers Middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
