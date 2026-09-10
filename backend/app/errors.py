from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger, request_id_var

log = get_logger(__name__)


class ApiError(Exception):
    """The only exception the app raises on purpose."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _request_id(request: Request) -> str | None:
    """The request's id, preferring `request.state` (survives into
    `ServerErrorMiddleware`, which sits outside our request-context middleware)
    over the contextvar (which may already be reset by the time a bare
    `Exception` handler runs)."""
    return getattr(request.state, "request_id", None) or request_id_var.get()


def envelope(code: str, message: str, request_id: str | None = None) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def _error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    request_id = _request_id(request)
    response = JSONResponse(status_code=status_code, content=envelope(code, message, request_id))
    if request_id:
        response.headers["X-Request-Id"] = request_id
    return response


async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
    return _error_response(request, exc.http_status, exc.code, exc.message)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = ".".join(str(part) for part in first.get("loc", [])[1:]) or "body"
    message = f"{location}: {first.get('msg', 'invalid request')}"
    return _error_response(request, 422, "validation_error", message)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {404: "not_found", 405: "method_not_allowed"}
    return _error_response(
        request, exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail)
    )


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    log.error("unhandled_exception", exc_info=exc, path=request.url.path, request_id=request_id)
    return _error_response(
        request, 500, "internal_error", "Unexpected server error. Quote the request_id."
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
