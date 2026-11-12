from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Restaurant(Base):
    __tablename__ = "restaurants"
    __table_args__ = (UniqueConstraint("name", name="uq_restaurants_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
