"""Command Bus - main entry point for sending and managing commands."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from commandbus.exceptions import DuplicateCommandError
from commandbus.models import CommandMetadata, CommandStatus
from commandbus.pgmq.client import PgmqClient
from commandbus.repositories.audit import AuditEventType, PostgresAuditLogger
from commandbus.repositories.command import PostgresCommandRepository

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


def _make_queue_name(domain: str, suffix: str = "commands") -> str:
    """Create a queue name from domain.

    Args:
        domain: The domain name
        suffix: Queue type suffix (commands, replies)

    Returns:
        Queue name in format domain__suffix
    """
    return f"{domain}__{suffix}"


@dataclass
class SendResult:
    """Result of sending a command.

    Attributes:
        command_id: The command ID
        msg_id: The PGMQ message ID
    """

    command_id: UUID
    msg_id: int


class CommandBus:
    """Command Bus for sending and managing commands.

    The CommandBus provides the main API for:
    - Sending commands to domain queues
    - Managing command lifecycle
    - Idempotent command handling

    Example:
        pool = AsyncConnectionPool(conninfo)
        await pool.open()
        bus = CommandBus(pool)

        result = await bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"account_id": "123", "amount": 100},
        )
    """

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        default_max_attempts: int = 3,
    ) -> None:
        """Initialize the Command Bus.

        Args:
            pool: psycopg async connection pool
            default_max_attempts: Default max retry attempts for commands
        """
        self._pool = pool
        self._default_max_attempts = default_max_attempts
        self._pgmq = PgmqClient(pool)
        self._command_repo = PostgresCommandRepository(pool)
        self._audit_logger = PostgresAuditLogger(pool)

    async def send(
        self,
        domain: str,
        command_type: str,
        command_id: UUID,
        data: dict[str, Any],
        correlation_id: UUID | None = None,
        reply_to: str | None = None,
        max_attempts: int | None = None,
    ) -> SendResult:
        """Send a command to a domain queue.

        The command is stored atomically with its metadata and queued for
        processing. If a command with the same ID already exists in the domain,
        a DuplicateCommandError is raised.

        Args:
            domain: The domain to send to (e.g., "payments")
            command_type: The type of command (e.g., "DebitAccount")
            command_id: Unique identifier for this command
            data: The command payload
            correlation_id: Optional correlation ID for tracing
            reply_to: Optional reply queue name
            max_attempts: Max retry attempts (defaults to bus default)

        Returns:
            SendResult with command_id and msg_id

        Raises:
            DuplicateCommandError: If command_id already exists in this domain
        """
        queue_name = _make_queue_name(domain)
        effective_max_attempts = max_attempts or self._default_max_attempts

        async with self._pool.connection() as conn, conn.transaction():
            # Check for duplicate command
            if await self._command_repo.exists(domain, command_id, conn):
                raise DuplicateCommandError(domain, str(command_id))

            # Create the command message payload
            message = self._build_message(
                domain=domain,
                command_type=command_type,
                command_id=command_id,
                data=data,
                correlation_id=correlation_id,
                reply_to=reply_to,
            )

            # Send to PGMQ queue
            msg_id = await self._pgmq.send(queue_name, message, conn=conn)

            # Create metadata record
            now = datetime.now(UTC)
            metadata = CommandMetadata(
                domain=domain,
                command_id=command_id,
                command_type=command_type,
                status=CommandStatus.PENDING,
                attempts=0,
                max_attempts=effective_max_attempts,
                msg_id=msg_id,
                correlation_id=correlation_id,
                reply_to=reply_to,
                created_at=now,
                updated_at=now,
            )

            # Save metadata
            await self._command_repo.save(metadata, queue_name, conn)

            # Record audit event
            await self._audit_logger.log(
                domain=domain,
                command_id=command_id,
                event_type=AuditEventType.SENT,
                details={
                    "command_type": command_type,
                    "correlation_id": str(correlation_id) if correlation_id else None,
                    "reply_to": reply_to,
                    "msg_id": msg_id,
                },
                conn=conn,
            )

            logger.info(
                f"Sent command {domain}.{command_type} (command_id={command_id}, msg_id={msg_id})"
            )

            return SendResult(command_id=command_id, msg_id=msg_id)

    def _build_message(
        self,
        domain: str,
        command_type: str,
        command_id: UUID,
        data: dict[str, Any],
        correlation_id: UUID | None,
        reply_to: str | None,
    ) -> dict[str, Any]:
        """Build the message payload for PGMQ.

        Args:
            domain: The domain
            command_type: Type of command
            command_id: Command ID
            data: Command payload
            correlation_id: Correlation ID
            reply_to: Reply queue

        Returns:
            Message dictionary for PGMQ
        """
        message: dict[str, Any] = {
            "domain": domain,
            "command_type": command_type,
            "command_id": str(command_id),
            "data": data,
        }

        if correlation_id is not None:
            message["correlation_id"] = str(correlation_id)

        if reply_to is not None:
            message["reply_to"] = reply_to

        return message

    async def get_command(
        self,
        domain: str,
        command_id: UUID,
    ) -> CommandMetadata | None:
        """Get command metadata by domain and command_id.

        Args:
            domain: The domain
            command_id: The command ID

        Returns:
            CommandMetadata if found, None otherwise
        """
        return await self._command_repo.get(domain, command_id)

    async def command_exists(
        self,
        domain: str,
        command_id: UUID,
    ) -> bool:
        """Check if a command exists.

        Args:
            domain: The domain
            command_id: The command ID

        Returns:
            True if command exists
        """
        return await self._command_repo.exists(domain, command_id)
