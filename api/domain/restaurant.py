from dataclasses import dataclass


@dataclass(frozen=True)
class Restaurant:
    id: int
    name: str
    is_open: bool


@dataclass(frozen=True)
class Dish:
    id: int
    name: str
    price_cents: int
    is_available: bool
    units_left: int | None
