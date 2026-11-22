import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from sqlalchemy.engine import make_url

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost/test_delivery"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-bytes-long")
# The test client talks plain http://, and a Secure cookie is never sent over http.
os.environ.setdefault("COOKIE_SECURE", "false")

_db_name = make_url(os.environ["DATABASE_URL"]).database or ""
if not _db_name.startswith("test_"):  # NEW
    raise RuntimeError(f"Refusing to run tests against non-test database {_db_name!r}")


import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.auth import create_access_token
from core.database import Base, get_db
from core.enums import UserRole
from domain.user_profile import UserProfile
from main import app
from models.dish import Dish
from models.restaurant import Restaurant
from models.user import User
from scripts.seed import seed

pytest_plugins = ["anyio"]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        poolclass=NullPool,
    )
    return engine


@pytest.fixture(scope="session")
async def setup_database(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()


@pytest.fixture
async def db_session(
    test_engine,
    setup_database,
) -> AsyncGenerator[AsyncSession]:
    conn = await test_engine.connect()
    trans = await conn.begin()

    test_async_session = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with test_async_session() as session:
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
            await conn.close()


@pytest.fixture
async def client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient]:

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def create_test_user(
    client: AsyncClient,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> dict:
    response = await client.post(
        "/v1/users",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, f"Failed to create user: {response.text}"
    return response.json()


async def login(
    client: AsyncClient,
    username: str = "testuser",
    password: str = "testpassword123",
) -> dict[str, str]:
    response = await client.post(
        "/v1/auth/token",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, f"Failed to log in: {response.text}"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def user(client: AsyncClient) -> dict:
    return await create_test_user(client)


@pytest.fixture
async def auth_headers(client: AsyncClient, user: dict) -> dict[str, str]:
    return await login(client)


@pytest.fixture
def customer(user: dict) -> UserProfile:
    """The `user` fixture as the service sees it: everyone who registers is a customer."""
    return UserProfile(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        role=UserRole.CUSTOMER,
        restaurant_id=None,
    )


def bearer(user_id: int) -> dict[str, str]:
    """Auth headers without going through /auth/token: no password needed."""
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def create_member(
    session: AsyncSession, username: str, role: UserRole, restaurant_id: int | None = None
) -> UserProfile:
    """Inserts a user with any role. Registration only creates customers, so staff and riders
    are inserted directly."""
    member = User(
        username=username,
        email=f"{username}@example.com",
        password_hash="-",
        role=role,
        restaurant_id=restaurant_id,
    )
    session.add(member)
    await session.flush()
    return UserProfile(member.id, username, member.email, role, restaurant_id)


@dataclass(frozen=True)
class Catalog:
    """Ids of the seeded catalog, looked up by name.

    Ids are never hard-coded: rolled-back tests don't reset Postgres sequences, so the same
    restaurant gets a different id depending on which tests ran before.
    """

    restaurant_ids: dict[str, int]
    dish_ids: dict[tuple[str, str], int]
    dish_prices: dict[tuple[str, str], int]

    def restaurant(self, name: str) -> int:
        return self.restaurant_ids[name]

    def dish(self, restaurant: str, dish: str) -> int:
        return self.dish_ids[(restaurant, dish)]

    def price(self, restaurant: str, dish: str) -> int:
        return self.dish_prices[(restaurant, dish)]


@pytest.fixture
async def catalog(db_session: AsyncSession) -> Catalog:
    await seed(db_session)
    rows = await db_session.execute(
        select(Restaurant.name, Dish.name, Dish.id, Dish.price_cents, Restaurant.id).join(
            Restaurant, Dish.restaurant_id == Restaurant.id
        )
    )
    restaurant_ids: dict[str, int] = {}
    dish_ids: dict[tuple[str, str], int] = {}
    dish_prices: dict[tuple[str, str], int] = {}
    for restaurant_name, dish_name, dish_id, price_cents, restaurant_id in rows:
        restaurant_ids[restaurant_name] = restaurant_id
        dish_ids[(restaurant_name, dish_name)] = dish_id
        dish_prices[(restaurant_name, dish_name)] = price_cents
    return Catalog(restaurant_ids, dish_ids, dish_prices)
