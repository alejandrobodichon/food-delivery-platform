from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Dish(Base):
    __tablename__ = "dishes"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "name", name="uq_dishes_restaurant_id_name"),
        CheckConstraint("units_left >= 0", name="ck_dishes_units_left_non_negative"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"))
    units_left: Mapped[int | None] = mapped_column(Integer, nullable=True)
