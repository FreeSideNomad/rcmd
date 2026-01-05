"""Database setup utilities for commandbus.

This module provides functions to initialize the database schema
required by commandbus, including tables and stored procedures.
"""

from __future__ import annotations

import importlib.resources
import logging
from typing import TYPE_CHECKING

from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


def get_schema_sql() -> str:
    """Get the SQL schema definition.

    Returns:
        The complete SQL schema as a string.

    Example:
        >>> sql = get_schema_sql()
        >>> print(sql[:50])
        -- V001: Command Bus Core Schema
    """
    files = importlib.resources.files("commandbus.migrations")
    schema_file = files.joinpath("V001__commandbus_schema.sql")
    return schema_file.read_text(encoding="utf-8")


async def setup_database(  # pragma: no cover
    pool_or_conn: AsyncConnectionPool | AsyncConnection,
    *,
    skip_if_exists: bool = True,
) -> bool:
    """Set up the commandbus database schema.

    Creates the 'commandbus' schema with all required tables and
    stored procedures. This function is idempotent - it can be
    called multiple times safely.

    Args:
        pool_or_conn: Either an AsyncConnectionPool or AsyncConnection.
            If a pool is provided, a connection will be acquired from it.
        skip_if_exists: If True (default), skip setup if the schema
            already exists. If False, always run the setup SQL.

    Returns:
        True if the schema was created, False if it already existed
        (when skip_if_exists=True).

    Raises:
        Exception: If database setup fails.

    Example:
        >>> from psycopg_pool import AsyncConnectionPool
        >>> from commandbus import setup_database
        >>>
        >>> async def main():
        ...     pool = AsyncConnectionPool(conninfo="postgresql://localhost/mydb")
        ...     await pool.open()
        ...     created = await setup_database(pool)
        ...     if created:
        ...         print("Schema created successfully")
        ...     else:
        ...         print("Schema already exists")
    """
    if isinstance(pool_or_conn, AsyncConnectionPool):
        async with pool_or_conn.connection() as conn:
            return await _setup_database_impl(conn, skip_if_exists=skip_if_exists)
    else:
        return await _setup_database_impl(pool_or_conn, skip_if_exists=skip_if_exists)


async def _setup_database_impl(  # pragma: no cover
    conn: AsyncConnection,
    *,
    skip_if_exists: bool,
) -> bool:
    """Internal implementation of setup_database."""
    if skip_if_exists:
        # Check if schema already exists
        result = await conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = 'commandbus'
            )
            """
        )
        row = await result.fetchone()
        if row and row[0]:
            logger.info("commandbus schema already exists, skipping setup")
            return False

    # Get and execute the schema SQL
    schema_sql = get_schema_sql()

    logger.info("Setting up commandbus database schema...")
    await conn.execute(schema_sql)
    await conn.commit()
    logger.info("commandbus database schema created successfully")

    return True


async def check_schema_exists(  # pragma: no cover
    pool_or_conn: AsyncConnectionPool | AsyncConnection,
) -> bool:
    """Check if the commandbus schema exists.

    Args:
        pool_or_conn: Either an AsyncConnectionPool or AsyncConnection.

    Returns:
        True if the commandbus schema exists, False otherwise.

    Example:
        >>> exists = await check_schema_exists(pool)
        >>> if not exists:
        ...     await setup_database(pool)
    """
    if isinstance(pool_or_conn, AsyncConnectionPool):
        async with pool_or_conn.connection() as conn:
            return await _check_schema_exists_impl(conn)
    else:
        return await _check_schema_exists_impl(pool_or_conn)


async def _check_schema_exists_impl(conn: AsyncConnection) -> bool:  # pragma: no cover
    """Internal implementation of check_schema_exists."""
    result = await conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.schemata
            WHERE schema_name = 'commandbus'
        )
        """
    )
    row = await result.fetchone()
    return bool(row and row[0])
