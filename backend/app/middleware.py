import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from .logging import get_logger, request_id_var

log = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, exposes it to every log line, and times the request.

    The id is stashed on both the contextvar (for log calls made deeper in the
    stack while this middleware's `try` is still on the stack) and on
    `request.state` (which survives into `ServerErrorMiddleware`, outside this
    middleware, where the bare-`Exception` handler runs after our `finally`
    has already reset the contextvar).
    """

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return response
        finally:
            request_id_var.reset(token)
