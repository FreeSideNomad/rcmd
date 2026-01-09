"""SQL constants, parameter builders, and row parsers for PGMQ operations.

This module extracts shared SQL logic for both async and sync implementations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Channel name prefix for pg_notify - shared between implementations
PGMQ_NOTIFY_CHANNEL = "pgmq_notify"


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


class PgmqSQL:
    """SQL constants for PGMQ operations."""

    CREATE_QUEUE = "SELECT pgmq.create(%s)"

    SEND = "SELECT pgmq.send(%s, %s::jsonb, %s)"

    SEND_BATCH = "SELECT * FROM pgmq.send_batch(%s, %s::jsonb[], %s)"

    READ = "SELECT * FROM pgmq.read(%s, %s, %s)"

    DELETE = "SELECT pgmq.delete(%s, %s)"

    ARCHIVE = "SELECT pgmq.archive(%s, %s)"

    SET_VT = "SELECT * FROM pgmq.set_vt(%s, %s, %s)"

    @staticmethod
    def notify_channel(queue_name: str) -> str:
        """Get the NOTIFY channel name for a queue.

        Args:
            queue_name: Name of the queue

        Returns:
            Channel name in format 'pgmq_notify_{queue_name}'
        """
        return f"{PGMQ_NOTIFY_CHANNEL}_{queue_name}"

    @staticmethod
    def notify_sql(queue_name: str) -> str:
        """Get the NOTIFY SQL for a queue.

        Args:
            queue_name: Name of the queue

        Returns:
            SQL string like 'NOTIFY pgmq_notify_myqueue'
        """
        channel = PgmqSQL.notify_channel(queue_name)
        return f"NOTIFY {channel}"


class PgmqParams:
    """Static methods for building SQL parameter tuples."""

    @staticmethod
    def create_queue(queue_name: str) -> tuple[str]:
        """Build parameters for CREATE_QUEUE call."""
        return (queue_name,)

    @staticmethod
    def send(queue_name: str, message: dict[str, Any], delay: int = 0) -> tuple[str, str, int]:
        """Build parameters for SEND call.

        Args:
            queue_name: Name of the queue
            message: Message payload (will be JSON serialized)
            delay: Delay in seconds before message becomes visible

        Returns:
            Tuple of (queue_name, json_message, delay)
        """
        msg_json = json.dumps(message)
        return (queue_name, msg_json, delay)

    @staticmethod
    def send_batch(
        queue_name: str, messages: list[dict[str, Any]], delay: int = 0
    ) -> tuple[str, list[str], int]:
        """Build parameters for SEND_BATCH call.

        Args:
            queue_name: Name of the queue
            messages: List of message payloads (will be JSON serialized)
            delay: Delay in seconds before messages become visible

        Returns:
            Tuple of (queue_name, json_messages_list, delay)
        """
        msgs_json = [json.dumps(m) for m in messages]
        return (queue_name, msgs_json, delay)

    @staticmethod
    def read(
        queue_name: str, visibility_timeout: int = 30, batch_size: int = 1
    ) -> tuple[str, int, int]:
        """Build parameters for READ call.

        Args:
            queue_name: Name of the queue
            visibility_timeout: Seconds before message becomes visible again
            batch_size: Maximum number of messages to read

        Returns:
            Tuple of (queue_name, visibility_timeout, batch_size)
        """
        return (queue_name, visibility_timeout, batch_size)

    @staticmethod
    def delete(queue_name: str, msg_id: int) -> tuple[str, int]:
        """Build parameters for DELETE call."""
        return (queue_name, msg_id)

    @staticmethod
    def archive(queue_name: str, msg_id: int) -> tuple[str, int]:
        """Build parameters for ARCHIVE call."""
        return (queue_name, msg_id)

    @staticmethod
    def set_vt(queue_name: str, msg_id: int, visibility_timeout: int) -> tuple[str, int, int]:
        """Build parameters for SET_VT call."""
        return (queue_name, msg_id, visibility_timeout)


class PgmqParsers:
    """Static methods for parsing database rows to PgmqMessage."""

    @staticmethod
    def from_row(row: tuple[Any, ...]) -> PgmqMessage:
        """Parse a database row to PgmqMessage.

        Expected column order (5 fields):
            msg_id, read_ct, enqueued_at, vt, message

        Args:
            row: Database row tuple

        Returns:
            PgmqMessage instance
        """
        message = row[4]
        if isinstance(message, str):
            message = json.loads(message)

        return PgmqMessage(
            msg_id=row[0],
            read_count=row[1],
            enqueued_at=str(row[2]),
            vt=str(row[3]),
            message=message,
        )

    @staticmethod
    def from_rows(rows: list[tuple[Any, ...]]) -> list[PgmqMessage]:
        """Parse multiple database rows to PgmqMessage list.

        Args:
            rows: List of database row tuples

        Returns:
            List of PgmqMessage instances
        """
        return [PgmqParsers.from_row(row) for row in rows]
