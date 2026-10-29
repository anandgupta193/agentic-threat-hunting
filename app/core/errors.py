"""AppError hierarchy and the handlers that map every error to one JSON envelope.

    { "error": { "code", "message", "details" }, "request_id": "req_…" }

Stack traces never reach the client; unexpected errors are logged with the request_id and returned as 500.
"""

from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import current_request_id
from app.core.logging import get_logger

log = get_logger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None


class AppError(Exception):
    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "INTERNAL_ERROR"
    log_level: ClassVar[str] = "error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"
    log_level = "warning"


class AuthError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"
    log_level = "warning"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"
    log_level = "warning"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    log_level = "warning"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"
    log_level = "info"


class UnprocessableError(AppError):
    """A business-rule check on a well-formed body (e.g. a limit read from config). Same code as DTO errors."""

    status_code = 422
    code = "VALIDATION_ERROR"
    log_level = "info"


class CreditsError(AppError):
    """Base for 429s. Always carries `Retry-After` so clients know when to come back."""

    status_code = 429
    log_level = "info"

    def __init__(self, message: str, *, retry_after_s: int, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details, headers={"Retry-After": str(max(1, retry_after_s))})
        self.retry_after_s = retry_after_s


class CreditsExhausted(CreditsError):
    code = "CREDITS_EXHAUSTED"


class CreditsContended(CreditsError):
    code = "CREDITS_CONTENDED"


class UpstreamError(AppError):
    status_code = 502
    code = "UPSTREAM_ERROR"


class GatewayTimeoutError(AppError):
    status_code = 504
    code = "UPSTREAM_TIMEOUT"


def _envelope(status: int, code: str, message: str, details: dict[str, Any] | None = None,
              headers: dict[str, str] | None = None) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or {}),
        request_id=current_request_id(),
    )
    return JSONResponse(status_code=status, content=jsonable_encoder(body), headers=headers)


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    getattr(log, exc.log_level)(
        "app_error", code=exc.code, status=exc.status_code, message=exc.message,
        path=request.url.path, details=exc.details,
    )
    return _envelope(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    log.info("validation_rejected", path=request.url.path, errors=errors)
    return _envelope(422, "VALIDATION_ERROR", "Request validation failed", {"errors": errors})


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    log.info("http_error", status=exc.status_code, path=request.url.path)
    code = {404: "ROUTE_NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return _envelope(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, exc_type=type(exc).__name__)
    return _envelope(500, "INTERNAL_ERROR", "An unexpected error occurred")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
