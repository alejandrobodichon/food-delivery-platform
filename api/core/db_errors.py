import functools
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import OperationalError

from core.exceptions import DatabaseUnavailable


def translate_db_errors[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except OperationalError as e:
            raise DatabaseUnavailable() from e

    return wrapper
