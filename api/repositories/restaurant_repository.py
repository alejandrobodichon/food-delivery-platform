from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db_errors import translate_db_errors
from core.timing import timed
from models.dish import Dish
from models.restaurant import Restaurant


class RestaurantRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @timed
    @translate_db_errors
    async def get_all(self) -> list[Restaurant]:
        result = await self._session.scalars(select(Restaurant).order_by(Restaurant.id))
        return list(result)

    @timed
    @translate_db_errors
    async def get_by_id(self, restaurant_id: int) -> Restaurant | None:
        return await self._session.get(Restaurant, restaurant_id)

    @timed
    @translate_db_errors
    async def get_dishes(self, restaurant_id: int) -> list[Dish]:
        result = await self._session.scalars(
            select(Dish).where(Dish.restaurant_id == restaurant_id).order_by(Dish.id)
        )
        return list(result)
