"""Synchronous wrappers for the Command Bus runtime."""

from commandbus.sync.bus import SyncCommandBus
from commandbus.sync.config import configure, get_default_runtime, get_thread_pool_size
from commandbus.sync.health import HealthState, HealthStatus
from commandbus.sync.process import SyncProcessReplyRouter
from commandbus.sync.runtime import SyncRuntime
from commandbus.sync.timeouts import (
    TimeoutConfig,
    create_pool_with_timeout,
    is_pool_timeout,
    is_query_cancelled,
    is_timeout_error,
    validate_timeouts,
)
from commandbus.sync.tsq import SyncTroubleshootingQueue
from commandbus.sync.watchdog import WorkerWatchdog
from commandbus.sync.worker import SyncWorker

__all__ = [
    "HealthState",
    "HealthStatus",
    "SyncCommandBus",
    "SyncProcessReplyRouter",
    "SyncRuntime",
    "SyncTroubleshootingQueue",
    "SyncWorker",
    "TimeoutConfig",
    "WorkerWatchdog",
    "configure",
    "create_pool_with_timeout",
    "get_default_runtime",
    "get_thread_pool_size",
    "is_pool_timeout",
    "is_query_cancelled",
    "is_timeout_error",
    "validate_timeouts",
]
