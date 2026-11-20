from dataclasses import dataclass
from datetime import datetime

from core.enums import OrderStatus, UserRole
from domain.user_profile import UserProfile

S = OrderStatus

ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.PAID, S.CANCELLED}),
    S.PAID: frozenset({S.PREPARING, S.CANCELLED}),
    S.PREPARING: frozenset({S.ON_THE_WAY}),
    S.ON_THE_WAY: frozenset({S.DELIVERED}),
    S.DELIVERED: frozenset(),
    S.CANCELLED: frozenset(),
}

TRANSITION_ROLE: dict[tuple[S, S], UserRole] = {
    (S.PENDING, S.CANCELLED): UserRole.CUSTOMER,
    (S.PAID, S.PREPARING): UserRole.RESTAURANT,
    (S.PAID, S.CANCELLED): UserRole.RESTAURANT,
    (S.PREPARING, S.ON_THE_WAY): UserRole.RIDER,
    (S.ON_THE_WAY, S.DELIVERED): UserRole.RIDER,
}


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


def can_transition(current: OrderStatus, new: OrderStatus) -> bool:
    return new in ALLOWED_TRANSITIONS[current]


def is_party(order: Order, user: UserProfile) -> bool:
    match user.role:
        case UserRole.CUSTOMER:
            return order.customer_id == user.id
        case UserRole.RESTAURANT:
            return order.restaurant_id == user.restaurant_id
        case UserRole.RIDER:
            return order.rider_id == user.id


def can_make(order: Order, user: UserProfile, new: OrderStatus) -> bool:
    return TRANSITION_ROLE.get((order.status, new)) == user.role
