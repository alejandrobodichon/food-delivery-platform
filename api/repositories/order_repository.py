from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db_errors import translate_db_errors
from core.enums import OrderStatus
from core.timing import timed
from domain.order import Order, OrderItem
from models.order import Order as OrderModel
from models.order_item import OrderItem as OrderItemModel


def _to_order_domain(order: OrderModel, items: Sequence[OrderItemModel]) -> Order:
    return Order(
        id=order.id,
        customer_id=order.customer_id,
        restaurant_id=order.restaurant_id,
        rider_id=order.rider_id,
        status=order.status,
        total_cents=order.total_cents,
        version=order.version,
        created_at=order.created_at,
        items=tuple(OrderItem(i.dish_id, i.quantity, i.unit_price_cents) for i in items),
    )


def _to_order_model(
    customer_id: int, restaurant_id: int, idempotency_key: str, total_cents: int
) -> OrderModel:
    return OrderModel(
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        idempotency_key=idempotency_key,
        total_cents=total_cents,
    )


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @timed
    @translate_db_errors
    async def insert(
        self,
        customer_id: int,
        restaurant_id: int,
        idempotency_key: str,
        items: Sequence[OrderItem],
        total_cents: int,
    ) -> Order | None:
        order = await self._session.scalar(
            insert(OrderModel)
            .values(
                customer_id=customer_id,
                restaurant_id=restaurant_id,
                idempotency_key=idempotency_key,
                status=OrderStatus.PENDING,
                total_cents=total_cents,
            )
            .on_conflict_do_nothing(constraint="uq_orders_customer_id_idempotency_key")
            .returning(OrderModel)
        )

        if order is None:
            return None

        order_items = [
            OrderItemModel(
                order_id=order.id,
                dish_id=i.dish_id,
                quantity=i.quantity,
                unit_price_cents=i.unit_price_cents,
            )
            for i in items
        ]
        self._session.add_all(order_items)
        await self._session.flush()
        return _to_order_domain(order, order_items)

    @timed
    @translate_db_errors
    async def get_by_idempotency_key(self, customer_id: int, idempotency_key: str) -> Order | None:
        order = await self._session.scalar(
            select(OrderModel).where(
                OrderModel.customer_id == customer_id,
                OrderModel.idempotency_key == idempotency_key,
            )
        )
        if order is None:
            return None
        return await self._with_items(order)

    async def _with_items(self, order: OrderModel) -> Order:
        items = await self._session.scalars(
            select(OrderItemModel)
            .where(OrderItemModel.order_id == order.id)
            .order_by(OrderItemModel.id)
        )
        return _to_order_domain(order, items.all())

    @timed
    @translate_db_errors
    async def get_by_id(self, order_id: int, customer_id: int) -> Order | None:
        order = await self._session.scalar(
            select(OrderModel).where(
                OrderModel.id == order_id, OrderModel.customer_id == customer_id
            )
        )
        if order is None:
            return None
        return await self._with_items(order)
