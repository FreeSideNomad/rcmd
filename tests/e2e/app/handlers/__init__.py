"""E2E Application Handlers and Registry setup."""

from psycopg_pool import AsyncConnectionPool

from commandbus import HandlerRegistry

from .base import NoOpHandlers, TestCommandHandlers
from .reporting import ReportingHandlers


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


__all__ = ["NoOpHandlers", "ReportingHandlers", "TestCommandHandlers", "create_registry"]
