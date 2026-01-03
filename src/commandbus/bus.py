"""Command Bus - main entry point for sending and managing commands."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from commandbus.exceptions import DuplicateCommandError
from commandbus.models import (
    AuditEvent,
    BatchSendResult,
    CommandMetadata,
    CommandStatus,
    SendRequest,
    SendResult,
)
from commandbus.pgmq.client import PgmqClient
from commandbus.repositories.audit import AuditEventType, PostgresAuditLogger
from commandbus.repositories.command import PostgresCommandRepository

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

# Default chunk size for batch operations
DEFAULT_BATCH_CHUNK_SIZE = 1_000


def _make_queue_name(domain: str, suffix: str = "commands") -> str:
    """Create a queue name from domain.

    Args:
        domain: The domain name
        suffix: Queue type suffix (commands, replies)

    Returns:
        Queue name in format domain__suffix
    """
    return f"{domain}__{suffix}"


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    """Split a list into chunks of specified size.

    Args:
        items: List to split
        size: Maximum chunk size

    Returns:
        List of chunks
    """
    return [items[i : i + size] for i in range(0, len(items), size)]


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
        effective_correlation_id = correlation_id if correlation_id is not None else uuid4()

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
                correlation_id=effective_correlation_id,
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
                correlation_id=effective_correlation_id,
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
                    "correlation_id": str(effective_correlation_id),
                    "reply_to": reply_to,
                    "msg_id": msg_id,
                },
                conn=conn,
            )

            logger.info(
                f"Sent command {domain}.{command_type} (command_id={command_id}, msg_id={msg_id})"
            )

            return SendResult(command_id=command_id, msg_id=msg_id)

    async def send_batch(
        self,
        requests: list[SendRequest],
        chunk_size: int = DEFAULT_BATCH_CHUNK_SIZE,
    ) -> BatchSendResult:
        """Send multiple commands efficiently in batched transactions.

        Each chunk is processed in a single transaction with one NOTIFY at the end.
        This is significantly faster than calling send() repeatedly.

        Args:
            requests: List of SendRequest objects
            chunk_size: Max commands per transaction (default 10,000)

        Returns:
            BatchSendResult with all results and stats

        Raises:
            DuplicateCommandError: If any command_id already exists

        Example:
            requests = [
                SendRequest(
                    domain="payments",
                    command_type="DebitAccount",
                    command_id=uuid4(),
                    data={"amount": 100},
                )
                for _ in range(1000)
            ]
            result = await bus.send_batch(requests)
            print(f"Sent {result.total_commands} in {result.chunks_processed} chunks")
        """
        if not requests:
            return BatchSendResult(results=[], chunks_processed=0, total_commands=0)

        all_results: list[SendResult] = []
        chunks_processed = 0

        # Group requests by domain for efficient processing
        domain_chunks = _chunked(requests, chunk_size)

        for chunk in domain_chunks:
            chunk_results = await self._send_batch_chunk(chunk)
            all_results.extend(chunk_results)
            chunks_processed += 1

        logger.info(f"Sent {len(all_results)} commands in {chunks_processed} chunks")

        return BatchSendResult(
            results=all_results,
            chunks_processed=chunks_processed,
            total_commands=len(all_results),
        )

    async def _send_batch_chunk(
        self,
        requests: list[SendRequest],
    ) -> list[SendResult]:
        """Process a single chunk of send requests in one transaction.

        Args:
            requests: List of requests to process

        Returns:
            List of SendResult for each command
        """
        if not requests:
            return []

        # All requests in a chunk must have the same domain for PGMQ batch
        # Group by domain
        by_domain: dict[str, list[SendRequest]] = {}
        for req in requests:
            by_domain.setdefault(req.domain, []).append(req)

        all_results: list[SendResult] = []
        now = datetime.now(UTC)

        async with self._pool.connection() as conn, conn.transaction():
            for domain, domain_requests in by_domain.items():
                queue_name = _make_queue_name(domain)

                # Check for duplicates
                command_ids = [r.command_id for r in domain_requests]
                existing = await self._command_repo.exists_batch(domain, command_ids, conn)
                if existing:
                    # Find first duplicate for error message
                    first_dup = next(r for r in domain_requests if r.command_id in existing)
                    raise DuplicateCommandError(domain, str(first_dup.command_id))

                # Build all messages
                messages: list[dict[str, Any]] = []
                metadata_list: list[CommandMetadata] = []
                audit_events: list[tuple[str, UUID, AuditEventType, dict[str, Any] | None]] = []

                for req in domain_requests:
                    effective_max_attempts = req.max_attempts or self._default_max_attempts
                    effective_correlation_id = (
                        req.correlation_id if req.correlation_id is not None else uuid4()
                    )

                    message = self._build_message(
                        domain=req.domain,
                        command_type=req.command_type,
                        command_id=req.command_id,
                        data=req.data,
                        correlation_id=effective_correlation_id,
                        reply_to=req.reply_to,
                    )
                    messages.append(message)

                # Batch send to PGMQ (no NOTIFY yet)
                msg_ids = await self._pgmq.send_batch(queue_name, messages, conn=conn)

                # Build metadata and audit events with msg_ids
                for i, req in enumerate(domain_requests):
                    msg_id = msg_ids[i]
                    effective_max_attempts = req.max_attempts or self._default_max_attempts
                    effective_correlation_id = (
                        req.correlation_id if req.correlation_id is not None else uuid4()
                    )

                    metadata = CommandMetadata(
                        domain=req.domain,
                        command_id=req.command_id,
                        command_type=req.command_type,
                        status=CommandStatus.PENDING,
                        attempts=0,
                        max_attempts=effective_max_attempts,
                        msg_id=msg_id,
                        correlation_id=effective_correlation_id,
                        reply_to=req.reply_to,
                        created_at=now,
                        updated_at=now,
                    )
                    metadata_list.append(metadata)

                    audit_events.append(
                        (
                            req.domain,
                            req.command_id,
                            AuditEventType.SENT,
                            {
                                "command_type": req.command_type,
                                "correlation_id": str(effective_correlation_id),
                                "reply_to": req.reply_to,
                                "msg_id": msg_id,
                            },
                        )
                    )

                    all_results.append(SendResult(command_id=req.command_id, msg_id=msg_id))

                # Batch save metadata
                await self._command_repo.save_batch(metadata_list, queue_name, conn)

                # Batch log audit events
                await self._audit_logger.log_batch(audit_events, conn)

                # Send NOTIFY for this domain (once per chunk per domain)
                await self._pgmq.notify(queue_name, conn)

        return all_results

    def _build_message(
        self,
        domain: str,
        command_type: str,
        command_id: UUID,
        data: dict[str, Any],
        correlation_id: UUID,
        reply_to: str | None,
    ) -> dict[str, Any]:
        """Build the message payload for PGMQ.

        Args:
            domain: The domain
            command_type: Type of command
            command_id: Command ID
            data: Command payload
            correlation_id: Correlation ID (always present, auto-generated if not provided)
            reply_to: Reply queue

        Returns:
            Message dictionary for PGMQ
        """
        message: dict[str, Any] = {
            "domain": domain,
            "command_type": command_type,
            "command_id": str(command_id),
            "correlation_id": str(correlation_id),
            "data": data,
        }

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

    async def get_audit_trail(
        self,
        command_id: UUID,
        domain: str | None = None,
    ) -> list[AuditEvent]:
        """Get the audit trail for a command.

        Returns all audit events for a command in chronological order.
        Events include: SENT, RECEIVED, COMPLETED, FAILED, RETRY_SCHEDULED,
        RETRY_EXHAUSTED, MOVED_TO_TSQ, OPERATOR_RETRY, OPERATOR_CANCEL,
        OPERATOR_COMPLETE.

        Args:
            command_id: The command ID
            domain: Optional domain filter

        Returns:
            List of AuditEvent in chronological order (empty if not found)
        """
        return await self._audit_logger.get_events(command_id, domain)

    async def query_commands(
        self,
        status: CommandStatus | None = None,
        domain: str | None = None,
        command_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CommandMetadata]:
        """Query commands with filters.

        Returns commands matching the specified filters, ordered by created_at
        descending (most recent first).

        Args:
            status: Filter by command status
            domain: Filter by domain
            command_type: Filter by command type
            created_after: Filter by created_at >= this datetime
            created_before: Filter by created_at <= this datetime
            limit: Maximum number of results (default 100)
            offset: Number of results to skip for pagination (default 0)

        Returns:
            List of CommandMetadata matching the filters

        Example:
            # Get all pending commands in payments domain
            pending = await bus.query_commands(
                status=CommandStatus.PENDING,
                domain="payments",
            )

            # Paginate through results
            page1 = await bus.query_commands(limit=50, offset=0)
            page2 = await bus.query_commands(limit=50, offset=50)
        """
        return await self._command_repo.query(
            status=status,
            domain=domain,
            command_type=command_type,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset,
        )
