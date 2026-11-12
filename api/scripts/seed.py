"""Load demo restaurants and dishes. Safe to run more than once.

Usage (from api/): uv run python -m scripts.seed
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, engine
from models.dish import Dish
from models.restaurant import Restaurant

# (restaurant name, is_open, [(dish name, price in cents, is_available)])
CATALOG: list[tuple[str, bool, list[tuple[str, int, bool]]]] = [
    (
        "Burger Palace",
        True,
        [
            ("Classic Burger", 950000, True),
            ("Cheese Burger", 1050000, True),
            ("Veggie Burger", 990000, True),
            ("French Fries", 450000, True),
        ],
    ),
    (
        "Pasta Nostra",
        True,
        [
            ("Spaghetti Bolognese", 1200000, True),
            ("Fettuccine Alfredo", 1250000, True),
            ("Lasagna", 1400000, False),  # sold out: lets us test unavailable dishes
            ("Tiramisu", 650000, True),
        ],
    ),
    (
        "Green Bowl",
        True,
        [
            ("Caesar Salad", 880000, True),
            ("Quinoa Bowl", 970000, True),
            ("Poke Bowl", 1150000, True),
            ("Fresh Lemonade", 350000, True),
        ],
    ),
    (
        "Taco Loco",
        True,
        [
            ("Beef Tacos", 900000, True),
            ("Chicken Burrito", 1100000, True),
            ("Nachos", 750000, True),
            ("Guacamole", 500000, True),
        ],
    ),
    (
        "Sushi Go",
        False,  # closed: lets us test that closed restaurants can't take orders
        [
            ("Salmon Roll", 1300000, True),
            ("Tuna Nigiri", 1450000, True),
            ("Miso Soup", 400000, True),
            ("Edamame", 380000, True),
        ],
    ),
]


async def seed(session: AsyncSession) -> None:
    for restaurant_name, is_open, dishes in CATALOG:
        # ponytail: restaurant names aren't unique in the schema, the seed owns these names
        restaurant_id = await session.scalar(
            select(Restaurant.id).where(Restaurant.name == restaurant_name)
        )
        if restaurant_id is None:
            restaurant = Restaurant(name=restaurant_name, is_open=is_open)
            session.add(restaurant)
            await session.flush()
            restaurant_id = restaurant.id

        await session.execute(
            insert(Dish)
            .values(
                [
                    {
                        "restaurant_id": restaurant_id,
                        "name": name,
                        "price_cents": price_cents,
                        "is_available": is_available,
                    }
                    for name, price_cents, is_available in dishes
                ]
            )
            .on_conflict_do_nothing(constraint="uq_dishes_restaurant_id_name")
        )


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await seed(session)
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
