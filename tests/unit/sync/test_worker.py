"""Tests for sync wrapper components (will be replaced by native sync).

The SyncWorker tests have been moved to test_sync_worker.py which tests
the native implementation. This file retains tests for wrapper components
that haven't been replaced yet.
"""

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


def test_sync_process_router_exposes_metadata(runtime: SyncRuntime) -> None:
    router = MagicMock()
    router.run = AsyncMock(return_value=None)
    router.stop = AsyncMock(return_value=None)
    router.reply_queue = "reporting__process_replies"
    router.domain = "reporting"

    sync_router = SyncProcessReplyRouter(router=router, runtime=runtime, thread_pool_size=1)
    assert sync_router.reply_queue == "reporting__process_replies"
    assert sync_router.domain == "reporting"
    sync_router.shutdown()
