from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, engine, get_db
from models.restaurant import Restaurant


@pytest.mark.anyio
@pytest.mark.usefixtures("setup_database")
async def test_get_db_rolls_back_when_endpoint_fails():
    app = FastAPI()

    @app.post("/boom")
    async def boom(db: Annotated[AsyncSession, Depends(get_db)]):
        db.add(Restaurant(name="Should Not Persist", is_open=True))
        await db.flush()  # the INSERT really reaches Postgres
        raise RuntimeError("boom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/boom")

    assert response.status_code == 500

    async with AsyncSessionLocal() as session:
        found = await session.scalar(
            select(Restaurant).where(Restaurant.name == "Should Not Persist")
        )
    await engine.dispose()

    assert found is None
