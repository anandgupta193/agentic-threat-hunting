"""Reusable request guards (FastAPI dependencies). They exit early, before any business logic runs.

- `read_user_id`: header present (401) and well-formed (400)
- `require_self`: header user must equal the `{user_id}` in the path (403)
- `require_user`: `read_user_id` + the user must exist (404)

`X-User-Id` identifies the caller; it is not authentication (see APPROACH §17).
"""

import re
from typing import Annotated

import structlog
from fastapi import Depends, Header, Request

from app.core.errors import AuthError, BadRequestError, ForbiddenError

USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


async def read_user_id(x_user_id: Annotated[str | None, Header()] = None) -> str:
    if x_user_id is None or not x_user_id.strip():
        raise AuthError("X-User-Id header is required")
    user_id = x_user_id.strip()
    if not USER_ID_PATTERN.fullmatch(user_id):
        raise BadRequestError(
            "X-User-Id is malformed", details={"allowed": USER_ID_PATTERN.pattern},
        )
    structlog.contextvars.bind_contextvars(user_id=user_id)
    return user_id


async def require_user(request: Request, user_id: Annotated[str, Depends(read_user_id)]) -> str:
    # The service is read from app.state (not imported) to keep guards free of module imports.
    await request.app.state.user_service.ensure_exists(user_id)
    return user_id


async def require_self(user_id: str, caller_id: Annotated[str, Depends(read_user_id)]) -> str:
    """`user_id` is the path parameter; a caller may only read their own credits/usage."""
    if caller_id != user_id:
        raise ForbiddenError("X-User-Id does not match the requested user")
    return caller_id
