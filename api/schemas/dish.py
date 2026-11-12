from pydantic import BaseModel


class DishResponse(BaseModel):
    id: int
    name: str
    price_cents: int
    is_available: bool
