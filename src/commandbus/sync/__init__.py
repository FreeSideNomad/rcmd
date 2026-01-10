"""Native synchronous Command Bus runtime components.

This module provides synchronous implementations for the Command Bus,
using psycopg3's thread-safe ConnectionPool for native sync operations.
"""

from commandbus.sync.bus import SyncCommandBus
from commandbus.sync.health import HealthState, HealthStatus
from commandbus.sync.process.router import SyncProcessReplyRouter
from commandbus.sync.timeouts import (
    TimeoutConfig,
    create_pool_with_timeout,
    is_pool_timeout,
    is_query_cancelled,
    is_timeout_error,
    validate_timeouts,
)
from commandbus.sync.watchdog import WorkerWatchdog
from commandbus.sync.worker import SyncWorker

__all__ = [
    "HealthState",
    "HealthStatus",
    "SyncCommandBus",
    "SyncProcessReplyRouter",
    "SyncWorker",
    "TimeoutConfig",
    "WorkerWatchdog",
    "create_pool_with_timeout",
    "is_pool_timeout",
    "is_query_cancelled",
    "is_timeout_error",
    "validate_timeouts",
]
