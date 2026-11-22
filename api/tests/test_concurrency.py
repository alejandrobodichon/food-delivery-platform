"""Concurrency tests: many requests compete for the same row at the same time.

These tests can't use the usual `db_session` fixture. That fixture runs the whole test on ONE
connection inside a transaction that is rolled back at the end, so requests can't truly run in
parallel. Here every request goes through the real `get_db`, gets its own connection from the
app's pool and commits, exactly like in production. The data is committed for real, so the
fixture truncates the tables afterwards.
"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal, engine, transaction
from core.enums import OrderStatus, UserRole
from main import app
from models.dish import Dish
from models.order import Order as OrderModel
from models.refresh_token import RefreshToken
from models.restaurant import Restaurant
from models.user import User
from scripts.seed import seed
from tests.conftest import bearer
from tests.test_refresh_tokens import tokens_of

RESTAURANT = "Burger Palace"
DISH = "Classic Burger"


@pytest.fixture
async def committed_db(setup_database) -> AsyncGenerator[None]:
    # The app's engine keeps a pool tied to the event loop that created it, and every test
    # runs in a new loop, so it's disposed before and after.
    await engine.dispose()
    try:
        yield
    finally:
        async with transaction(AsyncSessionLocal) as session:
            await session.execute(
                text(
                    "TRUNCATE refresh_tokens, order_items, orders, dishes, restaurants, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
        await engine.dispose()


@pytest.fixture
async def real_client(committed_db) -> AsyncGenerator[AsyncClient]:
    """A client that uses the real get_db: one session and one connection per request."""
    assert not app.dependency_overrides, "get_db must not be overridden here"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def create_users(
    session: AsyncSession, prefix: str, count: int, role: UserRole = UserRole.CUSTOMER
) -> list[int]:
    """Inserts users directly: hashing a password per user through the API would be slow."""
    users = [
        User(
            username=f"{prefix}{i}",
            email=f"{prefix}{i}@example.com",
            password_hash="-",
            role=role,
        )
        for i in range(count)
    ]
    session.add_all(users)
    await session.flush()
    return [user.id for user in users]


async def ids_of(session: AsyncSession) -> tuple[int, int]:
    """Ids of the seeded restaurant and dish used by these tests."""
    row = (
        await session.execute(
            select(Restaurant.id, Dish.id)
            .join(Dish, Dish.restaurant_id == Restaurant.id)
            .where(Restaurant.name == RESTAURANT, Dish.name == DISH)
        )
    ).one()
    return row[0], row[1]


# --- 20 riders accept the same order ---------------------------------------------------------

RIDERS = 20


@dataclass(frozen=True)
class RiderRace:
    order_id: int
    rider_ids: list[int]


async def create_rider_race(status: OrderStatus) -> RiderRace:
    """Commits one order in `status` and RIDERS rider users."""
    async with transaction(AsyncSessionLocal) as session:
        await seed(session)
        [customer_id] = await create_users(session, "customer", 1)
        rider_ids = await create_users(session, "rider", RIDERS, UserRole.RIDER)
        restaurant_id, _ = await ids_of(session)
        order = OrderModel(
            customer_id=customer_id,
            restaurant_id=restaurant_id,
            status=status,
            total_cents=0,
            idempotency_key="race",
        )
        session.add(order)
        await session.flush()
        return RiderRace(order_id=order.id, rider_ids=rider_ids)


async def accept_all_at_once(client: AsyncClient, race: RiderRace) -> list[int]:
    """Fires every rider's request concurrently; returns the status codes in rider order."""
    responses = await asyncio.gather(
        *(
            client.post(f"/v1/orders/{race.order_id}/accept", headers=bearer(rider_id))
            for rider_id in race.rider_ids
        )
    )
    return [response.status_code for response in responses]


async def stored_rider(order_id: int) -> int | None:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(OrderModel.rider_id).where(OrderModel.id == order_id))


@pytest.mark.anyio
async def test_only_one_of_many_concurrent_riders_gets_the_order(real_client: AsyncClient):
    race = await create_rider_race(OrderStatus.PAID)

    codes = await accept_all_at_once(real_client, race)

    assert codes.count(200) == 1, codes
    assert codes.count(409) == RIDERS - 1, codes
    winner = race.rider_ids[codes.index(200)]
    assert await stored_rider(race.order_id) == winner


@pytest.mark.anyio
async def test_nobody_can_accept_an_unpaid_order(real_client: AsyncClient):
    race = await create_rider_race(OrderStatus.PENDING)

    codes = await accept_all_at_once(real_client, race)

    assert set(codes) == {409}
    assert await stored_rider(race.order_id) is None


@pytest.mark.anyio
async def test_accept_missing_order_returns_404(real_client: AsyncClient):
    race = await create_rider_race(OrderStatus.PAID)

    response = await real_client.post("/v1/orders/999999/accept", headers=bearer(race.rider_ids[0]))

    assert response.status_code == 404


@pytest.mark.anyio
async def test_accept_returns_the_order(real_client: AsyncClient):
    race = await create_rider_race(OrderStatus.PAID)

    response = await real_client.post(
        f"/v1/orders/{race.order_id}/accept", headers=bearer(race.rider_ids[0])
    )

    assert response.status_code == 200
    assert response.json()["id"] == race.order_id


# --- 50 customers buy the dish of the day ----------------------------------------------------

CUSTOMERS = 50


@dataclass(frozen=True)
class DishRace:
    restaurant_id: int
    dish_id: int
    customer_ids: list[int]


