from pydantic import BaseModel


class RestaurantResponse(BaseModel):
    id: int
    name: str
    is_open: bool
