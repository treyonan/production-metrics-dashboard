"""Correlation-ID middleware and context variable.

Every request gets a correlation ID — either from the inbound
``X-Correlation-ID`` header or freshly generated. It's stashed in a
``ContextVar`` so ``structlog`` can attach it to every log line emitted
during that request, and echoed back in the response header so clients
can quote it when reporting issues.
"""

from contextvars import ContextVar
from typing import Final
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

HEADER_NAME: Final[str] = "X-Correlation-ID"

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Reads or generates an X-Correlation-ID per request.

    The ID is propagated via a ContextVar (for structlog) and echoed in
    the response header (for client-side correlation in logs / traces).
    """

    def __init__(self, app: ASGIApp, header_name: str = HEADER_NAME) -> None:
        super().__init__(app)
        self._header = header_name

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        cid = request.headers.get(self._header) or str(uuid4())
        token = correlation_id_var.set(cid)
        try:
            response: Response = await call_next(request)
            response.headers[self._header] = cid
            return response
        finally:
            correlation_id_var.reset(token)
