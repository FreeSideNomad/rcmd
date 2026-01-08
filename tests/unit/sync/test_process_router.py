from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from commandbus.sync.process import SyncProcessReplyRouter
from commandbus.sync.runtime import SyncRuntime


@pytest.fixture()
def runtime() -> SyncRuntime:
    rt = SyncRuntime()
    yield rt
    rt.shutdown()


def test_sync_process_router(runtime: SyncRuntime) -> None:
    router = MagicMock()
    router.run = AsyncMock(return_value=None)
    router.stop = AsyncMock(return_value=None)

    sync_router = SyncProcessReplyRouter(router=router, runtime=runtime, thread_pool_size=1)
    sync_router.run(concurrency=5, poll_interval=0.5, use_notify=False)
    router.run.assert_awaited_once_with(concurrency=5, poll_interval=0.5, use_notify=False)

    sync_router.stop()
    router.stop.assert_awaited_once()

    sync_router.shutdown()
