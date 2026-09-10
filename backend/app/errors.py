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


def envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id_var.get()}}


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=envelope(exc.code, exc.message))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = ".".join(str(part) for part in first.get("loc", [])[1:]) or "body"
    message = f"{location}: {first.get('msg', 'invalid request')}"
    return JSONResponse(status_code=422, content=envelope("validation_error", message))


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {404: "not_found", 405: "method_not_allowed"}
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(codes.get(exc.status_code, "http_error"), str(exc.detail)),
    )


async def _unhandled(request: Request, _: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=True, path=request.url.path)
    return JSONResponse(
        status_code=500,
        content=envelope("internal_error", "Unexpected server error. Quote the request_id."),
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
