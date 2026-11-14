import inspect
import logging

import pytest

from core.timing import timed


@timed
async def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@timed
async def boom() -> None:
    raise ValueError("boom")


def test_timed_keeps_metadata():
    assert add.__name__ == "add"
    assert add.__doc__ == "Add two numbers."
    assert list(inspect.signature(add).parameters) == ["a", "b"]


@pytest.mark.anyio
async def test_timed_logs_duration(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)

    assert await add(1, 2) == 3

    assert any("add took" in r.getMessage() for r in caplog.records)


@pytest.mark.anyio
async def test_timed_logs_and_reraises_on_error(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO)

    with pytest.raises(ValueError):
        await boom()

    assert any("boom took" in r.getMessage() for r in caplog.records)
