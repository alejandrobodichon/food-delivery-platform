import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order import Order
from models.restaurant import Restaurant
from tests.conftest import Catalog, create_test_user, login


async def place_order(
    client: AsyncClient,
    headers: dict[str, str],
    restaurant_id: int,
    items: list[tuple[int, int]],
    key: str = "order-key-1",
) -> Response:
    """POST /v1/orders. `items` is a list of (dish_id, quantity)."""
    return await client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "items": [{"dish_id": dish_id, "quantity": qty} for dish_id, qty in items],
        },
        headers={**headers, "Idempotency-Key": key},
    )


async def count_orders(db_session: AsyncSession) -> int:
    return await db_session.scalar(select(func.count()).select_from(Order)) or 0


@pytest.mark.anyio
async def test_create_order(client: AsyncClient, auth_headers: dict, catalog: Catalog):
    burger = catalog.dish("Burger Palace", "Classic Burger")
    fries = catalog.dish("Burger Palace", "French Fries")

    response = await place_order(
        client, auth_headers, catalog.restaurant("Burger Palace"), [(burger, 2), (fries, 1)]
    )

    assert response.status_code == 201
    body = response.json()
    assert response.headers["Location"] == f"/v1/orders/{body['id']}"
    assert body["status"] == "pending"
    assert body["restaurant_id"] == catalog.restaurant("Burger Palace")
    assert body["total_cents"] == 2 * catalog.price(
        "Burger Palace", "Classic Burger"
    ) + catalog.price("Burger Palace", "French Fries")
    assert body["items"] == [
        {
            "dish_id": burger,
            "quantity": 2,
            "unit_price_cents": catalog.price("Burger Palace", "Classic Burger"),
        },
        {
            "dish_id": fries,
            "quantity": 1,
            "unit_price_cents": catalog.price("Burger Palace", "French Fries"),
        },
    ]


