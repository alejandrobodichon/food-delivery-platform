"""Refresh tokens: rotation, reuse detection, expiry and logout.

Two cases need the real get_db and live in test_concurrency.py: two refreshes with the same token
at the same time, and the family revocation surviving the rollback of the 401.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.refresh_token import RefreshToken
from tests.conftest import create_test_user


async def login(client: AsyncClient, username: str = "testuser") -> dict:
    response = await client.post(
        "/v1/auth/token", data={"username": username, "password": "testpassword123"}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def refresh(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})


async def me(client: AsyncClient, access_token: str) -> Response:
    return await client.get("/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})


def sha256(token: str) -> str:
    """Restated instead of importing hash_token, so the test doesn't check it against itself."""
    return hashlib.sha256(token.encode()).hexdigest()


# --- login -----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_login_returns_both_tokens(client: AsyncClient, user: dict):
    tokens = await login(client)

    assert tokens["token_type"] == "bearer"
    assert tokens["refresh_token"]
    assert (await me(client, tokens["access_token"])).status_code == 200


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

    response = await refresh(client, tokens["refresh_token"])

    assert response.status_code == 200
    new = response.json()
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
    second = (await refresh(client, first["refresh_token"])).json()

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
async def test_refresh_without_a_token_returns_422(client: AsyncClient):
    response = await client.post("/v1/auth/refresh", json={"refresh_token": ""})

    assert response.status_code == 422


# --- logout ----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_logout_ends_the_session(client: AsyncClient, user: dict):
    tokens = await login(client)

    response = await client.post("/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 204
    assert (await refresh(client, tokens["refresh_token"])).status_code == 401


@pytest.mark.anyio
async def test_logout_revokes_tokens_already_rotated(client: AsyncClient, user: dict):
    """Logging out with an old token of the session still ends the current one."""
    first = await login(client)
    current = (await refresh(client, first["refresh_token"])).json()

    await client.post("/v1/auth/logout", json={"refresh_token": first["refresh_token"]})

    assert (await refresh(client, current["refresh_token"])).status_code == 401


@pytest.mark.anyio
async def test_logout_keeps_other_sessions(client: AsyncClient, user: dict):
    phone = await login(client)
    laptop = await login(client)

    await client.post("/v1/auth/logout", json={"refresh_token": phone["refresh_token"]})

    assert (await refresh(client, laptop["refresh_token"])).status_code == 200


@pytest.mark.anyio
async def test_logout_with_an_unknown_token_is_a_no_op(client: AsyncClient):
    response = await client.post("/v1/auth/logout", json={"refresh_token": "not-a-real-token"})

    assert response.status_code == 204


@pytest.mark.anyio
async def test_logout_all_ends_every_session_of_the_user(client: AsyncClient, user: dict):
    phone = await login(client)
    laptop = await login(client)

    response = await client.post(
        "/v1/auth/logout-all", headers={"Authorization": f"Bearer {laptop['access_token']}"}
    )

    assert response.status_code == 204
    assert (await refresh(client, phone["refresh_token"])).status_code == 401
    assert (await refresh(client, laptop["refresh_token"])).status_code == 401


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
