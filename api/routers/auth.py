from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from dependencies import AuthServiceDep, CurrentUser
from domain.refresh_token import TokenPair
from schemas.auth import RefreshRequest, Token

router = APIRouter()


def _token(pair: TokenPair) -> Token:
    return Token(
        access_token=pair.access_token, refresh_token=pair.refresh_token, token_type="bearer"
    )


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], service: AuthServiceDep
):
    pair = await service.login(form_data.username.lower(), form_data.password)
    return _token(pair)


@router.post("/refresh", response_model=Token)
async def refresh(data: RefreshRequest, service: AuthServiceDep):
    pair = await service.refresh(data.refresh_token)
    return _token(pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, service: AuthServiceDep) -> None:
    await service.logout(data.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(current_user: CurrentUser, service: AuthServiceDep) -> None:
    await service.logout_all(current_user.id)
