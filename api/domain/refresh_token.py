from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StoredRefreshToken:
    id: int
    user_id: int
    family_id: str
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
