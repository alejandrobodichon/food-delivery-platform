from dataclasses import replace

from core.enums import OrderStatus
from core.exceptions import (
    DishUnavailable,
    InternalError,
    InvalidOrder,
    InvalidStatusTransition,
    OrderNotAvailable,
    OrderNotFound,
    RestaurantClosed,
)
from domain.order import Order, OrderItem, can_transition
from repositories.order_repository import OrderRepository
from repositories.restaurant_repository import RestaurantRepository
from schemas.order import OrderCreate


class OrderService:
    def __init__(self, order_repo: OrderRepository, restaurant_repo: RestaurantRepository):
        self._order_repo = order_repo
        self._restaurant_repo = restaurant_repo

    async def get_by_id(self, order_id: int, customer_id: int) -> Order:
        order = await self._order_repo.get_by_id(order_id, customer_id)
        if order is None:
            raise OrderNotFound()
        return order

    async def create(self, customer_id: int, data: OrderCreate, idempotency_key: str) -> Order:
        existing = await self._order_repo.get_by_idempotency_key(customer_id, idempotency_key)
        if existing:
            return existing

        restaurant = await self._restaurant_repo.get_by_id(data.restaurant_id)
        if restaurant is None:
            raise InvalidOrder(f"Restaurant with id {data.restaurant_id} does not exist.")

        if not restaurant.is_open:
            raise RestaurantClosed()

        dish_ids = [item.dish_id for item in data.items]
        dishes = await self._restaurant_repo.get_dishes_with_ids(data.restaurant_id, dish_ids)
        if len(dishes) != len(dish_ids):
            raise InvalidOrder("Some dishes don't exist or don't belong to this restaurant.")

        if any(not dish.is_available for dish in dishes):
            raise DishUnavailable()

        # Create the order
        price_by_dish = {dish.id: dish.price_cents for dish in dishes}
        items = tuple(
            OrderItem(
                dish_id=item.dish_id,
                quantity=item.quantity,
                unit_price_cents=price_by_dish[item.dish_id],
            )
            for item in data.items
        )
        total_cents = sum(item.quantity * item.unit_price_cents for item in items)

        order = await self._order_repo.insert(
            customer_id=customer_id,
            restaurant_id=data.restaurant_id,
            idempotency_key=idempotency_key,
            items=items,
            total_cents=total_cents,
        )

        if order is not None:
            return order

        existing = await self._order_repo.get_by_idempotency_key(
            customer_id=customer_id, idempotency_key=idempotency_key
        )
        if existing is None:
            raise InternalError()
        return existing

    async def change_status(self, order_id: int, new: OrderStatus) -> Order:
        order = await self._order_repo.get_by_id_any(order_id)
        if order is None:
            raise OrderNotFound()
        if not can_transition(order.status, new):
            raise InvalidStatusTransition(f"Cannot change status from {order.status} to {new}.")
        if not await self._order_repo.update_status(order_id, order.status, new):
            raise InvalidStatusTransition("Order status changed concurrently; retry.")
        return replace(order, status=new)

    async def accept(self, order_id: int, rider_id: int) -> Order:
        order = await self._order_repo.assign_rider(order_id, rider_id)
        if order is not None:
            return order
        if await self._order_repo.get_by_id_any(order_id) is None:
            raise OrderNotFound()
        raise OrderNotAvailable()
