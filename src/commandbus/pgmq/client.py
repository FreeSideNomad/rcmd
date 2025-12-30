"""PGMQ client wrapper for Command Bus."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


@dataclass
class PgmqMessage:
    """A message from a PGMQ queue.

    Attributes:
        msg_id: Unique message ID
        read_count: Number of times message has been read
        enqueued_at: When the message was enqueued
        vt: Visibility timeout timestamp
        message: The message payload
    """

    msg_id: int
    read_count: int
    enqueued_at: str
    vt: str
    message: dict[str, Any]


class PgmqClient:
    """Client for interacting with PGMQ queues.

    Wraps PGMQ SQL functions for queue operations.
    """

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        """Initialize the PGMQ client.

        Args:
            pool: psycopg async connection pool
        """
        self._pool = pool

    async def create_queue(self, queue_name: str) -> None:
        """Create a queue if it doesn't exist.

        Args:
            queue_name: Name of the queue to create
        """
        async with self._pool.connection() as conn:
            await self._create_queue(conn, queue_name)

    async def _create_queue(
        self, conn: AsyncConnection[Any], queue_name: str
    ) -> None:
        """Create a queue using an existing connection.

        Args:
            conn: Database connection
            queue_name: Name of the queue to create
        """
        await conn.execute("SELECT pgmq.create(%s)", (queue_name,))
        logger.debug(f"Created queue: {queue_name}")

    async def send(
        self,
        queue_name: str,
        message: dict[str, Any],
        delay: int = 0,
        conn: AsyncConnection[Any] | None = None,
    ) -> int:
        """Send a message to a queue.

        Args:
            queue_name: Name of the queue
            message: Message payload (will be JSON serialized)
            delay: Delay in seconds before message becomes visible
            conn: Optional connection (for transaction support)

        Returns:
            Message ID assigned by PGMQ
        """
        if conn is not None:
            return await self._send(conn, queue_name, message, delay)

        async with self._pool.connection() as acquired_conn:
            return await self._send(acquired_conn, queue_name, message, delay)

    async def _send(
        self,
        conn: AsyncConnection[Any],
        queue_name: str,
        message: dict[str, Any],
        delay: int,
    ) -> int:
        """Send a message using an existing connection.

        Args:
            conn: Database connection
            queue_name: Name of the queue
            message: Message payload
            delay: Delay in seconds

        Returns:
            Message ID
        """
        msg_json = json.dumps(message)
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT pgmq.send(%s, %s::jsonb, %s)",
                (queue_name, msg_json, delay),
            )
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError(f"Failed to send message to queue {queue_name}")
            result = row[0]
        logger.debug(f"Sent message to {queue_name}: msg_id={result}")
        return int(result)

    async def read(
        self,
        queue_name: str,
        visibility_timeout: int = 30,
        batch_size: int = 1,
        conn: AsyncConnection[Any] | None = None,
    ) -> list[PgmqMessage]:
        """Read messages from a queue.

        Args:
            queue_name: Name of the queue
            visibility_timeout: Seconds before message becomes visible again
            batch_size: Maximum number of messages to read
            conn: Optional connection (for transaction support)

        Returns:
            List of messages (may be empty)
        """
        if conn is not None:
            return await self._read(conn, queue_name, visibility_timeout, batch_size)

        async with self._pool.connection() as acquired_conn:
            return await self._read(
                acquired_conn, queue_name, visibility_timeout, batch_size
            )

    async def _read(
        self,
        conn: AsyncConnection[Any],
        queue_name: str,
        visibility_timeout: int,
        batch_size: int,
    ) -> list[PgmqMessage]:
        """Read messages using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM pgmq.read(%s, %s, %s)",
                (queue_name, visibility_timeout, batch_size),
            )
            rows = await cur.fetchall()
            # Column order: msg_id, read_ct, enqueued_at, vt, message
            return [
                PgmqMessage(
                    msg_id=row[0],
                    read_count=row[1],
                    enqueued_at=str(row[2]),
                    vt=str(row[3]),
                    message=json.loads(row[4])
                    if isinstance(row[4], str)
                    else row[4],
                )
                for row in rows
            ]

    async def delete(
        self,
        queue_name: str,
        msg_id: int,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Delete a message from a queue.

        Args:
            queue_name: Name of the queue
            msg_id: Message ID to delete
            conn: Optional connection (for transaction support)

        Returns:
            True if message was deleted, False if not found
        """
        if conn is not None:
            return await self._delete(conn, queue_name, msg_id)

        async with self._pool.connection() as acquired_conn:
            return await self._delete(acquired_conn, queue_name, msg_id)

    async def _delete(
        self,
        conn: AsyncConnection[Any],
        queue_name: str,
        msg_id: int,
    ) -> bool:
        """Delete a message using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT pgmq.delete(%s, %s)",
                (queue_name, msg_id),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False

    async def archive(
        self,
        queue_name: str,
        msg_id: int,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Archive a message (move to archive table).

        Args:
            queue_name: Name of the queue
            msg_id: Message ID to archive
            conn: Optional connection (for transaction support)

        Returns:
            True if message was archived
        """
        if conn is not None:
            return await self._archive(conn, queue_name, msg_id)

        async with self._pool.connection() as acquired_conn:
            return await self._archive(acquired_conn, queue_name, msg_id)

    async def _archive(
        self,
        conn: AsyncConnection[Any],
        queue_name: str,
        msg_id: int,
    ) -> bool:
        """Archive a message using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT pgmq.archive(%s, %s)",
                (queue_name, msg_id),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False

    async def set_vt(
        self,
        queue_name: str,
        msg_id: int,
        visibility_timeout: int,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Set visibility timeout for a message.

        Args:
            queue_name: Name of the queue
            msg_id: Message ID
            visibility_timeout: New visibility timeout in seconds
            conn: Optional connection (for transaction support)

        Returns:
            True if timeout was set
        """
        if conn is not None:
            return await self._set_vt(conn, queue_name, msg_id, visibility_timeout)

        async with self._pool.connection() as acquired_conn:
            return await self._set_vt(
                acquired_conn, queue_name, msg_id, visibility_timeout
            )

    async def _set_vt(
        self,
        conn: AsyncConnection[Any],
        queue_name: str,
        msg_id: int,
        visibility_timeout: int,
    ) -> bool:
        """Set visibility timeout using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM pgmq.set_vt(%s, %s, %s)",
                (queue_name, msg_id, visibility_timeout),
            )
            row = await cur.fetchone()
            return row is not None
