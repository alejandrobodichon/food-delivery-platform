"""CORS: which origin may READ the API's responses from a browser.

CORS never blocks a request on the server. It only adds headers, and the browser decides whether
the page's JavaScript gets the response. Stopping a forged request from having an EFFECT is the
Origin check on the cookie endpoints (test_refresh_tokens.py).
"""

import pytest
from httpx import AsyncClient

from core.config import settings

FRONTEND = settings.frontend_origin
EVIL = "https://evil.example"


def preflight_headers(origin: str, method: str, headers: str) -> dict[str, str]:
    """What a browser sends before a non-simple request (PATCH, JSON, custom headers)."""
    return {
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": headers,
    }


@pytest.mark.anyio
async def test_preflight_from_the_frontend_is_allowed(client: AsyncClient):
    response = await client.options(
        "/v1/orders",
        headers=preflight_headers(FRONTEND, "POST", "authorization, content-type, idempotency-key"),
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert {"authorization", "content-type", "idempotency-key"} <= {
        header.strip() for header in allowed.split(",")
    }


@pytest.mark.anyio
async def test_preflight_from_another_origin_is_refused(client: AsyncClient):
    """Without an allow header the browser never sends the real request."""
    response = await client.options(
        "/v1/orders", headers=preflight_headers(EVIL, "POST", "content-type")
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.anyio
async def test_preflight_with_a_header_that_is_not_allowed_is_refused(client: AsyncClient):
    response = await client.options(
        "/v1/orders", headers=preflight_headers(FRONTEND, "POST", "x-not-allowed")
    )

    assert response.status_code == 400


@pytest.mark.anyio
async def test_frontend_can_read_responses_with_cookies(client: AsyncClient):
    response = await client.get("/v1/restaurants", headers={"Origin": FRONTEND})

    assert response.status_code == 200
    # The exact origin, never "*": browsers reject "*" together with credentials.
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.anyio
async def test_frontend_can_read_the_location_and_request_id_headers(client: AsyncClient):
    """By default JavaScript only sees a few basic response headers."""
    response = await client.get("/v1/restaurants", headers={"Origin": FRONTEND})

    exposed = response.headers["access-control-expose-headers"].lower()
    assert {"location", "x-request-id"} <= {header.strip() for header in exposed.split(",")}


@pytest.mark.anyio
async def test_another_origin_gets_a_200_it_cannot_read(client: AsyncClient):
    """The server still answers: the "CORS error with a 200". Only the missing header makes the
    browser keep the response from the page."""
    response = await client.get("/v1/restaurants", headers={"Origin": EVIL})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.anyio
async def test_requests_without_origin_are_not_affected(client: AsyncClient):
    """curl and other servers send no Origin: CORS doesn't apply to them at all."""
    response = await client.get("/v1/restaurants")

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.anyio
async def test_handled_errors_are_readable_by_the_frontend(client: AsyncClient):
    """A 404 from our exception handlers goes through the CORS middleware, so the page can read
    the error instead of seeing a generic CORS failure."""
    response = await client.get("/v1/restaurants/999999", headers={"Origin": FRONTEND})

    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == FRONTEND
