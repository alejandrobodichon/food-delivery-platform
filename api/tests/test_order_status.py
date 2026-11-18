import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import OrderStatus
from core.exceptions import InvalidStatusTransition, OrderNotFound
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
    """A pending order, created through the service like the real endpoint does."""
    data = OrderCreate(
        restaurant_id=catalog.restaurant("Burger Palace"),
        items=[
            OrderItemCreate(dish_id=catalog.dish("Burger Palace", "Classic Burger"), quantity=1)
        ],
    )
    return await service.create(user["id"], data, idempotency_key="status-tests")


async def stored_status(db_session: AsyncSession, order_id: int) -> OrderStatus | None:
    """Reads the status straight from the database, not through the service under test."""
    return await db_session.scalar(select(OrderModel.status).where(OrderModel.id == order_id))


@pytest.mark.anyio
async def test_change_status(service: OrderService, order: Order, db_session: AsyncSession):
    updated = await service.change_status(order.id, OrderStatus.PAID)

    assert updated.status == OrderStatus.PAID
    assert updated.id == order.id
    assert await stored_status(db_session, order.id) == OrderStatus.PAID


@pytest.mark.anyio
async def test_change_status_through_the_whole_lifecycle(
    service: OrderService, order: Order, db_session: AsyncSession
):
    for status in (
        OrderStatus.PAID,
        OrderStatus.PREPARING,
        OrderStatus.ON_THE_WAY,
        OrderStatus.DELIVERED,
    ):
        await service.change_status(order.id, status)

    assert await stored_status(db_session, order.id) == OrderStatus.DELIVERED


@pytest.mark.anyio
async def test_invalid_transition_raises_and_keeps_status(
    service: OrderService, order: Order, db_session: AsyncSession
):
    with pytest.raises(InvalidStatusTransition):
        await service.change_status(order.id, OrderStatus.DELIVERED)

    assert await stored_status(db_session, order.id) == OrderStatus.PENDING


@pytest.mark.anyio
async def test_final_state_cannot_change(service: OrderService, order: Order):
    await service.change_status(order.id, OrderStatus.CANCELLED)

    with pytest.raises(InvalidStatusTransition):
        await service.change_status(order.id, OrderStatus.PAID)


@pytest.mark.anyio
async def test_change_status_of_missing_order_raises_not_found(service: OrderService):
    with pytest.raises(OrderNotFound):
        await service.change_status(999_999, OrderStatus.PAID)


@pytest.mark.anyio
async def test_update_status_does_nothing_if_status_changed_since_read(
    order: Order, db_session: AsyncSession
):
    """The UPDATE only applies if the row is still in the status the caller validated."""
    repo = OrderRepository(db_session)
    assert await repo.update_status(order.id, OrderStatus.PENDING, OrderStatus.CANCELLED)

    # A second caller that also read "pending" before the first one wrote.
    applied = await repo.update_status(order.id, OrderStatus.PENDING, OrderStatus.PAID)

    assert applied is False
    assert await stored_status(db_session, order.id) == OrderStatus.CANCELLED


@pytest.mark.anyio
async def test_concurrent_change_raises_conflict(
    service: OrderService,
    order: Order,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Another request changes the status between our read and our UPDATE."""
    repo = OrderRepository(db_session)
    stale = await repo.get_by_id_any(order.id)  # we read "pending"...
    await repo.update_status(order.id, OrderStatus.PENDING, OrderStatus.CANCELLED)  # ...they cancel

    async def get_stale(order_id: int) -> Order | None:
        return stale

    monkeypatch.setattr(service._order_repo, "get_by_id_any", get_stale)

    with pytest.raises(InvalidStatusTransition, match="concurrently"):
        await service.change_status(order.id, OrderStatus.PAID)

    assert await stored_status(db_session, order.id) == OrderStatus.CANCELLED
