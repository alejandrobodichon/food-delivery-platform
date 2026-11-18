import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.restaurant import Restaurant
from scripts.seed import CATALOG, seed


async def restaurant_id_by_name(db_session: AsyncSession, name: str) -> int:
    restaurant_id = await db_session.scalar(select(Restaurant.id).where(Restaurant.name == name))
    assert restaurant_id is not None
    return restaurant_id


@pytest.mark.anyio
async def test_list_restaurants_empty(client: AsyncClient):
    response = await client.get("/v1/restaurants")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_list_restaurants_includes_closed_ones(client: AsyncClient, db_session: AsyncSession):
    await seed(db_session)

    response = await client.get("/v1/restaurants")

    assert response.status_code == 200
    body = response.json()
    assert [r["name"] for r in body] == [name for name, _, _ in CATALOG]
    assert {r["name"]: r["is_open"] for r in body}["Sushi Go"] is False
    assert set(body[0]) == {"id", "name", "is_open"}


@pytest.mark.anyio
async def test_get_restaurant(client: AsyncClient, db_session: AsyncSession):
    await seed(db_session)
    restaurant_id = await restaurant_id_by_name(db_session, "Burger Palace")

    response = await client.get(f"/v1/restaurants/{restaurant_id}")

    assert response.status_code == 200
    assert response.json() == {"id": restaurant_id, "name": "Burger Palace", "is_open": True}


@pytest.mark.anyio
async def test_get_restaurant_not_found(client: AsyncClient):
    response = await client.get("/v1/restaurants/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Restaurant not found."}


@pytest.mark.anyio
async def test_list_dishes_returns_only_that_restaurant(
    client: AsyncClient, db_session: AsyncSession
):
    await seed(db_session)
    restaurant_id = await restaurant_id_by_name(db_session, "Pasta Nostra")

    response = await client.get(f"/v1/restaurants/{restaurant_id}/dishes")

    assert response.status_code == 200
    body = response.json()
    assert [d["name"] for d in body] == [
        "Spaghetti Bolognese",
        "Fettuccine Alfredo",
        "Lasagna",
        "Tiramisu",
    ]
    lasagna = next(d for d in body if d["name"] == "Lasagna")
    assert lasagna["is_available"] is False
    assert set(lasagna) == {"id", "name", "price_cents", "is_available"}


@pytest.mark.anyio
async def test_list_dishes_empty_menu(client: AsyncClient, db_session: AsyncSession):
    restaurant = Restaurant(name="Empty Kitchen", is_open=True)
    db_session.add(restaurant)
    await db_session.flush()

    response = await client.get(f"/v1/restaurants/{restaurant.id}/dishes")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_list_dishes_restaurant_not_found(client: AsyncClient):
    response = await client.get("/v1/restaurants/999999/dishes")

    assert response.status_code == 404
    assert response.json() == {"detail": "Restaurant not found."}


@pytest.mark.anyio
async def test_restaurant_name_is_unique_in_db(db_session: AsyncSession):
    db_session.add(Restaurant(name="Twin", is_open=True))
    await db_session.flush()

    db_session.add(Restaurant(name="Twin", is_open=False))
    with pytest.raises(IntegrityError, match="uq_restaurants_name"):
        await db_session.flush()
    await db_session.rollback()
