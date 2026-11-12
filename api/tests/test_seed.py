import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.dish import Dish
from models.restaurant import Restaurant
from scripts.seed import CATALOG, seed


@pytest.mark.anyio
async def test_seed_twice_does_not_duplicate(db_session: AsyncSession):
    await seed(db_session)
    await seed(db_session)

    restaurants = await db_session.scalar(select(func.count()).select_from(Restaurant))
    dishes = await db_session.scalar(select(func.count()).select_from(Dish))

    assert restaurants == len(CATALOG)
    assert dishes == sum(len(menu) for _, _, menu in CATALOG)
