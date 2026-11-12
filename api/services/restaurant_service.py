from core.exceptions import RestaurantNotFound
from models.dish import Dish
from models.restaurant import Restaurant
from repositories.restaurant_repository import RestaurantRepository


class RestaurantService:
    def __init__(self, restaurant_repo: RestaurantRepository):
        self._repo = restaurant_repo

    async def list_restaurants(self) -> list[Restaurant]:
        return await self._repo.get_all()

    async def get_by_id(self, restaurant_id: int) -> Restaurant:
        restaurant = await self._repo.get_by_id(restaurant_id)
        if restaurant is None:
            raise RestaurantNotFound()
        return restaurant

    async def list_dishes(self, restaurant_id: int) -> list[Dish]:
        # An empty list is ambiguous: no dishes vs no restaurant. Check existence first.
        await self.get_by_id(restaurant_id)
        return await self._repo.get_dishes(restaurant_id)
