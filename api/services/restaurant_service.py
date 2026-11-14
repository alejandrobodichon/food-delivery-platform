from core.exceptions import RestaurantNotFound
from domain.restaurant import Dish, Restaurant
from models.dish import Dish as DishModel
from models.restaurant import Restaurant as RestaurantModel
from repositories.restaurant_repository import RestaurantRepository


def _to_restaurant(model: RestaurantModel) -> Restaurant:
    return Restaurant(id=model.id, name=model.name, is_open=model.is_open)


def _to_dish(model: DishModel) -> Dish:
    return Dish(
        id=model.id,
        name=model.name,
        price_cents=model.price_cents,
        is_available=model.is_available,
    )


class RestaurantService:
    def __init__(self, restaurant_repo: RestaurantRepository):
        self._repo = restaurant_repo

    async def list_restaurants(self) -> list[Restaurant]:
        return [_to_restaurant(r) for r in await self._repo.get_all()]

    async def get_by_id(self, restaurant_id: int) -> Restaurant:
        restaurant = await self._repo.get_by_id(restaurant_id)
        if restaurant is None:
            raise RestaurantNotFound()
        return _to_restaurant(restaurant)

    async def list_dishes(self, restaurant_id: int) -> list[Dish]:
        # An empty list is ambiguous: no dishes vs no restaurant. Check existence first.
        await self.get_by_id(restaurant_id)
        return [_to_dish(d) for d in await self._repo.get_dishes(restaurant_id)]
