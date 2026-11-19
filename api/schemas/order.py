from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from core.enums import OrderStatus


class OrderItemCreate(BaseModel):
    dish_id: int
    quantity: int = Field(gt=0, le=50)


class OrderCreate(BaseModel):
    restaurant_id: int
    items: list[OrderItemCreate] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def dishes_are_unique(self) -> Self:
        dish_ids = [item.dish_id for item in self.items]
        if len(dish_ids) != len(set(dish_ids)):
            raise ValueError("Each dish can appear only once; use quantity instead.")
        return self


class OrderItemResponse(BaseModel):
    dish_id: int
    quantity: int
    unit_price_cents: int


class OrderResponse(BaseModel):
    id: int
    restaurant_id: int
    status: OrderStatus
    total_cents: int
    items: list[OrderItemResponse]
    created_at: datetime
    version: int


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    version: int = Field(ge=1)
