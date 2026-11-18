from core.auth import create_access_token, verify_password
from core.exceptions import InvalidCredentials
from repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, user_repository: UserRepository):
        self._user_repository = user_repository

    async def login(self, username: str, password: str) -> str:
        credentials = await self._user_repository.get_credentials(username.lower())
        if credentials is None or not verify_password(password, credentials.password_hash):
            raise InvalidCredentials()
        return create_access_token(credentials.id)
