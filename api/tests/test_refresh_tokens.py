"""Refresh tokens: rotation, reuse detection, expiry, logout, and the cookie that carries them.

Two cases need the real get_db and live in test_concurrency.py: two refreshes with the same token
at the same time, and the family revocation surviving the rollback of the 401.

The helpers send the refresh cookie by hand instead of letting the client's cookie jar do it:
reuse tests have to send an OLD token, and a jar always holds the newest one.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.refresh_token import RefreshToken
from tests.conftest import create_test_user

ORIGIN = {"Origin": settings.frontend_origin}


def tokens_of(response: Response) -> dict[str, str]:
    """The access token from the body and the refresh token from the Set-Cookie header."""
    assert response.status_code == 200, response.text
    return {
        "access_token": response.json()["access_token"],
        "refresh_token": response.cookies["refresh_token"],
    }


def set_cookie_header(response: Response) -> str:
    [header] = response.headers.get_list("set-cookie")
    return header


async def login(client: AsyncClient, username: str = "testuser") -> dict[str, str]:
    response = await client.post(
        "/v1/auth/token", data={"username": username, "password": "testpassword123"}
    )
    return tokens_of(response)


async def post_with_cookie(
    client: AsyncClient,
    path: str,
    refresh_token: str | None,
    headers: dict[str, str] = ORIGIN,
) -> Response:
    client.cookies.clear()
    cookie = {} if refresh_token is None else {"Cookie": f"refresh_token={refresh_token}"}
    return await client.post(path, headers={**headers, **cookie})


async def refresh(client: AsyncClient, refresh_token: str | None) -> Response:
    return await post_with_cookie(client, "/v1/auth/refresh", refresh_token)


async def logout(client: AsyncClient, refresh_token: str | None) -> Response:
    return await post_with_cookie(client, "/v1/auth/logout", refresh_token)


async def me(client: AsyncClient, access_token: str) -> Response:
    return await client.get("/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})


def sha256(token: str) -> str:
    """Restated instead of importing hash_token, so the test doesn't check it against itself."""
    return hashlib.sha256(token.encode()).hexdigest()


# --- login -----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_login_returns_the_access_token_in_the_body(client: AsyncClient, user: dict):
    tokens = await login(client)

    assert (await me(client, tokens["access_token"])).status_code == 200


@pytest.mark.anyio
async def test_refresh_token_is_not_in_the_body(client: AsyncClient, user: dict):
    """JavaScript can read the body. The refresh token must only live in the HttpOnly cookie."""
    response = await client.post(
        "/v1/auth/token", data={"username": "testuser", "password": "testpassword123"}
    )

    assert set(response.json()) == {"access_token", "token_type"}


@pytest.mark.anyio
async def test_refresh_cookie_flags(client: AsyncClient, user: dict):
    response = await client.post(
        "/v1/auth/token", data={"username": "testuser", "password": "testpassword123"}
    )

    header = set_cookie_header(response).lower()
    assert header.startswith("refresh_token=")
    assert "httponly" in header  # JavaScript can't read it: an XSS can't steal it
    assert "samesite=strict" in header  # not sent on requests started by another site
    assert "path=/v1/auth" in header  # not sent to every API call
    assert f"max-age={settings.refresh_token_expire_days * 24 * 60 * 60}" in header


@pytest.mark.anyio
async def test_refresh_token_is_stored_hashed(
    client: AsyncClient, user: dict, db_session: AsyncSession
):
    """A leaked database must not give out usable tokens."""
    tokens = await login(client)

    stored = list(await db_session.scalars(select(RefreshToken.token_hash)))

    assert stored == [sha256(tokens["refresh_token"])]
    assert tokens["refresh_token"] not in stored


@pytest.mark.anyio
async def test_each_login_starts_a_new_family(
    client: AsyncClient, user: dict, db_session: AsyncSession
):
    await login(client)
    await login(client)

    families = set(await db_session.scalars(select(RefreshToken.family_id)))

    assert len(families) == 2


# --- refresh and rotation --------------------------------------------------------------------


@pytest.mark.anyio
async def test_refresh_returns_a_new_working_pair(client: AsyncClient, user: dict):
    tokens = await login(client)

    new = tokens_of(await refresh(client, tokens["refresh_token"]))

    assert new["refresh_token"] != tokens["refresh_token"]
    assert (await me(client, new["access_token"])).status_code == 200


@pytest.mark.anyio
async def test_rotated_token_stays_in_the_same_family(
    client: AsyncClient, user: dict, db_session: AsyncSession
):
    tokens = await login(client)
    await refresh(client, tokens["refresh_token"])

    families = list(await db_session.scalars(select(RefreshToken.family_id)))

    assert len(families) == 2
    assert len(set(families)) == 1


@pytest.mark.anyio
async def test_a_refresh_token_works_only_once(client: AsyncClient, user: dict):
    tokens = await login(client)
    await refresh(client, tokens["refresh_token"])

    response = await refresh(client, tokens["refresh_token"])

    assert response.status_code == 401


