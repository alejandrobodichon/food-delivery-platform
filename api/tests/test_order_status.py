"""Status changes and optimistic locking. Who may make each change is in test_order_permissions."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import OrderStatus, UserRole
from core.exceptions import InvalidStatusTransition, OrderNotFound, StaleOrder
from domain.order import Order
from domain.user_profile import UserProfile
from models.order import Order as OrderModel
from repositories.order_repository import OrderRepository
from repositories.restaurant_repository import RestaurantRepository
from schemas.order import OrderCreate, OrderItemCreate
from services.order_service import OrderService
from tests.conftest import Catalog, bearer, create_member


@pytest.fixture
def service(db_session: AsyncSession) -> OrderService:
    return OrderService(OrderRepository(db_session), RestaurantRepository(db_session))


@pytest.fixture
async def order(service: OrderService, customer: UserProfile, catalog: Catalog) -> Order:
    """A pending Burger Palace order at version 1, created through the service."""
    data = OrderCreate(
        restaurant_id=catalog.restaurant("Burger Palace"),
        items=[
            OrderItemCreate(dish_id=catalog.dish("Burger Palace", "Classic Burger"), quantity=1)
        ],
    )
    return await service.create(customer.id, data, idempotency_key="status-tests")


@pytest.fixture
async def staff(db_session: AsyncSession, catalog: Catalog) -> UserProfile:
    """Works at Burger Palace, the restaurant of `order`."""
    return await create_member(
        db_session, "staff", UserRole.RESTAURANT, catalog.restaurant("Burger Palace")
    )


@pytest.fixture
async def rider(db_session: AsyncSession) -> UserProfile:
    return await create_member(db_session, "rider", UserRole.RIDER)


@pytest.fixture
async def paid(db_session: AsyncSession, order: Order) -> int:
    """Marks `order` as paid straight in the database, as the payment webhook will (phase 4):
    no user may do it through the API. Returns the new version, 2."""
    version = await db_session.scalar(
        update(OrderModel)
        .where(OrderModel.id == order.id)
        .values(status=OrderStatus.PAID, version=OrderModel.version + 1)
        .returning(OrderModel.version)
    )
    assert version == 2
    return version


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
    service: OrderService, order: Order, customer: UserProfile, db_session: AsyncSession
):
    updated = await service.change_status(order.id, OrderStatus.CANCELLED, 1, customer)

    assert updated.status == OrderStatus.CANCELLED
    assert updated.version == 2
    assert await stored(db_session, order.id) == (OrderStatus.CANCELLED, 2)


@pytest.mark.anyio
async def test_full_delivery_uses_the_version_returned_by_each_step(
    service: OrderService,
    order: Order,
    paid: int,
    staff: UserProfile,
    rider: UserProfile,
    db_session: AsyncSession,
):
    """What clients do: always send the version from the last response they got."""
    current = await service.change_status(order.id, OrderStatus.PREPARING, paid, staff)
    current = await service.accept(order.id, rider.id)
    current = await service.change_status(order.id, OrderStatus.ON_THE_WAY, current.version, rider)
    current = await service.change_status(order.id, OrderStatus.DELIVERED, current.version, rider)

    assert current.version == 6
    assert await stored(db_session, order.id) == (OrderStatus.DELIVERED, 6)


@pytest.mark.anyio
async def test_stale_version_raises_and_changes_nothing(
    service: OrderService,
    order: Order,
    paid: int,
    staff: UserProfile,
    db_session: AsyncSession,
):
    # The kitchen screen was loaded before the order was paid, at version 1.
    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.CANCELLED, 1, staff)

    assert await stored(db_session, order.id) == (OrderStatus.PAID, 2)


@pytest.mark.anyio
async def test_invalid_transition_raises_and_changes_nothing(
    service: OrderService, order: Order, customer: UserProfile, db_session: AsyncSession
):
    with pytest.raises(InvalidStatusTransition):
        await service.change_status(order.id, OrderStatus.DELIVERED, 1, customer)

    assert await stored(db_session, order.id) == (OrderStatus.PENDING, 1)


@pytest.mark.anyio
async def test_final_state_cannot_change(
    service: OrderService, order: Order, customer: UserProfile
):
    cancelled = await service.change_status(order.id, OrderStatus.CANCELLED, 1, customer)

    with pytest.raises(InvalidStatusTransition):
        await service.change_status(order.id, OrderStatus.CANCELLED, cancelled.version, customer)


@pytest.mark.anyio
async def test_change_status_of_missing_order_raises_not_found(
    service: OrderService, customer: UserProfile
):
    with pytest.raises(OrderNotFound):
        await service.change_status(999_999, OrderStatus.CANCELLED, 1, customer)


@pytest.mark.anyio
async def test_change_between_read_and_write_raises_stale(
    service: OrderService,
    order: Order,
    paid: int,
    staff: UserProfile,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Another request writes between our read and our UPDATE: the version check in the
    UPDATE itself catches it, not only the check on the value we read."""
    stale = await service._order_repo.get_by_id_any(order.id)  # we read "paid", version 2...
    await service.change_status(order.id, OrderStatus.PREPARING, paid, staff)  # ...now v3

    async def get_stale(order_id: int) -> Order | None:
        return stale

    monkeypatch.setattr(service._order_repo, "get_by_id_any", get_stale)

    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.CANCELLED, paid, staff)

    assert await stored(db_session, order.id) == (OrderStatus.PREPARING, 3)


