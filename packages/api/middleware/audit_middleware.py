"""
DataExtraction Enterprise — PII Access & Audit Trail Middleware
Intercepts queries, exports, and mutations of sensitive corporate and executive records,
logging auditable immutable records to the SOC-2 Type II audit repository.
"""

import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from packages.infrastructure.audit_trail_repository import AuditTrailRepository

logger = logging.getLogger("dataextraction.audit.middleware")

AUDITED_PREFIXES = (
    "/api/leads",
    "/api/export",
    "/api/search",
    "/api/compliance",
)


class AuditTrailMiddleware(BaseHTTPMiddleware):
    """Logs data access operations to the immutable compliance ledger."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Fast path bypass for non-audited routes
        if not path.startswith(AUDITED_PREFIXES) or request.method == "OPTIONS":
            return await call_next(request)

        response = await call_next(request)

        # Asynchronously capture audit record on completion
        try:
            user_id = "anonymous"
            user_email = "anonymous@public.net"

            # Parse user principal if token exists
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    from jose import jwt
                    from packages.infrastructure.config_manager import config_manager
                    tok = auth_header.replace("Bearer ", "").strip()
                    alg = config_manager.get_jwt_algorithm().upper()
                    key = config_manager.get_jwt_public_key() if alg.startswith("RS") else config_manager.get_jwt_secret()
                    payload = jwt.decode(tok, key, algorithms=[alg], options={"verify_exp": False})
                    user_email = payload.get("email") or payload.get("sub") or user_email
                    user_id = payload.get("uid") or user_email
                except Exception:
                    pass

            # Map action category
            if "/export" in path:
                action = "LEAD_EXPORT"
                res_type = "export"
            elif "/search" in path:
                action = "SEARCH_QUERY"
                res_type = "search"
            elif "/compliance" in path:
                action = "COMPLIANCE_OPERATION"
                res_type = "compliance"
            else:
                action = "LEAD_MUTATION" if request.method in ("POST", "PUT", "PATCH", "DELETE") else "LEAD_READ"
                res_type = "leads"

            forwarded = request.headers.get("x-forwarded-for")
            ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
            user_agent = request.headers.get("user-agent", "")

            AuditTrailRepository.record_access_event(
                user_id=str(user_id),
                user_email=str(user_email),
                action=action,
                resource_type=res_type,
                resource_id=path,
                ip_address=ip,
                user_agent=user_agent,
                status_code=response.status_code,
                metadata={"method": request.method, "query_params": dict(request.query_params)},
            )
        except Exception as exc:
            logger.debug("Failed to record audit trail in middleware: %s", exc)

        return response

