"""User rules: create (generated id, default/maximum limit, 409 on duplicates) and existence checks."""

import uuid

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.logging import get_logger
from app.db.engine import Database
from app.modules.users.dtos import CreateUserRequest, UserDTO
from app.modules.users.repository import UserRepository

log = get_logger(__name__)


class UserExists(ConflictError):
    code = "USER_EXISTS"


class UserNotFound(NotFoundError):
    code = "USER_NOT_FOUND"


class UserService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._repo = UserRepository()

    async def create(self, req: CreateUserRequest) -> UserDTO:
        token_limit = req.token_limit or self._settings.token_limit_default
        if token_limit > self._settings.max_token_limit:
            raise UnprocessableError(f"token_limit must be ≤ {self._settings.max_token_limit}",
                                     details={"token_limit": token_limit})
        user_id = req.user_id or f"user_{uuid.uuid4().hex[:12]}"
        try:
            async with self._db.session() as s, s.begin():
                user = await self._repo.insert(s, user_id, token_limit)
        except IntegrityError as exc:
            raise UserExists("User already exists", details={"user_id": user_id}) from exc
        log.info("user_created", new_user_id=user_id, token_limit=token_limit)
        return UserDTO(user_id=user.user_id, token_limit=user.token_limit, created_at=user.created_at)

    async def ensure_exists(self, user_id: str) -> None:
        async with self._db.session() as s:
            if not await self._repo.exists(s, user_id):
                raise UserNotFound("User not found", details={"user_id": user_id})