@pytest.mark.anyio
async def test_change_that_keeps_the_status_still_makes_the_order_stale(
    service: OrderService,
    order: Order,
    paid: int,
    staff: UserProfile,
    rider: UserProfile,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """A rider takes the order between our read and our UPDATE. The status is still "paid", so
    only the version tells us the order changed: a status check alone would let this through."""
    stale = await service._order_repo.get_by_id_any(order.id)  # we read "paid", version 2...
    await service.accept(order.id, rider.id)  # ...a rider takes it: still "paid", version 3

    async def get_stale(order_id: int) -> Order | None:
        return stale

    monkeypatch.setattr(service._order_repo, "get_by_id_any", get_stale)

    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.CANCELLED, paid, staff)

    assert await stored(db_session, order.id) == (OrderStatus.PAID, 3)


@pytest.mark.anyio
async def test_rider_assignment_bumps_the_version(
    service: OrderService,
    order: Order,
    paid: int,
    staff: UserProfile,
    rider: UserProfile,
):
    """A kitchen screen loaded before the rider took the order must be told to reload."""
    accepted = await service.accept(order.id, rider.id)

    assert accepted.version == paid + 1
    with pytest.raises(StaleOrder):
        await service.change_status(order.id, OrderStatus.PREPARING, paid, staff)


# --- PATCH /v1/orders/{id} -------------------------------------------------------------------


@pytest.mark.anyio
async def test_patch_order_status(client: AsyncClient, auth_headers: dict, order: Order):
    response = await client.patch(
        f"/v1/orders/{order.id}",
        json={"status": "cancelled", "version": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["version"] == 2


@pytest.mark.anyio
async def test_patch_with_an_old_version_returns_409(
    client: AsyncClient,
    order: Order,
    paid: int,
    staff: UserProfile,
    rider: UserProfile,
    db_session: AsyncSession,
):
    """The kitchen screen still shows version 2, but a rider took the order meanwhile."""
    accepted = await client.post(f"/v1/orders/{order.id}/accept", headers=bearer(rider.id))
    response = await client.patch(
        f"/v1/orders/{order.id}",
        json={"status": "preparing", "version": paid},
        headers=bearer(staff.id),
    )

    assert accepted.status_code == 200
    assert response.status_code == 409
    assert response.json() == {
        "detail": "Order was modified by someone else; reload it and try again."
    }
    assert await stored(db_session, order.id) == (OrderStatus.PAID, 3)


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
        {"status": "cancelled"},  # no version
        {"status": "cancelled", "version": 0},  # versions start at 1
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
        "/v1/orders/999999", json={"status": "cancelled", "version": 1}, headers=auth_headers
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_patch_without_token_returns_401(client: AsyncClient, order: Order):
    response = await client.patch(
        f"/v1/orders/{order.id}", json={"status": "cancelled", "version": 1}
    )

    assert response.status_code == 401
