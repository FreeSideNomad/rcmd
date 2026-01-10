"""E2E Application Handlers and Registry setup."""

from typing import Any

from psycopg_pool import AsyncConnectionPool

from commandbus import HandlerRegistry

from .base import NoOpHandlers, TestCommandHandlers
from .reporting import ReportingHandlers
from .sync_handlers import create_sync_handler_registry


def create_registry(pool: AsyncConnectionPool) -> HandlerRegistry:
    """Create handler registry using F007 composition root pattern.

    This uses:
    - @handler decorator on class methods
    - register_instance() for automatic handler discovery
    """
    # Create handler instances with dependencies
    test_handlers = TestCommandHandlers(pool)
    no_op_handlers = NoOpHandlers(pool)
    reporting_handlers = ReportingHandlers(pool)

    # Register all decorated handlers
    registry = HandlerRegistry()
    registry.register_instance(test_handlers)
    registry.register_instance(no_op_handlers)
    registry.register_instance(reporting_handlers)

    return registry


def create_sync_registry(pool: Any) -> HandlerRegistry:
    """Create handler registry with sync handlers for native SyncWorker.

    This wraps async handlers with sync adapters using asyncio.run(),
    allowing the same handler implementations to work with both async
    and sync workers.

    Args:
        pool: Database connection pool (can be async or sync, handlers
              will use it according to their implementation)

    Returns:
        HandlerRegistry with sync handlers registered
    """
    # Create handler instances with dependencies
    # Note: handlers still use async pool internally - each sync dispatch
    # runs the async handler in its own event loop via asyncio.run()
    test_handlers = TestCommandHandlers(pool)
    no_op_handlers = NoOpHandlers(pool)
    reporting_handlers = ReportingHandlers(pool)

    # Register as sync handlers (wraps async handlers)
    registry = HandlerRegistry()
    registry.register_instance_as_sync(test_handlers)
    registry.register_instance_as_sync(no_op_handlers)
    registry.register_instance_as_sync(reporting_handlers)

    return registry


__all__ = [
    "NoOpHandlers",
    "ReportingHandlers",
    "TestCommandHandlers",
    "create_registry",
    "create_sync_handler_registry",
    "create_sync_registry",  # Deprecated: use create_sync_handler_registry
]
