from collections.abc import Collection

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.db_errors import translate_db_errors
from core.timing import timed
from domain.restaurant import Dish, Restaurant
from models.dish import Dish as DishModel
from models.restaurant import Restaurant as RestaurantModel


def _to_restaurant(model: RestaurantModel) -> Restaurant:
    return Restaurant(id=model.id, name=model.name, is_open=model.is_open)


def _to_dish(model: DishModel) -> Dish:
    return Dish(
        id=model.id,
        name=model.name,
        price_cents=model.price_cents,
        is_available=model.is_available,
        units_left=model.units_left,
    )


class RestaurantRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @timed
    @translate_db_errors
    async def get_all(self) -> list[Restaurant]:
        result = await self._session.scalars(select(RestaurantModel).order_by(RestaurantModel.id))
        return [_to_restaurant(r) for r in result]

    @timed
    @translate_db_errors
    async def get_by_id(self, restaurant_id: int) -> Restaurant | None:
        restaurant = await self._session.get(RestaurantModel, restaurant_id)
        return _to_restaurant(restaurant) if restaurant else None

    @timed
    @translate_db_errors
    async def get_dishes(self, restaurant_id: int) -> list[Dish]:
        result = await self._session.scalars(
            select(DishModel).where(DishModel.restaurant_id == restaurant_id).order_by(DishModel.id)
        )
        return [_to_dish(d) for d in result]

    @timed
    @translate_db_errors
    async def get_dishes_with_ids(
        self, restaurant_id: int, dish_ids: Collection[int]
    ) -> list[Dish]:
        result = await self._session.scalars(
            select(DishModel)
            .where(DishModel.restaurant_id == restaurant_id, DishModel.id.in_(dish_ids))
            .order_by(DishModel.id)
        )
        return [_to_dish(d) for d in result]

    @timed
    @translate_db_errors
    async def take_units(self, dish_id: int, quantity: int) -> bool:
        taken_id = await self._session.scalar(
            update(DishModel)
            .where(DishModel.id == dish_id, DishModel.units_left >= quantity)
            .values(units_left=DishModel.units_left - quantity)
            .returning(DishModel.id)
        )
        return taken_id is not None
