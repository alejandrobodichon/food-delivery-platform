from dataclasses import dataclass


@dataclass(frozen=True)
class UserProfile:
    id: int
    username: str
    email: str


@dataclass(frozen=True)
class UserCredentials:
    """What login needs. Kept apart from UserProfile so the password hash never leaves auth."""

    id: int
    password_hash: str
