from dataclasses import dataclass
from datetime import datetime

from core.enums import OrderStatus


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
