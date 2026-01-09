"""Native synchronous PGMQ client for sync workers.

This module provides a synchronous PGMQ client using psycopg3's
thread-safe ConnectionPool for native sync operations without
async wrapper overhead.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from commandbus._core.pgmq_sql import PgmqMessage, PgmqParams, PgmqParsers, PgmqSQL

if TYPE_CHECKING:
    from psycopg import Connection
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


class SyncPgmqClient:
    """Synchronous PGMQ client using native sync connections.

    This client provides sync methods for PGMQ operations, using
    psycopg3's thread-safe ConnectionPool. Each method accepts an
    optional connection parameter for transaction support.

    Example:
        pool = ConnectionPool(conninfo=DATABASE_URL)
        client = SyncPgmqClient(pool)

        # Send a message
        msg_id = client.send("my_queue", {"data": "value"})

        # Read messages
        messages = client.read("my_queue", vt=30, limit=10)

        # Read with polling (blocks until messages available)
        messages = client.read_with_poll("my_queue", vt=30, limit=10, max_wait=60)

        # Delete a message
        client.delete("my_queue", msg_id)
    """

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize the sync PGMQ client.

        Args:
            pool: psycopg sync connection pool
        """
        self._pool = pool

    def create_queue(
        self,
        queue_name: str,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Create a queue if it doesn't exist.

        Args:
            queue_name: Name of the queue to create
            conn: Optional connection (for transaction support)
        """
        sql = PgmqSQL.CREATE_QUEUE
        params = PgmqParams.create_queue(queue_name)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Created queue: %s", queue_name)

    def send(
        self,
        queue_name: str,
        message: dict[str, Any],
        delay: int = 0,
        conn: Connection[Any] | None = None,
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
        sql = PgmqSQL.SEND
        params = PgmqParams.send(queue_name, message, delay)

        if conn is not None:
            result = self._send_with_conn(conn, sql, params, queue_name)
        else:
            with self._pool.connection() as c:
                result = self._send_with_conn(c, sql, params, queue_name)

        logger.debug("Sent message to %s: msg_id=%d", queue_name, result)
        return result

    def _send_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, str, int],
        queue_name: str,
    ) -> int:
        """Send a message using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"Failed to send message to queue {queue_name}")

            # Send notification for workers using LISTEN/NOTIFY
            notify_sql = PgmqSQL.notify_sql(queue_name)
            cur.execute(notify_sql)
            logger.debug("Notified channel %s", PgmqSQL.notify_channel(queue_name))

            return int(row[0])

    def send_batch(
        self,
        queue_name: str,
        messages: list[dict[str, Any]],
        delay: int = 0,
        conn: Connection[Any] | None = None,
    ) -> list[int]:
        """Send multiple messages to a queue in a single operation.

        Uses PGMQ's native send_batch() for optimal performance.
        Does NOT send NOTIFY - caller is responsible for notification.

        Args:
            queue_name: Name of the queue
            messages: List of message payloads (will be JSON serialized)
            delay: Delay in seconds before messages become visible
            conn: Optional connection (for transaction support)

        Returns:
            List of message IDs assigned by PGMQ
        """
        if not messages:
            return []

        sql = PgmqSQL.SEND_BATCH
        params = PgmqParams.send_batch(queue_name, messages, delay)

        if conn is not None:
            result = self._send_batch_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                result = self._send_batch_with_conn(c, sql, params)

        logger.debug("Sent %d messages to %s", len(result), queue_name)
        return result

    def _send_batch_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, list[str], int],
    ) -> list[int]:
        """Send batch using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [int(row[0]) for row in rows]

    def notify(
        self,
        queue_name: str,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Send a NOTIFY signal for a queue.

        Used after batch operations to wake up workers.

        Args:
            queue_name: Name of the queue
            conn: Optional connection
        """
        notify_sql = PgmqSQL.notify_sql(queue_name)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(notify_sql)
        else:
            with self._pool.connection() as c, c.cursor() as cur:
                cur.execute(notify_sql)

        logger.debug("Notified channel %s", PgmqSQL.notify_channel(queue_name))

    def read(
        self,
        queue_name: str,
        visibility_timeout: int = 30,
        batch_size: int = 1,
        conn: Connection[Any] | None = None,
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
        sql = PgmqSQL.READ
        params = PgmqParams.read(queue_name, visibility_timeout, batch_size)

        if conn is not None:
            return self._read_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._read_with_conn(c, sql, params)

    def _read_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, int, int],
    ) -> list[PgmqMessage]:
        """Read messages using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return PgmqParsers.from_rows(rows)

    def read_with_poll(
        self,
        queue_name: str,
        visibility_timeout: int = 30,
        batch_size: int = 1,
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
    ) -> list[PgmqMessage]:
        """Read messages with polling until available or timeout.

        This method blocks until messages are available or max_wait is exceeded.
        Useful for workers that need to wait for messages.

        Args:
            queue_name: Name of the queue
            visibility_timeout: Seconds before message becomes visible again
            batch_size: Maximum number of messages to read
            poll_interval: Seconds between poll attempts
            max_wait: Maximum seconds to wait for messages

        Returns:
            List of messages (may be empty if max_wait exceeded)
        """
        start_time = time.monotonic()

        while True:
            messages = self.read(queue_name, visibility_timeout, batch_size)
            if messages:
                return messages

            elapsed = time.monotonic() - start_time
            if elapsed >= max_wait:
                return []

            # Wait before next poll
            remaining = max_wait - elapsed
            wait_time = min(poll_interval, remaining)
            if wait_time > 0:
                time.sleep(wait_time)

    def delete(
        self,
        queue_name: str,
        msg_id: int,
        conn: Connection[Any] | None = None,
    ) -> bool:
        """Delete a message from a queue.

        Args:
            queue_name: Name of the queue
            msg_id: Message ID to delete
            conn: Optional connection (for transaction support)

        Returns:
            True if message was deleted, False if not found
        """
        sql = PgmqSQL.DELETE
        params = PgmqParams.delete(queue_name, msg_id)

        if conn is not None:
            return self._delete_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._delete_with_conn(c, sql, params)

    def _delete_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, int],
    ) -> bool:
        """Delete a message using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return bool(row[0]) if row else False

    def archive(
        self,
        queue_name: str,
        msg_id: int,
        conn: Connection[Any] | None = None,
    ) -> bool:
        """Archive a message (move to archive table).

        Args:
            queue_name: Name of the queue
            msg_id: Message ID to archive
            conn: Optional connection (for transaction support)

        Returns:
            True if message was archived
        """
        sql = PgmqSQL.ARCHIVE
        params = PgmqParams.archive(queue_name, msg_id)

        if conn is not None:
            return self._archive_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._archive_with_conn(c, sql, params)

    def _archive_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, int],
    ) -> bool:
        """Archive a message using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return bool(row[0]) if row else False

    def set_vt(
        self,
        queue_name: str,
        msg_id: int,
        visibility_timeout: int,
        conn: Connection[Any] | None = None,
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
        sql = PgmqSQL.SET_VT
        params = PgmqParams.set_vt(queue_name, msg_id, visibility_timeout)

        if conn is not None:
            return self._set_vt_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._set_vt_with_conn(c, sql, params)

    def _set_vt_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, int, int],
    ) -> bool:
        """Set visibility timeout using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row is not None
