"""Integration test configuration and shared fixtures.

This module provides shared fixtures for integration tests that need
to create PGMQ queues dynamically for test isolation.
"""

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from commandbus import CommandBus, PgmqClient
from commandbus.handler import HandlerRegistry
from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.worker import Worker


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/commandbus",  # pragma: allowlist secret
    )


@pytest_asyncio.fixture
async def pool(database_url: str) -> AsyncGenerator[AsyncConnectionPool, None]:
    """Create a connection pool for testing."""
    async with AsyncConnectionPool(conninfo=database_url, min_size=1, max_size=5, open=False) as p:
        yield p


@pytest_asyncio.fixture
async def pgmq(pool: AsyncConnectionPool) -> PgmqClient:
    """Create a PGMQ client."""
    return PgmqClient(pool)


@pytest_asyncio.fixture
async def command_bus(pool: AsyncConnectionPool) -> CommandBus:
    """Create a CommandBus with real database connection."""
    return CommandBus(pool)


@pytest.fixture
def handler_registry() -> HandlerRegistry:
    """Create handler registry."""
    return HandlerRegistry()


@pytest_asyncio.fixture
async def worker(pool: AsyncConnectionPool) -> Worker:
    """Create a Worker for the payments domain."""
    return Worker(pool, domain="payments", visibility_timeout=5)


@pytest_asyncio.fixture
async def tsq(pool: AsyncConnectionPool) -> TroubleshootingQueue:
    """Create a TroubleshootingQueue."""
    return TroubleshootingQueue(pool)


@pytest.fixture
def ensure_domain(pgmq: PgmqClient):
    """Factory fixture to ensure a domain's queues exist.

    Usage:
        async def test_something(ensure_domain):
            domain = f"test_{uuid4().hex[:8]}"
            await ensure_domain(domain)
            # Now you can send commands to this domain
    """

    async def _ensure_domain(domain: str) -> None:
        """Create queues for a domain if they don't exist."""
        await pgmq.create_queue(f"{domain}__commands")
        await pgmq.create_queue(f"{domain}__replies")

    return _ensure_domain


@pytest_asyncio.fixture
async def cleanup_payments_domain(pool: AsyncConnectionPool) -> AsyncGenerator[None, None]:
    """Clean up the payments domain before and after each test.

    This fixture ensures test isolation for tests using the 'payments' domain.
    It creates queues if they don't exist and clears all data.
    """
    async with pool.connection() as conn:
        # Create queues if they don't exist (PGMQ create is idempotent)
        await conn.execute("SELECT pgmq.create('payments__commands')")
        await conn.execute("SELECT pgmq.create('payments__replies')")
        await conn.execute("SELECT pgmq.create('reports__replies')")

        # Clean up before test
        await conn.execute("DELETE FROM command_bus_audit WHERE domain = 'payments'")
        await conn.execute("DELETE FROM command_bus_command WHERE domain = 'payments'")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_payments__replies")
        await conn.execute("DELETE FROM pgmq.q_reports__replies")

    yield

    # Clean up after test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM command_bus_audit WHERE domain = 'payments'")
        await conn.execute("DELETE FROM command_bus_command WHERE domain = 'payments'")
        await conn.execute("DELETE FROM pgmq.q_payments__commands")
        await conn.execute("DELETE FROM pgmq.q_payments__replies")
        await conn.execute("DELETE FROM pgmq.q_reports__replies")
