from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import verify_access_token
from core.database import get_db
from core.exceptions import NotAuthenticated
from models.user import User
from repositories.restaurant_repository import RestaurantRepository
from repositories.user_repository import UserRepository
from services.auth_service import AuthService
from services.restaurant_service import RestaurantService
from services.user_service import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


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


def get_auth_service(
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> AuthService:
    return AuthService(repo)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    repo: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    user_id = verify_access_token(token)
    if user_id is None:
        raise NotAuthenticated()
    user = await repo.get_by_id(user_id)
    if user is None:
        raise NotAuthenticated()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


RedisDep = Annotated[Redis, Depends(get_redis)]
