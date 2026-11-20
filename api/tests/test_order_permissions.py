"""Who may do what with an order.

The first half tests the domain rules with plain objects, no database. The rules are written
out again here instead of importing TRANSITION_ROLE, so the test doesn't check the code
against itself. The second half goes through HTTP to check the status codes.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import OrderStatus, UserRole
from domain.order import Order, can_make, is_party
from domain.user_profile import UserProfile
from models.order import Order as OrderModel
from tests.conftest import Catalog, bearer, create_member

S = OrderStatus
R = UserRole

WHO_MAY = {
    (S.PENDING, S.CANCELLED): R.CUSTOMER,  # the customer changed their mind before paying
    (S.PAID, S.PREPARING): R.RESTAURANT,
    (S.PAID, S.CANCELLED): R.RESTAURANT,  # e.g. out of an ingredient
    (S.PREPARING, S.ON_THE_WAY): R.RIDER,
    (S.ON_THE_WAY, S.DELIVERED): R.RIDER,
}

CUSTOMER_ID, OTHER_CUSTOMER_ID = 1, 2
RESTAURANT_ID, OTHER_RESTAURANT_ID = 10, 11
RIDER_ID, OTHER_RIDER_ID = 20, 21


def an_order(status: OrderStatus = S.PAID, rider_id: int | None = RIDER_ID) -> Order:
    return Order(
        id=1,
        customer_id=CUSTOMER_ID,
        restaurant_id=RESTAURANT_ID,
        rider_id=rider_id,
        status=status,
        total_cents=1000,
        version=1,
        created_at=datetime.now(UTC),
        items=(),
    )


def a_user(role: UserRole, user_id: int, restaurant_id: int | None = None) -> UserProfile:
    return UserProfile(user_id, f"user{user_id}", f"user{user_id}@example.com", role, restaurant_id)


# --- can_make: whose turn is each step -------------------------------------------------------


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.parametrize("current", list(OrderStatus))
@pytest.mark.parametrize("new", list(OrderStatus))
def test_each_step_belongs_to_exactly_the_expected_role(
    role: UserRole, current: OrderStatus, new: OrderStatus
):
    """Every (status, status, role) combination: a permission added by mistake fails here."""
    user = a_user(role, 1, RESTAURANT_ID if role == R.RESTAURANT else None)

    assert can_make(an_order(current), user, new) == (WHO_MAY.get((current, new)) == role)


@pytest.mark.parametrize("role", list(UserRole))
def test_nobody_can_mark_an_order_as_paid(role: UserRole):
    """Only the payment provider confirms a payment (phase 4), never a user."""
    user = a_user(role, 1, RESTAURANT_ID if role == R.RESTAURANT else None)

    assert not can_make(an_order(S.PENDING), user, S.PAID)


# --- is_party: whose order is it -------------------------------------------------------------


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        (a_user(R.CUSTOMER, CUSTOMER_ID), True),
        (a_user(R.CUSTOMER, OTHER_CUSTOMER_ID), False),
        (a_user(R.RESTAURANT, 30, RESTAURANT_ID), True),
        (a_user(R.RESTAURANT, 31, OTHER_RESTAURANT_ID), False),
        (a_user(R.RIDER, RIDER_ID), True),
        (a_user(R.RIDER, OTHER_RIDER_ID), False),
        # The role decides which field is compared, not just the id.
        (a_user(R.RIDER, CUSTOMER_ID), False),
    ],
    ids=[
        "own customer",
        "other customer",
        "own restaurant",
        "other restaurant",
        "assigned rider",
        "other rider",
        "rider with the customer's id",
    ],
)
def test_is_party(user: UserProfile, expected: bool):
    assert is_party(an_order(), user) == expected


def test_no_rider_is_party_before_one_accepts():
    assert not is_party(an_order(rider_id=None), a_user(R.RIDER, RIDER_ID))


# --- through HTTP ----------------------------------------------------------------------------


@pytest.fixture
async def burger_order(db_session: AsyncSession, customer: UserProfile, catalog: Catalog) -> int:
    """A Burger Palace order of `customer`, inserted directly. Returns its id."""
    order = OrderModel(
        customer_id=customer.id,
        restaurant_id=catalog.restaurant("Burger Palace"),
        status=S.PENDING,
        total_cents=1000,
        idempotency_key="permissions",
    )
    db_session.add(order)
    await db_session.flush()
    return order.id


async def set_order(db_session: AsyncSession, order_id: int, **values) -> None:
    await db_session.execute(update(OrderModel).where(OrderModel.id == order_id).values(**values))


async def patch(client: AsyncClient, order_id: int, user_id: int, status: OrderStatus):
    return await client.patch(
        f"/v1/orders/{order_id}",
        json={"status": status, "version": 1},
        headers=bearer(user_id),
    )


@pytest.mark.anyio
async def test_another_customer_gets_404(
    client: AsyncClient, db_session: AsyncSession, burger_order: int
):
    """404, not 403: a 403 would confirm the order exists."""
    stranger = await create_member(db_session, "stranger", R.CUSTOMER)

    response = await patch(client, burger_order, stranger.id, S.CANCELLED)

    assert response.status_code == 404


@pytest.mark.anyio
async def test_another_restaurant_gets_404(
    client: AsyncClient, db_session: AsyncSession, catalog: Catalog, burger_order: int
):
    await set_order(db_session, burger_order, status=S.PAID)
    sushi = await create_member(db_session, "sushi", R.RESTAURANT, catalog.restaurant("Sushi Go"))

    response = await patch(client, burger_order, sushi.id, S.PREPARING)

    assert response.status_code == 404


@pytest.mark.anyio
async def test_a_rider_who_did_not_accept_the_order_gets_404(
    client: AsyncClient, db_session: AsyncSession, burger_order: int
):
    await set_order(db_session, burger_order, status=S.PREPARING)
    rider = await create_member(db_session, "rider", R.RIDER)

    response = await patch(client, burger_order, rider.id, S.ON_THE_WAY)

    assert response.status_code == 404


@pytest.mark.anyio
async def test_customer_cannot_start_preparing_their_own_order(
    client: AsyncClient, db_session: AsyncSession, customer: UserProfile, burger_order: int
):
    """It's their order and the step is valid, but it's the kitchen's step: 403."""
    await set_order(db_session, burger_order, status=S.PAID)

    response = await patch(client, burger_order, customer.id, S.PREPARING)

    assert response.status_code == 403


