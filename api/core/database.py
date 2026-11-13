from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

engine = create_async_engine(settings.database_url)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Transactional(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...

@asynccontextmanager
async def transaction[S: Transactional](
    session_factory: Callable[[], AbstractAsyncContextManager[S]],
) -> AsyncGenerator[S, None]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with transaction(AsyncSessionLocal) as session:
        yield session

