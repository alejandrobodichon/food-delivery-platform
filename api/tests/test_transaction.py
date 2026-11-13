import pytest

from core.database import transaction


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.calls.append("close")

    async def commit(self) -> None:
        self.calls.append("commit")

    async def rollback(self) -> None:
        self.calls.append("rollback")


@pytest.mark.anyio
async def test_commits_on_success():
    fake = FakeSession()

    async with transaction(lambda: fake):
        pass

    assert fake.calls == ["commit", "close"]


@pytest.mark.anyio
async def test_rolls_back_and_reraises_on_error():
    fake = FakeSession()

    with pytest.raises(ValueError):
        async with transaction(lambda: fake):
            raise ValueError("boom")

    assert fake.calls == ["rollback", "close"]