@pytest.mark.anyio
async def test_customer_cannot_cancel_once_paid(
    client: AsyncClient, db_session: AsyncSession, customer: UserProfile, burger_order: int
):
    await set_order(db_session, burger_order, status=S.PAID)

    response = await patch(client, burger_order, customer.id, S.CANCELLED)

    assert response.status_code == 403


@pytest.mark.anyio
async def test_restaurant_cannot_mark_an_order_as_paid(
    client: AsyncClient, db_session: AsyncSession, catalog: Catalog, burger_order: int
):
    staff = await create_member(
        db_session, "staff", R.RESTAURANT, catalog.restaurant("Burger Palace")
    )

    response = await patch(client, burger_order, staff.id, S.PAID)

    assert response.status_code == 403


@pytest.mark.anyio
async def test_assigned_rider_cannot_cancel(
    client: AsyncClient, db_session: AsyncSession, burger_order: int
):
    rider = await create_member(db_session, "rider", R.RIDER)
    await set_order(db_session, burger_order, status=S.PAID, rider_id=rider.id)

    response = await patch(client, burger_order, rider.id, S.CANCELLED)

    assert response.status_code == 403


@pytest.mark.anyio
async def test_customer_cannot_accept_an_order(
    client: AsyncClient, db_session: AsyncSession, customer: UserProfile, burger_order: int
):
    await set_order(db_session, burger_order, status=S.PAID)

    response = await client.post(f"/v1/orders/{burger_order}/accept", headers=bearer(customer.id))

    assert response.status_code == 403


@pytest.mark.anyio
async def test_rider_cannot_place_an_order(
    client: AsyncClient, db_session: AsyncSession, catalog: Catalog
):
    rider = await create_member(db_session, "rider", R.RIDER)

    response = await client.post(
        "/v1/orders",
        json={
            "restaurant_id": catalog.restaurant("Burger Palace"),
            "items": [{"dish_id": catalog.dish("Burger Palace", "Classic Burger"), "quantity": 1}],
        },
        headers={**bearer(rider.id), "Idempotency-Key": "rider-order"},
    )

    assert response.status_code == 403
