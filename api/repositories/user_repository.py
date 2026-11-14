from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.db_errors import translate_db_errors
from core.exceptions import UserAlreadyExists
from core.timing import timed
from models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @timed
    @translate_db_errors
    async def exist_by_username(self, username: str) -> bool:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.first() is not None

    @timed
    @translate_db_errors
    async def exist_by_email(self, email: str) -> bool:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.first() is not None

    @timed
    @translate_db_errors
    async def get_all(self) -> list[User]:
        result = await self._session.execute(select(User))
        users = list(result.scalars())
        return users

    @timed
    @translate_db_errors
    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    @timed
    @translate_db_errors
    async def get_by_username(self, username: str) -> User | None:
        return await self._session.scalar(select(User).where(User.username == username))

    @timed
    @translate_db_errors
    async def save(self, user: User) -> User:
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError as e:
            await self._session.rollback()
            raise UserAlreadyExists() from e
        await self._session.refresh(user)
        return user

    @timed
    @translate_db_errors
    async def delete(self, user: User) -> None:
        await self._session.delete(user)
        await self._session.commit()
