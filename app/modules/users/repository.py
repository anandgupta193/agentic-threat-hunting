"""All SQL for `users`. Callers own the session and the transaction."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


class UserRepository:
    async def get(self, session: AsyncSession, user_id: str) -> User | None:
        return await session.get(User, user_id)

    async def insert(self, session: AsyncSession, user_id: str, token_limit: int) -> User:
        """Raises `IntegrityError` if the user exists; the service maps it to 409."""
        user = User(user_id=user_id, token_limit=token_limit)
        session.add(user)
        await session.flush()
        await session.refresh(user, ["created_at"])
        return user

    async def exists(self, session: AsyncSession, user_id: str) -> bool:
        return (await session.scalar(select(User.user_id).where(User.user_id == user_id))) is not None
