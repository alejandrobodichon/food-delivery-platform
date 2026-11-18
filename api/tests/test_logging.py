import logging

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_generates_request_id_when_missing(client: AsyncClient):
    response = await client.get("/v1/restaurants")

    assert len(response.headers["X-Request-ID"]) == 32  # uuid4().hex


@pytest.mark.anyio
async def test_echoes_valid_request_id(client: AsyncClient):
    response = await client.get("/v1/restaurants", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


@pytest.mark.anyio
async def test_replaces_invalid_request_id(client: AsyncClient):
    response = await client.get("/v1/restaurants", headers={"X-Request-ID": "x" * 200})

    assert response.headers["X-Request-ID"] != "x" * 200


@pytest.mark.anyio
async def test_request_logs_carry_request_id(client: AsyncClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)

    await client.get("/v1/restaurants", headers={"X-Request-ID": "trace-me"})

    request_logs = [r for r in caplog.records if r.name == "api.request"]
    assert request_logs
    assert all(getattr(r, "request_id", None) == "trace-me" for r in request_logs)
