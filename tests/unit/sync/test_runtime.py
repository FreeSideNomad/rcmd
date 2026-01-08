import asyncio

import pytest

from commandbus.sync.runtime import SyncRuntime


async def _async_value(value: int) -> int:
    await asyncio.sleep(0)
    return value


def test_runtime_runs_coroutines() -> None:
    runtime = SyncRuntime()
    try:
        assert runtime.run(_async_value(7)) == 7
        assert runtime.run_many([_async_value(1), _async_value(2)]) == [1, 2]
    finally:
        runtime.shutdown()


def test_runtime_disallows_reuse_after_shutdown() -> None:
    runtime = SyncRuntime()
    runtime.shutdown()
    coro = _async_value(0)
    with pytest.raises(RuntimeError):
        runtime.run(coro)
    coro.close()
