from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from core.config import settings
from core.exceptions import InvalidRefreshToken
from dependencies import AuthServiceDep, CurrentUser, verify_origin
from domain.refresh_token import TokenPair
from schemas.auth import Token

router = APIRouter()

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/v1/auth"  # only sent to the auth endpoints, not to every API call

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    # Same key, path and flags as when it was set, or the browser treats it as another cookie.
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _token(pair: TokenPair, response: Response) -> Token:
    _set_refresh_cookie(response, pair.refresh_token)
    return Token(access_token=pair.access_token, token_type="bearer")


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: AuthServiceDep,
    response: Response,
):
    pair = await service.login(form_data.username.lower(), form_data.password)
    return _token(pair, response)


@router.post("/refresh", response_model=Token, dependencies=[Depends(verify_origin)])
async def refresh(service: AuthServiceDep, response: Response, refresh_token: RefreshCookie = None):
    if refresh_token is None:
        raise InvalidRefreshToken()
    pair = await service.refresh(refresh_token)
    return _token(pair, response)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_origin)]
)
async def logout(
    service: AuthServiceDep, response: Response, refresh_token: RefreshCookie = None
) -> None:
    if refresh_token is not None:
        await service.logout(refresh_token)
    _clear_refresh_cookie(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    current_user: CurrentUser, service: AuthServiceDep, response: Response
) -> None:
    await service.logout_all(current_user.id)
    _clear_refresh_cookie(response)
