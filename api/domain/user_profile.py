from dataclasses import dataclass

from core.enums import UserRole


@dataclass(frozen=True)
class UserProfile:
    id: int
    username: str
    email: str
    role: UserRole
    restaurant_id: int | None


@dataclass(frozen=True)
class UserCredentials:
    """What login needs. Kept apart from UserProfile so the password hash never leaves auth."""

    id: int
    password_hash: str
