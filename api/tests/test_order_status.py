import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import OrderStatus
from core.exceptions import InvalidStatusTransition, OrderNotFound, StaleOrder
from domain.order import Order
from models.order import Order as OrderModel
from repositories.order_repository import OrderRepository
from repositories.restaurant_repository import RestaurantRepository
from schemas.order import OrderCreate, OrderItemCreate
from services.order_service import OrderService
from tests.conftest import Catalog


@pytest.fixture
def service(db_session: AsyncSession) -> OrderService:
    return OrderService(OrderRepository(db_session), RestaurantRepository(db_session))


@pytest.fixture
async def order(service: OrderService, user: dict, catalog: Catalog) -> Order:
    """A pending order at version 1, created through the service like the real endpoint does."""
    data = OrderCreate(
        restaurant_id=catalog.restaurant("Burger Palace"),
        items=[
            OrderItemCreate(dish_id=catalog.dish("Burger Palace", "Classic Burger"), quantity=1)
        ],
    )
    return await service.create(user["id"], data, idempotency_key="status-tests")


async def stored(db_session: AsyncSession, order_id: int) -> tuple[OrderStatus, int] | None:
    """Status and version read straight from the database, not through the code under test."""
    row = (
        await db_session.execute(
            select(OrderModel.status, OrderModel.version).where(OrderModel.id == order_id)
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


# --- service ---------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_new_order_starts_at_version_1(order: Order):
    assert order.version == 1


@pytest.mark.anyio
async def test_change_status_bumps_the_version(
    service: OrderService, order: Order, db_session: AsyncSession
):
    updated = await service.change_status(order.id, OrderStatus.PAID, version=1)

    assert updated.status == OrderStatus.PAID
    assert updated.version == 2
    assert await stored(db_session, order.id) == (OrderStatus.PAID, 2)


@pytest.mark.anyio
async def test_each_change_uses_the_version_returned_by_the_previous_one(
    service: OrderService, order: Order, db_session: AsyncSession
):
    """What a client does: always send the version from the last response it got."""
    current = order
    for status in (
        OrderStatus.PAID,
        OrderStatus.PREPARING,
        OrderStatus.ON_THE_WAY,
        OrderStatus.DELIVERED,
    ):
        current = await service.change_status(order.id, status, version=current.version)

    assert await stored(db_session, order.id) == (OrderStatus.DELIVERED, 5)


@pytest.mark.anyio
async def test_stale_version_raises_and_changes_nothing(
    service: OrderService, order: Order, db_session: AsyncSession
):
    await service.change_status(order.id, OrderStatus.PAID, version=1)

    # Someone who still has the screen from before, at version 1.
    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.CANCELLED, version=1)

    assert await stored(db_session, order.id) == (OrderStatus.PAID, 2)


@pytest.mark.anyio
async def test_invalid_transition_raises_and_changes_nothing(
    service: OrderService, order: Order, db_session: AsyncSession
):
    with pytest.raises(InvalidStatusTransition):
        await service.change_status(order.id, OrderStatus.DELIVERED, version=1)

    assert await stored(db_session, order.id) == (OrderStatus.PENDING, 1)


@pytest.mark.anyio
async def test_final_state_cannot_change(service: OrderService, order: Order):
    cancelled = await service.change_status(order.id, OrderStatus.CANCELLED, version=1)

    with pytest.raises(InvalidStatusTransition):
        await service.change_status(order.id, OrderStatus.PAID, version=cancelled.version)


@pytest.mark.anyio
async def test_change_status_of_missing_order_raises_not_found(service: OrderService):
    with pytest.raises(OrderNotFound):
        await service.change_status(999_999, OrderStatus.PAID, version=1)


@pytest.mark.anyio
async def test_change_between_read_and_write_raises_stale(
    service: OrderService,
    order: Order,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Another request writes between our read and our UPDATE: the version check in the
    UPDATE itself catches it, not only the check on the value we read."""
    stale = await service._order_repo.get_by_id_any(order.id)  # we read version 1...
    await service.change_status(order.id, OrderStatus.PAID, version=1)  # ...they move it to 2

    async def get_stale(order_id: int) -> Order | None:
        return stale

    monkeypatch.setattr(service._order_repo, "get_by_id_any", get_stale)

    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.CANCELLED, version=1)

    assert await stored(db_session, order.id) == (OrderStatus.PAID, 2)


@pytest.mark.anyio
async def test_rider_assignment_bumps_the_version(
    service: OrderService, order: Order, db_session: AsyncSession
):
    """A restaurant screen loaded before the rider took the order must be told to reload."""
    paid = await service.change_status(order.id, OrderStatus.PAID, version=1)
    rider_id = order.customer_id  # any existing user; roles come in phase 3

    accepted = await service.accept(order.id, rider_id)

    assert accepted.version == paid.version + 1
    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.PREPARING, version=paid.version)


@pytest.mark.anyio
async def test_patch_order_status(client: AsyncClient, auth_headers: dict, order: Order):
    response = await client.patch(
        f"/v1/orders/{order.id}",
        json={"status": "paid", "version": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    assert response.json()["version"] == 2


@pytest.mark.anyio
async def test_second_patch_with_the_same_version_returns_409(
    client: AsyncClient, auth_headers: dict, order: Order, db_session: AsyncSession
):
    """Two people edit the same order from the same screen: the second one must not win."""
    first = await client.patch(
        f"/v1/orders/{order.id}",
        json={"status": "paid", "version": 1},
        headers=auth_headers,
    )
    second = await client.patch(
        f"/v1/orders/{order.id}",
        json={"status": "cancelled", "version": 1},
        headers=auth_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {
        "detail": "Order was modified by someone else; reload it and try again."
    }
    assert await stored(db_session, order.id) == (OrderStatus.PAID, 2)


@pytest.mark.anyio
async def test_patch_invalid_transition_returns_409(
    client: AsyncClient, auth_headers: dict, order: Order
):
    response = await client.patch(
        f"/v1/orders/{order.id}",
        json={"status": "delivered", "version": 1},
        headers=auth_headers,
    )

    assert response.status_code == 409


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        {"status": "paid"},  # no version
        {"status": "paid", "version": 0},  # versions start at 1
        {"status": "teleported", "version": 1},  # not a status
    ],
)
async def test_patch_with_invalid_body_returns_422(
    client: AsyncClient, auth_headers: dict, order: Order, body: dict
):
    response = await client.patch(f"/v1/orders/{order.id}", json=body, headers=auth_headers)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_patch_missing_order_returns_404(client: AsyncClient, auth_headers: dict):
    response = await client.patch(
        "/v1/orders/999999", json={"status": "paid", "version": 1}, headers=auth_headers
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_patch_without_token_returns_401(client: AsyncClient, order: Order):
    response = await client.patch(f"/v1/orders/{order.id}", json={"status": "paid", "version": 1})

    assert response.status_code == 401


@pytest.mark.anyio
async def test_change_that_keeps_the_status_still_makes_the_order_stale(
    service: OrderService,
    order: Order,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """A rider takes the order between our read and our UPDATE. The status is still "paid", so
    only the version tells us the order changed: a status check alone would let this through."""
    await service.change_status(order.id, OrderStatus.PAID, version=1)
    stale = await service._order_repo.get_by_id_any(order.id)  # we read "paid", version 2...
    await service.accept(order.id, order.customer_id)  # ...a rider takes it: still "paid", v3

    async def get_stale(order_id: int) -> Order | None:
        return stale

    monkeypatch.setattr(service._order_repo, "get_by_id_any", get_stale)

    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.CANCELLED, version=2)

    assert await stored(db_session, order.id) == (OrderStatus.PAID, 3)
