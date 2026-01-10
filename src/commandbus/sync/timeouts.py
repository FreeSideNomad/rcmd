"""Timeout configuration and validation for sync workers.

This module provides timeout constants, configuration helpers, and validation
for the multi-layer timeout hierarchy used in sync workers and routers.

Timeout Hierarchy:
    Layer 1: PostgreSQL statement_timeout (25s default)
        - Kills query on server, frees database resources
        - Should be less than visibility_timeout

    Layer 2: Connection pool timeout (30s default)
        - Fail-fast on pool exhaustion
        - Raises PoolTimeout if no connection available

    Layer 3: PGMQ visibility_timeout (30s default)
        - Message reappears if not deleted within timeout
        - Allows for automatic retry on failure

    Layer 4: Thread stuck threshold (visibility_timeout + 5s)
        - Worker detects threads running longer than expected
        - Records stuck thread in health status

    Layer 5: Worker watchdog (configurable interval)
        - Monitors overall worker health
        - Can trigger recovery on CRITICAL state
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from psycopg import errors as psycopg_errors
from psycopg_pool import ConnectionPool, PoolTimeout

logger = logging.getLogger(__name__)


# Default timeout values
DEFAULT_STATEMENT_TIMEOUT_MS = 25000  # 25 seconds
DEFAULT_VISIBILITY_TIMEOUT_S = 30  # 30 seconds
DEFAULT_POOL_TIMEOUT_S = 30.0  # 30 seconds
DEFAULT_WATCHDOG_INTERVAL_S = 10.0  # 10 seconds
STUCK_THREAD_BUFFER_S = 5.0  # Added to visibility_timeout for stuck detection


@dataclass(frozen=True)
class TimeoutConfig:
    """Timeout configuration for sync workers and routers.

    All timeouts are validated to ensure proper ordering:
    - statement_timeout (ms) / 1000 < visibility_timeout (s)
    - This ensures queries are cancelled before messages become visible again

    Example:
        config = TimeoutConfig(
            statement_timeout_ms=25000,  # 25s
            visibility_timeout_s=30,     # 30s
            pool_timeout_s=30.0,         # 30s
        )
        config.validate()  # Raises ValueError if invalid

        # Use in worker
        worker = SyncWorker(
            pool=pool,
            domain="payments",
            registry=registry,
            statement_timeout=config.statement_timeout_ms,
            visibility_timeout=config.visibility_timeout_s,
        )
    """

    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS
    visibility_timeout_s: int = DEFAULT_VISIBILITY_TIMEOUT_S
    pool_timeout_s: float = DEFAULT_POOL_TIMEOUT_S
    watchdog_interval_s: float = DEFAULT_WATCHDOG_INTERVAL_S

    @property
    def statement_timeout_s(self) -> float:
        """Get statement timeout in seconds."""
        return self.statement_timeout_ms / 1000.0

    @property
    def stuck_threshold_s(self) -> float:
        """Get stuck thread detection threshold in seconds."""
        return self.visibility_timeout_s + STUCK_THREAD_BUFFER_S

    def validate(self) -> None:
        """Validate timeout configuration.

        Raises:
            ValueError: If timeouts are not properly ordered or invalid
        """
        # All timeouts must be positive (check this first)
        if self.statement_timeout_ms <= 0:
            raise ValueError(f"statement_timeout_ms must be positive: {self.statement_timeout_ms}")

        if self.visibility_timeout_s <= 0:
            raise ValueError(f"visibility_timeout_s must be positive: {self.visibility_timeout_s}")

        if self.pool_timeout_s <= 0:
            raise ValueError(f"pool_timeout_s must be positive: {self.pool_timeout_s}")

        if self.watchdog_interval_s <= 0:
            raise ValueError(f"watchdog_interval_s must be positive: {self.watchdog_interval_s}")

        # Statement timeout must be less than visibility timeout
        if self.statement_timeout_s >= self.visibility_timeout_s:
            raise ValueError(
                f"statement_timeout ({self.statement_timeout_s}s) must be less than "
                f"visibility_timeout ({self.visibility_timeout_s}s)"
            )


def validate_timeouts(
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    visibility_timeout_s: int = DEFAULT_VISIBILITY_TIMEOUT_S,
) -> None:
    """Validate statement and visibility timeouts.

    Args:
        statement_timeout_ms: PostgreSQL statement timeout in milliseconds
        visibility_timeout_s: PGMQ visibility timeout in seconds

    Raises:
        ValueError: If statement_timeout >= visibility_timeout
    """
    config = TimeoutConfig(
        statement_timeout_ms=statement_timeout_ms,
        visibility_timeout_s=visibility_timeout_s,
    )
    config.validate()


def create_pool_with_timeout(
    conninfo: str,
    min_size: int = 4,
    max_size: int | None = None,
    timeout: float = DEFAULT_POOL_TIMEOUT_S,
    **kwargs: Any,
) -> ConnectionPool[Any]:
    """Create a connection pool with proper timeout configuration.

    Args:
        conninfo: PostgreSQL connection string
        min_size: Minimum pool size (should be >= worker concurrency)
        max_size: Maximum pool size (defaults to min_size * 2)
        timeout: Pool timeout in seconds (fail-fast on exhaustion)
        **kwargs: Additional arguments passed to ConnectionPool

    Returns:
        Configured ConnectionPool instance

    Example:
        pool = create_pool_with_timeout(
            conninfo=DATABASE_URL,
            min_size=4,
            timeout=30.0,
        )
    """
    if max_size is None:
        max_size = min_size * 2

    return ConnectionPool(
        conninfo=conninfo,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        **kwargs,
    )


def is_timeout_error(error: Exception) -> bool:
    """Check if an exception is a timeout-related error.

    Args:
        error: The exception to check

    Returns:
        True if the error is timeout-related (QueryCanceled or PoolTimeout)
    """
    return isinstance(error, psycopg_errors.QueryCanceled | PoolTimeout)


def is_query_cancelled(error: Exception) -> bool:
    """Check if an exception is a QueryCanceled error.

    This indicates the PostgreSQL statement timeout was exceeded.

    Args:
        error: The exception to check

    Returns:
        True if the error is QueryCanceled
    """
    return isinstance(error, psycopg_errors.QueryCanceled)


def is_pool_timeout(error: Exception) -> bool:
    """Check if an exception is a PoolTimeout error.

    This indicates connection pool exhaustion.

    Args:
        error: The exception to check

    Returns:
        True if the error is PoolTimeout
    """
    return isinstance(error, PoolTimeout)
