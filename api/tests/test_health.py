import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from dependencies import get_redis
from main import app


class FakeRedis:
    def __init__(self, up: bool = True) -> None:
        self.up = up

    async def ping(self) -> bool:
        if not self.up:
            raise RedisConnectionError("down")
        return True


@pytest.mark.anyio
async def test_health_ok(client: AsyncClient):
    app.dependency_overrides[get_redis] = lambda: FakeRedis()

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.anyio
async def test_health_redis_down_returns_503(client: AsyncClient):
    app.dependency_overrides[get_redis] = lambda: FakeRedis(up=False)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Redis unavailable"}
