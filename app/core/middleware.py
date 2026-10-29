"""Request-context middleware (pure ASGI, so contextvars propagate correctly).

- assigns a server `request_id` to every request and echoes it as `X-Request-Id`
  (a client-sent `X-Request-Id` is never trusted as ours; it is logged as `client_request_id`)
- binds `request_id` into structlog contextvars
- writes one access-log line with status and latency
- last-resort catch: an unhandled error becomes the standard 500 envelope, still carrying the request id
"""

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import new_request_id, set_request_id
from app.core.errors import ErrorBody, ErrorResponse
from app.core.logging import get_logger

log = get_logger("access")

REQUEST_ID_HEADER = b"x-request-id"
MAX_CLIENT_ID_CHARS = 128


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_request_id()
        client_id = next(
            (v.decode("latin-1")[:MAX_CLIENT_ID_CHARS] for k, v in scope["headers"] if k == REQUEST_ID_HEADER),
            None,
        )
        set_request_id(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        if client_id:
            structlog.contextvars.bind_contextvars(client_request_id=client_id)

        status = 500
        started = False
        t0 = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k != REQUEST_ID_HEADER]
                headers.append((REQUEST_ID_HEADER, request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            log.exception("unhandled_error", path=scope.get("path"), exc_type=type(exc).__name__)
            if started:
                raise
            await _send_internal_error(send_wrapper, request_id)
        finally:
            log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status,
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            )


async def _send_internal_error(send: Send, request_id: str) -> None:
    body = ErrorResponse(
        error=ErrorBody(code="INTERNAL_ERROR", message="An unexpected error occurred"),
        request_id=request_id,
    ).model_dump_json().encode()
    await send({
        "type": "http.response.start",
        "status": 500,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})
