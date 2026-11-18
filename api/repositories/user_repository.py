from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.db_errors import translate_db_errors
from core.exceptions import UserAlreadyExists
from core.timing import timed
from domain.user_profile import UserCredentials, UserProfile
from models.user import User


def _to_profile(user: User) -> UserProfile:
    return UserProfile(id=user.id, username=user.username, email=user.email)


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
    async def get_all(self) -> list[UserProfile]:
        result = await self._session.scalars(select(User).order_by(User.id))
        return [_to_profile(user) for user in result]

    @timed
    @translate_db_errors
    async def get_by_id(self, user_id: int) -> UserProfile | None:
        user = await self._session.get(User, user_id)
        return _to_profile(user) if user else None

    @timed
    @translate_db_errors
    async def get_credentials(self, username: str) -> UserCredentials | None:
        user = await self._session.scalar(select(User).where(User.username == username))
        return UserCredentials(id=user.id, password_hash=user.password_hash) if user else None

    @timed
    @translate_db_errors
    async def create(self, username: str, email: str, password_hash: str) -> UserProfile:
        user = User(username=username, email=email, password_hash=password_hash)
        return await self._save(user)

    @timed
    @translate_db_errors
    async def update(self, user_id: int, changes: dict[str, str]) -> UserProfile:
        user = await self._session.get_one(User, user_id)
        for field, value in changes.items():
            setattr(user, field, value)
        return await self._save(user)

    @timed
    @translate_db_errors
    async def delete(self, user_id: int) -> None:
        user = await self._session.get_one(User, user_id)
        await self._session.delete(user)
        await self._session.commit()

    async def _save(self, user: User) -> UserProfile:
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError as e:
            await self._session.rollback()
            raise UserAlreadyExists() from e
        await self._session.refresh(user)
        return _to_profile(user)
