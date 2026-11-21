from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.refresh_token import StoredRefreshToken
from models.refresh_token import RefreshToken as RefreshTokenModel


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(
        self, user_id: int, token_hash: str, family_id: str, expires_at: datetime
    ) -> None:
        self._session.add(
            RefreshTokenModel(
                user_id=user_id, token_hash=token_hash, family_id=family_id, expires_at=expires_at
            )
        )
        await self._session.flush()

    async def get_by_hash(self, token_hash: str) -> StoredRefreshToken | None:
        token = await self._session.scalar(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        )
        if token is None:
            return None
        return StoredRefreshToken(
            id=token.id,
            user_id=token.user_id,
            family_id=token.family_id,
            expires_at=token.expires_at,
            revoked_at=token.revoked_at,
        )

    async def revoke(self, token_id: int) -> bool:
        """Atomic: of two requests using the same token, only one gets True."""
        revoked_id = await self._session.scalar(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.id == token_id, RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=func.now())
            .returning(RefreshTokenModel.id)
        )
        return revoked_id is not None

    async def revoke_family(self, family_id: str) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.family_id == family_id, RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )

    async def revoke_all_for_user(self, user_id: int) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.user_id == user_id, RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )

    async def commit(self) -> None:
        await self._session.commit()
