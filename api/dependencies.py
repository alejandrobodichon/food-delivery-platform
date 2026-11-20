from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import verify_access_token
from core.database import get_db
from core.enums import UserRole
from core.exceptions import NotAuthenticated, NotAuthorized
from domain.user_profile import UserProfile
from repositories.order_repository import OrderRepository
from repositories.restaurant_repository import RestaurantRepository
from repositories.user_repository import UserRepository
from services.auth_service import AuthService
from services.order_service import OrderService
from services.restaurant_service import RestaurantService
from services.user_service import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/token")


def get_user_repository(db: Annotated[AsyncSession, Depends(get_db)]) -> UserRepository:
    return UserRepository(db)


def get_user_service(
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserService:
    return UserService(repo)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_restaurant_repository(db: Annotated[AsyncSession, Depends(get_db)]) -> RestaurantRepository:
    return RestaurantRepository(db)


def get_restaurant_service(
    repo: Annotated[RestaurantRepository, Depends(get_restaurant_repository)],
) -> RestaurantService:
    return RestaurantService(repo)


RestaurantServiceDep = Annotated[RestaurantService, Depends(get_restaurant_service)]


def get_order_repository(db: Annotated[AsyncSession, Depends(get_db)]) -> OrderRepository:
    return OrderRepository(db)


def get_order_service(
    order_repo: Annotated[OrderRepository, Depends(get_order_repository)],
    restaurant_repo: Annotated[RestaurantRepository, Depends(get_restaurant_repository)],
) -> OrderService:
    return OrderService(order_repo, restaurant_repo)


OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]


def get_auth_service(
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> AuthService:
    return AuthService(repo)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> UserProfile:
    user_id = verify_access_token(token)
    if user_id is None:
        raise NotAuthenticated()
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotAuthenticated()
    return user


CurrentUser = Annotated[UserProfile, Depends(get_current_user)]


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


RedisDep = Annotated[Redis, Depends(get_redis)]


def require_role(*roles: UserRole):
    async def dependency(user: CurrentUser) -> UserProfile:
        if user.role not in roles:
            raise NotAuthorized()
        return user

    return dependency


RiderUser = Annotated[UserProfile, Depends(require_role(UserRole.RIDER))]