@pytest.mark.anyio
async def test_create_order_ignores_client_prices(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    burger = catalog.dish("Burger Palace", "Classic Burger")

    response = await client.post(
        "/v1/orders",
        json={
            "restaurant_id": catalog.restaurant("Burger Palace"),
            "items": [{"dish_id": burger, "quantity": 1, "unit_price_cents": 1}],
            "total_cents": 1,
        },
        headers={**auth_headers, "Idempotency-Key": "cheap"},
    )

    assert response.status_code == 201
    assert response.json()["total_cents"] == catalog.price("Burger Palace", "Classic Burger")


@pytest.mark.anyio
async def test_create_order_without_token_returns_401(client: AsyncClient, catalog: Catalog):
    burger = catalog.dish("Burger Palace", "Classic Burger")

    response = await place_order(client, {}, catalog.restaurant("Burger Palace"), [(burger, 1)])

    assert response.status_code == 401


@pytest.mark.anyio
async def test_create_order_without_idempotency_key_returns_422(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    burger = catalog.dish("Burger Palace", "Classic Burger")

    response = await client.post(
        "/v1/orders",
        json={
            "restaurant_id": catalog.restaurant("Burger Palace"),
            "items": [{"dish_id": burger, "quantity": 1}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_order_with_no_items_returns_422(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    response = await place_order(client, auth_headers, catalog.restaurant("Burger Palace"), [])

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_order_with_repeated_dish_returns_422(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    burger = catalog.dish("Burger Palace", "Classic Burger")

    response = await place_order(
        client, auth_headers, catalog.restaurant("Burger Palace"), [(burger, 1), (burger, 2)]
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_order_for_unknown_restaurant_returns_422(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    burger = catalog.dish("Burger Palace", "Classic Burger")

    response = await place_order(client, auth_headers, 999_999, [(burger, 1)])

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_order_with_dish_from_another_restaurant_returns_422(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    tacos = catalog.dish("Taco Loco", "Beef Tacos")

    response = await place_order(
        client, auth_headers, catalog.restaurant("Burger Palace"), [(tacos, 1)]
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_order_at_closed_restaurant_returns_409(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    roll = catalog.dish("Sushi Go", "Salmon Roll")

    response = await place_order(client, auth_headers, catalog.restaurant("Sushi Go"), [(roll, 1)])

    assert response.status_code == 409
    assert response.json() == {"detail": "Restaurant is closed."}


@pytest.mark.anyio
async def test_create_order_with_unavailable_dish_returns_409(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    lasagna = catalog.dish("Pasta Nostra", "Lasagna")

    response = await place_order(
        client, auth_headers, catalog.restaurant("Pasta Nostra"), [(lasagna, 1)]
    )

    assert response.status_code == 409


@pytest.mark.anyio
async def test_rejected_order_is_not_saved(
    client: AsyncClient, auth_headers: dict, catalog: Catalog, db_session: AsyncSession
):
    lasagna = catalog.dish("Pasta Nostra", "Lasagna")

    await place_order(client, auth_headers, catalog.restaurant("Pasta Nostra"), [(lasagna, 1)])

    assert await count_orders(db_session) == 0


@pytest.mark.anyio
async def test_same_idempotency_key_returns_same_order(
    client: AsyncClient, auth_headers: dict, catalog: Catalog, db_session: AsyncSession
):
    burger = catalog.dish("Burger Palace", "Classic Burger")
    restaurant = catalog.restaurant("Burger Palace")

    first = await place_order(client, auth_headers, restaurant, [(burger, 1)], key="retry-me")
    second = await place_order(client, auth_headers, restaurant, [(burger, 1)], key="retry-me")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert await count_orders(db_session) == 1


@pytest.mark.anyio
async def test_different_idempotency_keys_create_different_orders(
    client: AsyncClient, auth_headers: dict, catalog: Catalog, db_session: AsyncSession
):
    burger = catalog.dish("Burger Palace", "Classic Burger")
    restaurant = catalog.restaurant("Burger Palace")

    first = await place_order(client, auth_headers, restaurant, [(burger, 1)], key="key-a")
    second = await place_order(client, auth_headers, restaurant, [(burger, 1)], key="key-b")

    assert first.json()["id"] != second.json()["id"]
    assert await count_orders(db_session) == 2


@pytest.mark.anyio
async def test_idempotency_key_is_scoped_to_the_customer(
    client: AsyncClient, auth_headers: dict, catalog: Catalog, db_session: AsyncSession
):
    burger = catalog.dish("Burger Palace", "Classic Burger")
    restaurant = catalog.restaurant("Burger Palace")
    await create_test_user(client, username="other", email="other@example.com")
    other_headers = await login(client, username="other")

    mine = await place_order(client, auth_headers, restaurant, [(burger, 1)], key="shared")
    theirs = await place_order(client, other_headers, restaurant, [(burger, 1)], key="shared")

    assert theirs.status_code == 201
    assert theirs.json()["id"] != mine.json()["id"]
    assert await count_orders(db_session) == 2


@pytest.mark.anyio
async def test_retry_returns_original_order_even_if_restaurant_closed_since(
    client: AsyncClient, auth_headers: dict, catalog: Catalog, db_session: AsyncSession
):
    burger = catalog.dish("Burger Palace", "Classic Burger")
    restaurant_id = catalog.restaurant("Burger Palace")
    first = await place_order(client, auth_headers, restaurant_id, [(burger, 1)], key="late")

    restaurant = await db_session.get(Restaurant, restaurant_id)
    assert restaurant is not None
    restaurant.is_open = False
    await db_session.flush()

    retry = await place_order(client, auth_headers, restaurant_id, [(burger, 1)], key="late")

    assert retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]


@pytest.mark.anyio
async def test_get_own_order(client: AsyncClient, auth_headers: dict, catalog: Catalog):
    burger = catalog.dish("Burger Palace", "Classic Burger")
    created = await place_order(
        client, auth_headers, catalog.restaurant("Burger Palace"), [(burger, 1)]
    )

    response = await client.get(created.headers["Location"], headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == created.json()


@pytest.mark.anyio
async def test_get_order_of_another_customer_returns_404(
    client: AsyncClient, auth_headers: dict, catalog: Catalog
):
    burger = catalog.dish("Burger Palace", "Classic Burger")
    created = await place_order(
        client, auth_headers, catalog.restaurant("Burger Palace"), [(burger, 1)]
    )
    await create_test_user(client, username="other", email="other@example.com")
    other_headers = await login(client, username="other")

    response = await client.get(created.headers["Location"], headers=other_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Order not found."}


@pytest.mark.anyio
async def test_get_missing_order_returns_404(client: AsyncClient, auth_headers: dict):
    response = await client.get("/v1/orders/999999", headers=auth_headers)

    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_order_without_token_returns_401(client: AsyncClient):
    response = await client.get("/v1/orders/1")

    assert response.status_code == 401
