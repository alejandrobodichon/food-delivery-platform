from dataclasses import dataclass
from datetime import datetime

from core.enums import OrderStatus

ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset({OrderStatus.PREPARING, OrderStatus.CANCELLED}),
    OrderStatus.PREPARING: frozenset({OrderStatus.ON_THE_WAY}),
    OrderStatus.ON_THE_WAY: frozenset({OrderStatus.DELIVERED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    return new in ALLOWED_TRANSITIONS[current]


@dataclass(frozen=True)
class OrderItem:
    dish_id: int
    quantity: int
    unit_price_cents: int


@dataclass(frozen=True)
class Order:
    id: int
    customer_id: int
    restaurant_id: int
    rider_id: int | None
    status: OrderStatus
    total_cents: int
    version: int
    created_at: datetime
    items: tuple[OrderItem, ...]
