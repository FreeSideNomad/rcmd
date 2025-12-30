"""Repository for command metadata storage."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from commandbus.models import CommandMetadata, CommandStatus

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class CommandRepository(Protocol):
    """Protocol for command metadata storage."""

    async def save(
        self,
        metadata: CommandMetadata,
        queue_name: str,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Save command metadata."""
        ...

    async def get(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> CommandMetadata | None:
        """Get command metadata by domain and command_id."""
        ...

    async def update_status(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update command status."""
        ...

    async def exists(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Check if a command exists."""
        ...


class PostgresCommandRepository:
    """PostgreSQL implementation of CommandRepository."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        """Initialize the repository.

        Args:
            pool: psycopg async connection pool
        """
        self._pool = pool

    async def save(
        self,
        metadata: CommandMetadata,
        queue_name: str,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Save command metadata to the database.

        Args:
            metadata: Command metadata to save
            queue_name: The queue name for this command
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._save(conn, metadata, queue_name)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._save(acquired_conn, metadata, queue_name)

    async def _save(
        self,
        conn: AsyncConnection[Any],
        metadata: CommandMetadata,
        queue_name: str,
    ) -> None:
        """Save metadata using an existing connection."""
        await conn.execute(
            """
            INSERT INTO command_bus_command (
                domain, queue_name, msg_id, command_id, command_type,
                status, attempts, max_attempts, correlation_id, reply_queue,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                metadata.domain,
                queue_name,
                metadata.msg_id,
                metadata.command_id,
                metadata.command_type,
                metadata.status.value,
                metadata.attempts,
                metadata.max_attempts,
                metadata.correlation_id,
                metadata.reply_to or "",
                metadata.created_at,
                metadata.updated_at,
            ),
        )
        logger.debug(
            f"Saved command metadata: {metadata.domain}.{metadata.command_id}"
        )

    async def get(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> CommandMetadata | None:
        """Get command metadata by domain and command_id.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            CommandMetadata if found, None otherwise
        """
        if conn is not None:
            return await self._get(conn, domain, command_id)

        async with self._pool.connection() as acquired_conn:
            return await self._get(acquired_conn, domain, command_id)

    async def _get(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
    ) -> CommandMetadata | None:
        """Get metadata using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT domain, command_id, command_type, status, attempts,
                       max_attempts, msg_id, correlation_id, reply_queue,
                       last_error_type, last_error_code, last_error_msg,
                       created_at, updated_at
                FROM command_bus_command
                WHERE domain = %s AND command_id = %s
                """,
                (domain, command_id),
            )
            row = await cur.fetchone()

        if row is None:
            return None

        return CommandMetadata(
            domain=row[0],
            command_id=row[1],
            command_type=row[2],
            status=CommandStatus(row[3]),
            attempts=row[4],
            max_attempts=row[5],
            msg_id=row[6],
            correlation_id=row[7],
            reply_to=row[8] if row[8] else None,
            last_error_type=row[9],
            last_error_code=row[10],
            last_error_msg=row[11],
            created_at=row[12],
            updated_at=row[13],
        )

    async def update_status(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update command status.

        Args:
            domain: The domain
            command_id: The command ID
            status: New status
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._update_status(conn, domain, command_id, status)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._update_status(acquired_conn, domain, command_id, status)

    async def _update_status(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        status: CommandStatus,
    ) -> None:
        """Update status using an existing connection."""
        await conn.execute(
            """
            UPDATE command_bus_command
            SET status = %s, updated_at = NOW()
            WHERE domain = %s AND command_id = %s
            """,
            (status.value, domain, command_id),
        )
        logger.debug(f"Updated status for {domain}.{command_id} to {status.value}")

    async def update_msg_id(
        self,
        domain: str,
        command_id: UUID,
        msg_id: int,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update the message ID for a command.

        Args:
            domain: The domain
            command_id: The command ID
            msg_id: The PGMQ message ID
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._update_msg_id(conn, domain, command_id, msg_id)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._update_msg_id(acquired_conn, domain, command_id, msg_id)

    async def _update_msg_id(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        msg_id: int,
    ) -> None:
        """Update msg_id using an existing connection."""
        await conn.execute(
            """
            UPDATE command_bus_command
            SET msg_id = %s, updated_at = NOW()
            WHERE domain = %s AND command_id = %s
            """,
            (msg_id, domain, command_id),
        )

    async def exists(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Check if a command exists.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            True if command exists, False otherwise
        """
        if conn is not None:
            return await self._exists(conn, domain, command_id)

        async with self._pool.connection() as acquired_conn:
            return await self._exists(acquired_conn, domain, command_id)

    async def _exists(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
    ) -> bool:
        """Check existence using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM command_bus_command
                    WHERE domain = %s AND command_id = %s
                )
                """,
                (domain, command_id),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False
