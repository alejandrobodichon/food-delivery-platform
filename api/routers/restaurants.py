from fastapi import APIRouter

from dependencies import RestaurantServiceDep
from schemas.dish import DishResponse
from schemas.restaurant import RestaurantResponse

router = APIRouter()


@router.get("", response_model=list[RestaurantResponse])
async def list_restaurants(service: RestaurantServiceDep):
    return await service.list_restaurants()


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
async def get_restaurant(restaurant_id: int, service: RestaurantServiceDep):
    return await service.get_by_id(restaurant_id)


@router.get("/{restaurant_id}/dishes", response_model=list[DishResponse])
async def list_restaurant_dishes(restaurant_id: int, service: RestaurantServiceDep):
    return await service.list_dishes(restaurant_id)