@pytest.mark.anyio
async def test_reusing_a_token_revokes_the_whole_family(client: AsyncClient, user: dict):
    """A used token coming back means someone has a copy: the newer token dies too."""
    first = await login(client)
    second = tokens_of(await refresh(client, first["refresh_token"]))

    reused = await refresh(client, first["refresh_token"])
    after = await refresh(client, second["refresh_token"])

    assert reused.status_code == 401
    assert after.status_code == 401


@pytest.mark.anyio
async def test_reuse_in_one_login_does_not_touch_another(client: AsyncClient, user: dict):
    """The phone's token was stolen; the laptop, logged in separately, keeps working."""
    phone = await login(client)
    laptop = await login(client)
    await refresh(client, phone["refresh_token"])
    await refresh(client, phone["refresh_token"])  # reuse: the phone's family is revoked

    response = await refresh(client, laptop["refresh_token"])

    assert response.status_code == 200


@pytest.mark.anyio
async def test_expired_refresh_token_returns_401(
    client: AsyncClient, user: dict, db_session: AsyncSession
):
    tokens = await login(client)
    await db_session.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    response = await refresh(client, tokens["refresh_token"])

    assert response.status_code == 401
    assert response.json() == {"detail": "Refresh token is invalid or expired."}


@pytest.mark.anyio
async def test_unknown_refresh_token_returns_401(client: AsyncClient):
    response = await refresh(client, "not-a-real-token")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_refresh_without_the_cookie_returns_401(client: AsyncClient):
    response = await refresh(client, None)

    assert response.status_code == 401


# --- CSRF: the Origin check ------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {}],
    ids=["another site", "no Origin"],
)
@pytest.mark.parametrize("path", ["/v1/auth/refresh", "/v1/auth/logout"])
async def test_cookie_endpoints_reject_other_origins(
    client: AsyncClient,
    user: dict,
    db_session: AsyncSession,
    path: str,
    headers: dict[str, str],
):
    """The browser sends the cookie on its own; Origin tells us which site started the request.
    The token must be left untouched: a forged request may not rotate or revoke it."""
    tokens = await login(client)

    response = await post_with_cookie(client, path, tokens["refresh_token"], headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Request origin not allowed."}
    revoked = await db_session.scalar(select(RefreshToken.revoked_at))
    assert revoked is None


# --- logout ----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_logout_ends_the_session_and_clears_the_cookie(client: AsyncClient, user: dict):
    tokens = await login(client)

    response = await logout(client, tokens["refresh_token"])

    assert response.status_code == 204
    header = set_cookie_header(response).lower()
    assert header.startswith('refresh_token=""') or header.startswith("refresh_token=;")
    assert "max-age=0" in header
    assert "path=/v1/auth" in header  # same path as when it was set, or it's another cookie
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401


@pytest.mark.anyio
async def test_logout_revokes_tokens_already_rotated(client: AsyncClient, user: dict):
    """Logging out with an old token of the session still ends the current one."""
    first = await login(client)
    current = tokens_of(await refresh(client, first["refresh_token"]))

    await logout(client, first["refresh_token"])

    assert (await refresh(client, current["refresh_token"])).status_code == 401


@pytest.mark.anyio
async def test_logout_keeps_other_sessions(client: AsyncClient, user: dict):
    phone = await login(client)
    laptop = await login(client)

    await logout(client, phone["refresh_token"])

    assert (await refresh(client, laptop["refresh_token"])).status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("refresh_token", ["not-a-real-token", None], ids=["unknown", "missing"])
async def test_logout_without_a_valid_session_is_a_no_op(
    client: AsyncClient, refresh_token: str | None
):
    response = await logout(client, refresh_token)

    assert response.status_code == 204


@pytest.mark.anyio
async def test_logout_all_ends_every_session_of_the_user(client: AsyncClient, user: dict):
    phone = await login(client)
    laptop = await login(client)

    response = await client.post(
        "/v1/auth/logout-all", headers={"Authorization": f"Bearer {laptop['access_token']}"}
    )

    assert response.status_code == 204
    assert "max-age=0" in set_cookie_header(response).lower()
    assert (await refresh(client, phone["refresh_token"])).status_code == 401
    assert (await refresh(client, laptop["refresh_token"])).status_code == 401


@pytest.mark.anyio
async def test_logout_all_needs_no_origin(client: AsyncClient, user: dict):
    """It's authenticated by the Authorization header, which another site can't add: no CSRF."""
    tokens = await login(client)

    response = await client.post(
        "/v1/auth/logout-all", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert response.status_code == 204


@pytest.mark.anyio
async def test_logout_all_keeps_other_users_sessions(client: AsyncClient, user: dict):
    mine = await login(client)
    await create_test_user(client, username="other", email="other@example.com")
    theirs = await login(client, username="other")

    await client.post(
        "/v1/auth/logout-all", headers={"Authorization": f"Bearer {mine['access_token']}"}
    )

    assert (await refresh(client, theirs["refresh_token"])).status_code == 200


@pytest.mark.anyio
async def test_logout_all_without_token_returns_401(client: AsyncClient):
    response = await client.post("/v1/auth/logout-all")

    assert response.status_code == 401
