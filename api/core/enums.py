from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    PREPARING = "preparing"
    ON_THE_WAY = "on_the_way"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class UserRole(StrEnum):
    CUSTOMER = "customer"
    RESTAURANT = "restaurant"
    RIDER = "rider"
