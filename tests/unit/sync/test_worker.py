from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from commandbus.sync.process import SyncProcessReplyRouter
from commandbus.sync.runtime import SyncRuntime
from commandbus.sync.worker import SyncWorker


@pytest.fixture()
def runtime() -> SyncRuntime:
    rt = SyncRuntime()
    yield rt
    rt.shutdown()


def test_sync_worker_runs_blocking(runtime: SyncRuntime) -> None:
    worker = MagicMock()
    worker.run = AsyncMock(return_value=None)
    worker.stop = AsyncMock(return_value=None)

    sync_worker = SyncWorker(worker=worker, runtime=runtime, thread_pool_size=1)
    sync_worker.run(concurrency=2, poll_interval=0.5, use_notify=False)
    worker.run.assert_awaited_once_with(concurrency=2, poll_interval=0.5, use_notify=False)

    sync_worker.stop()
    worker.stop.assert_awaited_once()
    sync_worker.shutdown()


def test_sync_worker_non_blocking(runtime: SyncRuntime) -> None:
    worker = MagicMock()
    worker.run = AsyncMock(return_value=None)
    worker.stop = AsyncMock(return_value=None)
    sync_worker = SyncWorker(worker=worker, runtime=runtime, thread_pool_size=1)

    sync_worker.run(block=False)
    sync_worker.stop()
    sync_worker.shutdown()


def test_sync_worker_prevents_double_run(runtime: SyncRuntime) -> None:
    worker = MagicMock()
    worker.run = AsyncMock(return_value=None)
    worker.stop = AsyncMock(return_value=None)
    sync_worker = SyncWorker(worker=worker, runtime=runtime, thread_pool_size=1)

    sync_worker.run(block=False)
    with pytest.raises(RuntimeError):
        sync_worker.run(block=False)

    sync_worker.stop()
    sync_worker.shutdown()


def test_sync_worker_exposes_domain(runtime: SyncRuntime) -> None:
    worker = MagicMock()
    worker.run = AsyncMock(return_value=None)
    worker.stop = AsyncMock(return_value=None)
    worker.domain = "reporting"

    sync_worker = SyncWorker(worker=worker, runtime=runtime, thread_pool_size=1)
    assert sync_worker.domain == "reporting"
    sync_worker.shutdown()


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