async def create_dish_race(units_left: int | None) -> DishRace:
    """Commits the catalog with one dish limited to `units_left`, and CUSTOMERS customers."""
    async with transaction(AsyncSessionLocal) as session:
        await seed(session)
        restaurant_id, dish_id = await ids_of(session)
        await session.execute(update(Dish).where(Dish.id == dish_id).values(units_left=units_left))
        customer_ids = await create_users(session, "customer", CUSTOMERS)
        return DishRace(restaurant_id, dish_id, customer_ids)


def order_one(client: AsyncClient, race: DishRace, customer_id: int, quantity: int = 1):
    return client.post(
        "/v1/orders",
        json={
            "restaurant_id": race.restaurant_id,
            "items": [{"dish_id": race.dish_id, "quantity": quantity}],
        },
        headers={**bearer(customer_id), "Idempotency-Key": f"buy-{customer_id}"},
    )


async def buy_all_at_once(client: AsyncClient, race: DishRace) -> list[Response]:
    return await asyncio.gather(
        *(order_one(client, race, customer_id) for customer_id in race.customer_ids)
    )


async def stock_and_orders(race: DishRace) -> tuple[int | None, int]:
    async with AsyncSessionLocal() as session:
        units_left = await session.scalar(select(Dish.units_left).where(Dish.id == race.dish_id))
        orders = await session.scalar(select(func.count()).select_from(OrderModel)) or 0
        return units_left, orders


@pytest.mark.anyio
async def test_last_unit_is_sold_exactly_once(real_client: AsyncClient):
    race = await create_dish_race(units_left=1)

    responses = await buy_all_at_once(real_client, race)

    codes = [response.status_code for response in responses]
    assert codes.count(201) == 1, codes
    assert codes.count(409) == CUSTOMERS - 1, codes
    assert {r.json()["detail"] for r in responses if r.status_code == 409} == {"Dish is sold out."}
    assert await stock_and_orders(race) == (0, 1)


@pytest.mark.anyio
async def test_limited_stock_is_never_oversold(real_client: AsyncClient):
    race = await create_dish_race(units_left=3)

    responses = await buy_all_at_once(real_client, race)

    codes = [response.status_code for response in responses]
    assert codes.count(201) == 3, codes
    assert await stock_and_orders(race) == (0, 3)


@pytest.mark.anyio
async def test_unlimited_dish_is_not_counted(real_client: AsyncClient):
    race = await create_dish_race(units_left=None)

    responses = await buy_all_at_once(real_client, race)

    assert {response.status_code for response in responses} == {201}
    assert await stock_and_orders(race) == (None, CUSTOMERS)


@pytest.mark.anyio
async def test_ordering_more_units_than_left_returns_409(real_client: AsyncClient):
    race = await create_dish_race(units_left=2)

    response = await order_one(real_client, race, race.customer_ids[0], quantity=3)

    assert response.status_code == 409
    assert await stock_and_orders(race) == (2, 0)


# --- the same refresh token used twice at once -----------------------------------------------

REFRESHES = 20


async def login_once(client: AsyncClient) -> dict[str, str]:
    """Registers and logs in through the API: a real password hash, committed for real."""
    registered = await client.post(
        "/v1/users",
        json={"username": "racer", "email": "racer@example.com", "password": "testpassword123"},
    )
    assert registered.status_code == 201, registered.text
    response = await client.post(
        "/v1/auth/token", data={"username": "racer", "password": "testpassword123"}
    )
    return tokens_of(response)


def refresh_with(client: AsyncClient, refresh_token: str):
    """An explicit Cookie header wins over the client's cookie jar, so each request sends exactly
    this token even while other responses are setting new ones."""
    return client.post(
        "/v1/auth/refresh",
        headers={"Origin": settings.frontend_origin, "Cookie": f"refresh_token={refresh_token}"},
    )


@pytest.mark.anyio
async def test_only_one_of_many_concurrent_refreshes_wins(real_client: AsyncClient):
    """All of them may read the token as unused; only the atomic UPDATE picks one winner."""
    tokens = await login_once(real_client)

    responses = await asyncio.gather(
        *(refresh_with(real_client, tokens["refresh_token"]) for _ in range(REFRESHES))
    )

    codes = [response.status_code for response in responses]
    assert codes.count(200) == 1, codes
    assert codes.count(401) == REFRESHES - 1, codes


@pytest.mark.anyio
async def test_concurrent_reuse_revokes_the_winners_token_too(real_client: AsyncClient):
    """The losers see a reuse, so the token the winner just got is revoked as well."""
    tokens = await login_once(real_client)

    responses = await asyncio.gather(
        *(refresh_with(real_client, tokens["refresh_token"]) for _ in range(REFRESHES))
    )

    [winner] = [tokens_of(response) for response in responses if response.status_code == 200]
    assert (await refresh_with(real_client, winner["refresh_token"])).status_code == 401


@pytest.mark.anyio
async def test_family_revocation_survives_the_401(real_client: AsyncClient):
    """get_db rolls back when a request fails. The reuse branch commits before raising, or the
    revocation would be undone together with the request and the thief would stay logged in."""
    first = await login_once(real_client)
    second = tokens_of(await refresh_with(real_client, first["refresh_token"]))

    reused = await refresh_with(real_client, first["refresh_token"])

    assert reused.status_code == 401
    async with AsyncSessionLocal() as session:
        alive = await session.scalar(
            select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))
        )
    assert alive == 0
    assert (await refresh_with(real_client, second["refresh_token"])).status_code == 401
