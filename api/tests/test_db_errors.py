import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from core.database import get_db
from main import app


class DownSession:
    async def scalars(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.mark.anyio
async def test_database_down_returns_503(client: AsyncClient):
    async def override_get_db():
        yield DownSession()

    app.dependency_overrides[get_db] = override_get_db

    response = await client.get("/v1/restaurants")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable."}
