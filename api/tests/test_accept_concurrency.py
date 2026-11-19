"""Concurrency tests: many riders accept the same order at the same time.

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
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from core.auth import create_access_token
from core.database import AsyncSessionLocal, engine, transaction
from core.enums import OrderStatus
from main import app
from models.order import Order as OrderModel
from models.restaurant import Restaurant
from models.user import User
from scripts.seed import seed

RIDERS = 20


@dataclass(frozen=True)
class Race:
    order_id: int
    rider_ids: list[int]


async def create_race(status: OrderStatus) -> Race:
    """Commits one order in `status` and RIDERS rider users."""
    async with transaction(AsyncSessionLocal) as session:
        await seed(session)
        customer = User(username="customer", email="customer@example.com", password_hash="-")
        riders = [
            User(username=f"rider{i}", email=f"rider{i}@example.com", password_hash="-")
            for i in range(RIDERS)
        ]
        session.add_all([customer, *riders])
        await session.flush()

        restaurant_id = await session.scalar(
            select(Restaurant.id).where(Restaurant.name == "Burger Palace")
        )
        assert restaurant_id is not None
        order = OrderModel(
            customer_id=customer.id,
            restaurant_id=restaurant_id,
            status=status,
            total_cents=0,
            idempotency_key="race",
        )
        session.add(order)
        await session.flush()
        return Race(order_id=order.id, rider_ids=[rider.id for rider in riders])


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
                    "TRUNCATE order_items, orders, dishes, restaurants, users "
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


def bearer(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def accept_all_at_once(client: AsyncClient, race: Race) -> list[int]:
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
    race = await create_race(OrderStatus.PAID)

    codes = await accept_all_at_once(real_client, race)

    assert codes.count(200) == 1, codes
    assert codes.count(409) == RIDERS - 1, codes
    winner = race.rider_ids[codes.index(200)]
    assert await stored_rider(race.order_id) == winner


@pytest.mark.anyio
async def test_nobody_can_accept_an_unpaid_order(real_client: AsyncClient):
    race = await create_race(OrderStatus.PENDING)

    codes = await accept_all_at_once(real_client, race)

    assert set(codes) == {409}
    assert await stored_rider(race.order_id) is None


@pytest.mark.anyio
async def test_accept_missing_order_returns_404(real_client: AsyncClient):
    race = await create_race(OrderStatus.PAID)

    response = await real_client.post("/v1/orders/999999/accept", headers=bearer(race.rider_ids[0]))

    assert response.status_code == 404


@pytest.mark.anyio
async def test_accept_returns_the_order(real_client: AsyncClient):
    race = await create_race(OrderStatus.PAID)

    response = await real_client.post(
        f"/v1/orders/{race.order_id}/accept", headers=bearer(race.rider_ids[0])
    )

    assert response.status_code == 200
    assert response.json()["id"] == race.order_id
