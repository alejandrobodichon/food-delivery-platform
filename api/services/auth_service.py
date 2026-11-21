from datetime import UTC, datetime, timedelta
from uuid import uuid4

from core.auth import create_access_token, generate_token, hash_token, verify_password
from core.config import settings
from core.exceptions import InvalidCredentials, InvalidRefreshToken
from domain.refresh_token import TokenPair
from repositories.refresh_token_repository import RefreshTokenRepository
from repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, user_repository: UserRepository, token_repository: RefreshTokenRepository):
        self._user_repository = user_repository
        self._tokens = token_repository

    async def login(self, username: str, password: str) -> TokenPair:
        credentials = await self._user_repository.get_credentials(username.lower())
        if credentials is None or not verify_password(password, credentials.password_hash):
            raise InvalidCredentials()
        return await self._issue(credentials.id, family_id=str(uuid4()))

    async def refresh(self, refresh_token: str) -> TokenPair:
        stored = await self._tokens.get_by_hash(hash_token(refresh_token))
        if stored is None or stored.expires_at <= datetime.now(UTC):
            raise InvalidRefreshToken()
        if stored.revoked_at is not None or not await self._tokens.revoke(stored.id):
            # Used twice: someone else has a copy. End this login on every device.
            await self._tokens.revoke_family(stored.family_id)
            await self._tokens.commit()  # the 401 below would roll it back otherwise
            raise InvalidRefreshToken()
        return await self._issue(stored.user_id, stored.family_id)

    async def logout(self, refresh_token: str) -> None:
        stored = await self._tokens.get_by_hash(hash_token(refresh_token))
        if stored is not None:
            await self._tokens.revoke_family(stored.family_id)

    async def logout_all(self, user_id: int) -> None:
        await self._tokens.revoke_all_for_user(user_id)

    async def _issue(self, user_id: int, family_id: str) -> TokenPair:
        refresh_token = generate_token()
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
        await self._tokens.add(user_id, hash_token(refresh_token), family_id, expires_at)
        return TokenPair(create_access_token(user_id), refresh_token)
