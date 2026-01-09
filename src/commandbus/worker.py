"""Worker for receiving and processing commands from queues."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from commandbus.batch import invoke_batch_callback
from commandbus.exceptions import PermanentCommandError, TransientCommandError
from commandbus.models import (
    Command,
    CommandMetadata,
    CommandStatus,
    HandlerContext,
    ReplyOutcome,
)
from commandbus.pgmq.client import PGMQ_NOTIFY_CHANNEL, PgmqClient
from commandbus.policies import DEFAULT_RETRY_POLICY, RetryPolicy
from commandbus.repositories.audit import PostgresAuditLogger
from commandbus.repositories.batch import PostgresBatchRepository
from commandbus.repositories.command import PostgresCommandRepository

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from commandbus.handler import HandlerRegistry

logger = logging.getLogger(__name__)


def _make_queue_name(domain: str, suffix: str = "commands") -> str:
    """Create a queue name from domain."""
    return f"{domain}__{suffix}"


@dataclass
class ReceivedCommand:
    """A command received from the queue, ready for processing.

    Attributes:
        command: The command to process
        context: Handler context with attempt info
        msg_id: PGMQ message ID for acknowledgment
        metadata: Command metadata from storage
    """

    command: Command
    context: HandlerContext
    msg_id: int
    metadata: CommandMetadata


class Worker:
    """Worker for receiving and processing commands.

    The worker reads commands from a domain queue, handles visibility
    timeout for at-least-once delivery, and manages command lifecycle.

    Example:
        pool = AsyncConnectionPool(conninfo)
        await pool.open()
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)
        await worker.run(concurrency=5)  # Process up to 5 commands concurrently
    """

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        domain: str,
        registry: HandlerRegistry | None = None,
        visibility_timeout: int = 30,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            pool: psycopg async connection pool
            domain: The domain to process commands for
            registry: Handler registry for dispatching commands
            visibility_timeout: Default visibility timeout in seconds
            retry_policy: Policy for retry behavior and backoff
        """
        self._pool = pool
        self._domain = domain
        self._registry = registry
        self._visibility_timeout = visibility_timeout
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._queue_name = _make_queue_name(domain)
        self._pgmq = PgmqClient(pool)
        self._command_repo = PostgresCommandRepository(pool)
        self._batch_repo = PostgresBatchRepository(pool)
        self._audit_logger = PostgresAuditLogger(pool)
        self._running = False
        self._stop_event: asyncio.Event | None = None
        self._in_flight: set[asyncio.Task[None]] = set()

    @property
    def domain(self) -> str:
        """Get the domain this worker processes."""
        return self._domain

    @property
    def queue_name(self) -> str:
        """Get the queue name this worker reads from."""
        return self._queue_name

    async def receive(
        self,
        batch_size: int = 1,
        visibility_timeout: int | None = None,
    ) -> list[ReceivedCommand]:
        """Receive commands from the queue.

        Reads messages from the queue and returns them for processing.
        Messages become invisible to other workers for the visibility
        timeout period. If not acknowledged, they reappear for retry.

        Commands in terminal states (COMPLETED, CANCELED) are automatically
        archived and skipped.

        Uses a single shared connection for all DB operations to reduce
        connection pool pressure and improve throughput.

        Args:
            batch_size: Maximum number of commands to receive
            visibility_timeout: Override default visibility timeout

        Returns:
            List of received commands (may be empty)
        """
        vt = visibility_timeout or self._visibility_timeout
        received: list[ReceivedCommand] = []

        # Use a single connection for all receive operations
        # This reduces pool pressure: 3 connections per message → 1 shared
        async with self._pool.connection() as conn:
            messages = await self._pgmq.read(
                self._queue_name,
                visibility_timeout=vt,
                batch_size=batch_size,
                conn=conn,
            )

            for msg in messages:
                try:
                    result = await self._process_message(msg.msg_id, msg.message, conn)
                    if result is not None:
                        received.append(result)
                except Exception:
                    logger.exception(f"Error processing message {msg.msg_id}")
                    # Message will reappear after visibility timeout

        return received

    async def _process_message(
        self,
        msg_id: int,
        message: dict[str, Any],
        conn: Any = None,
    ) -> ReceivedCommand | None:
        """Process a single message from the queue.

        Args:
            msg_id: PGMQ message ID
            message: Message payload
            conn: Shared database connection (optional)

        Returns:
            ReceivedCommand if ready for processing, None if skipped
        """
        domain = message.get("domain", self._domain)
        command_id_str = message.get("command_id")
        if not command_id_str:
            logger.warning(f"Message {msg_id} missing command_id, archiving")
            await self._pgmq.archive(self._queue_name, msg_id, conn)
            return None

        command_id = UUID(command_id_str)

        # Use stored procedure: atomically get metadata + increment attempts +
        # update status + insert audit event - ALL IN ONE DB CALL
        result = await self._command_repo.sp_receive_command(
            domain, command_id, msg_id=msg_id, conn=conn
        )

        if result is None:
            logger.warning(f"No metadata for command {command_id} in domain {domain}, archiving")
            await self._pgmq.archive(self._queue_name, msg_id, conn)
            return None

        metadata, attempts = result

        # Build command object
        correlation_id_str = message.get("correlation_id")
        command = Command(
            domain=domain,
            command_type=message.get("command_type", metadata.command_type),
            command_id=command_id,
            data=message.get("data", {}),
            correlation_id=UUID(correlation_id_str) if correlation_id_str else None,
            reply_to=message.get("reply_to"),
            created_at=metadata.created_at,
        )

        # Build context
        context = HandlerContext(
            command=command,
            attempt=attempts,
            max_attempts=metadata.max_attempts,
            msg_id=msg_id,
        )

        logger.info(
            f"Received command {domain}.{command.command_type} "
            f"(command_id={command_id}, attempt={attempts}/{metadata.max_attempts})"
        )

        # Note: Batch start (PENDING -> IN_PROGRESS) is handled inside sp_receive_command

        return ReceivedCommand(
            command=command,
            context=context,
            msg_id=msg_id,
            metadata=metadata,
        )

    async def complete(
        self,
        received: ReceivedCommand,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Complete a command successfully.

        Deletes the message from the queue, updates status to COMPLETED,
        sends a reply if configured, and records an audit event.
        All operations are performed atomically in a single transaction.

        Args:
            received: The received command to complete
            result: Optional result data to include in the reply
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain

        async with self._pool.connection() as conn, conn.transaction():
            # Delete message from queue
            await self._pgmq.delete(self._queue_name, received.msg_id, conn)

            # Use stored procedure: update status + insert audit + batch counter in ONE DB CALL
            # Returns is_batch_complete for callback triggering
            is_batch_complete = await self._command_repo.sp_finish_command(
                domain,
                command_id,
                CommandStatus.COMPLETED,
                event_type="COMPLETED",
                details={
                    "msg_id": received.msg_id,
                    "reply_to": command.reply_to,
                    "has_result": result is not None,
                },
                batch_id=received.metadata.batch_id,
                conn=conn,
            )

            # Send reply if reply_to is configured
            if command.reply_to:
                reply_message = {
                    "command_id": str(command_id),
                    "correlation_id": str(command.correlation_id)
                    if command.correlation_id
                    else None,
                    "outcome": ReplyOutcome.SUCCESS.value,
                    "result": result,
                }
                await self._pgmq.send(command.reply_to, reply_message, conn=conn)

        logger.info(f"Completed command {domain}.{command.command_type} (command_id={command_id})")

        # Invoke batch completion callback (S043) - outside transaction
        if is_batch_complete and received.metadata.batch_id is not None:
            await invoke_batch_callback(domain, received.metadata.batch_id, self._batch_repo)

    async def fail(
        self,
        received: ReceivedCommand,
        error: TransientCommandError | Exception,
        is_transient: bool = True,
    ) -> None:
        """Record a command failure and schedule retry if applicable.

        For transient errors, applies backoff and leaves the message to expire.
        If retries are exhausted, moves the command to the troubleshooting queue.
        For permanent errors, this method does NOT handle them - use fail_permanent().

        All operations are performed atomically in a single transaction with
        shared connection for consistency and reduced pool pressure.

        Args:
            received: The received command that failed
            error: The error that occurred
            is_transient: Whether this is a transient (retryable) error
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain
        attempt = received.context.attempt

        # Extract error details
        if isinstance(error, TransientCommandError):
            error_type = "TRANSIENT"
            error_code = error.code
            error_msg = error.error_message
        elif isinstance(error, PermanentCommandError):
            error_type = "PERMANENT"
            error_code = error.code
            error_msg = error.error_message
        else:
            # Unknown exception treated as transient
            error_type = "TRANSIENT"
            error_code = type(error).__name__
            error_msg = str(error)

        # Check if retries are exhausted for transient errors
        if is_transient and not self._retry_policy.should_retry(attempt):
            await self._fail_exhausted(received, error_type, error_code, error_msg)
            return

        # Use shared connection and transaction for fail operations
        async with self._pool.connection() as conn, conn.transaction():
            # Use stored procedure: update error + insert audit in ONE DB CALL
            await self._command_repo.sp_fail_command(
                domain,
                command_id,
                error_type,
                error_code,
                error_msg,
                attempt,
                received.metadata.max_attempts,
                received.msg_id,
                conn=conn,
            )

            # Apply backoff by extending visibility timeout
            if is_transient:
                backoff = self._retry_policy.get_backoff(attempt)
                await self._pgmq.set_vt(self._queue_name, received.msg_id, backoff, conn)

        if is_transient:
            logger.info(
                f"Transient failure for {domain}.{command.command_type} "
                f"(command_id={command_id}, attempt={attempt}, backoff={backoff}s): "
                f"[{error_code}] {error_msg}"
            )
        else:
            logger.warning(
                f"Failure for {domain}.{command.command_type} "
                f"(command_id={command_id}, attempt={attempt}): "
                f"[{error_code}] {error_msg}"
            )

    async def fail_permanent(
        self,
        received: ReceivedCommand,
        error: PermanentCommandError,
    ) -> None:
        """Handle a permanent failure by moving command to troubleshooting queue.

        Archives the message, updates status to IN_TROUBLESHOOTING_QUEUE,
        stores error details, and records an audit event.
        Uses finish_command() to combine status + error update into one query.

        Args:
            received: The received command that failed
            error: The permanent error that occurred
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain

        async with self._pool.connection() as conn, conn.transaction():
            # Archive message (not delete - keeps history)
            await self._pgmq.archive(self._queue_name, received.msg_id, conn)

            # Use stored procedure: update status + error + audit + batch counter in ONE DB CALL
            # Note: Moving to TSQ never completes a batch (is_batch_complete always False)
            await self._command_repo.sp_finish_command(
                domain,
                command_id,
                CommandStatus.IN_TROUBLESHOOTING_QUEUE,
                event_type="MOVED_TO_TSQ",
                error_type="PERMANENT",
                error_code=error.code,
                error_msg=error.error_message,
                details={
                    "msg_id": received.msg_id,
                    "attempt": received.context.attempt,
                    "error_code": error.code,
                    "error_msg": error.error_message,
                    "error_details": error.details,
                },
                batch_id=received.metadata.batch_id,
                conn=conn,
            )

        logger.warning(
            f"Permanent failure for {domain}.{command.command_type} "
            f"(command_id={command_id}), moved to troubleshooting queue: "
            f"[{error.code}] {error.error_message}"
        )

    async def _fail_exhausted(
        self,
        received: ReceivedCommand,
        error_type: str,
        error_code: str,
        error_msg: str,
    ) -> None:
        """Handle retry exhaustion by moving command to troubleshooting queue.

        Called when a transient error occurs but max_attempts has been reached.
        Archives the message, updates status to IN_TROUBLESHOOTING_QUEUE,
        stores error details, and records an audit event with reason "EXHAUSTED".
        Uses finish_command() to combine status + error update into one query.

        Args:
            received: The received command that exhausted retries
            error_type: Type of the error (e.g., "TRANSIENT")
            error_code: Error code from the exception
            error_msg: Error message from the exception
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain
        attempt = received.context.attempt

        async with self._pool.connection() as conn, conn.transaction():
            # Archive message (not delete - keeps history)
            await self._pgmq.archive(self._queue_name, received.msg_id, conn)

            # Use stored procedure: update status + error + audit + batch counter in ONE DB CALL
            # Note: Moving to TSQ never completes a batch (is_batch_complete always False)
            await self._command_repo.sp_finish_command(
                domain,
                command_id,
                CommandStatus.IN_TROUBLESHOOTING_QUEUE,
                event_type="MOVED_TO_TSQ",
                error_type=error_type,
                error_code=error_code,
                error_msg=error_msg,
                details={
                    "msg_id": received.msg_id,
                    "attempt": attempt,
                    "max_attempts": received.metadata.max_attempts,
                    "reason": "EXHAUSTED",
                    "error_type": error_type,
                    "error_code": error_code,
                    "error_msg": error_msg,
                },
                batch_id=received.metadata.batch_id,
                conn=conn,
            )

        logger.warning(
            f"Retry exhausted for {domain}.{command.command_type} "
            f"(command_id={command_id}, attempt={attempt}/{received.metadata.max_attempts}), "
            f"moved to troubleshooting queue: [{error_code}] {error_msg}"
        )

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._running

    @property
    def in_flight_count(self) -> int:
        """Get the number of commands currently being processed."""
        return len(self._in_flight)

    async def run(
        self,
        concurrency: int = 1,
        poll_interval: float = 1.0,
        use_notify: bool = True,
    ) -> None:
        """Run the worker continuously, processing commands.

        The worker will poll for commands and process them concurrently
        up to the specified concurrency limit. When use_notify is True,
        the worker listens for pg_notify notifications to wake up
        immediately when new commands arrive.

        Args:
            concurrency: Maximum number of commands to process concurrently
            poll_interval: Seconds between polls (fallback when notify misses)
            use_notify: Use pg_notify for immediate wake-up

        Raises:
            RuntimeError: If no handler registry is configured
        """
        if self._registry is None:
            raise RuntimeError("Cannot run worker without a handler registry")

        self._running = True
        self._stop_event = asyncio.Event()
        semaphore = asyncio.Semaphore(concurrency)

        logger.info(
            f"Starting worker for {self._domain} "
            f"(concurrency={concurrency}, poll_interval={poll_interval}s, use_notify={use_notify})"
        )

        try:
            if use_notify:
                await self._run_with_notify(semaphore, poll_interval)
            else:
                await self._run_with_polling(semaphore, poll_interval)
        except asyncio.CancelledError:
            logger.info("Worker received cancellation signal")
        except Exception:
            logger.exception(f"Worker for {self._domain} crashed; propagate error to supervisor")
            raise
        finally:
            await self._wait_for_in_flight()
            self._running = False
            logger.info(f"Worker for {self._domain} stopped")

    async def stop(self, timeout: float | None = None) -> None:
        """Stop the worker gracefully.

        Signals the worker to stop receiving new commands and waits for
        in-flight commands to complete (or timeout).

        Args:
            timeout: Maximum seconds to wait for in-flight commands.
                     If None, waits indefinitely.
        """
        if not self._running or self._stop_event is None:
            return

        logger.info(f"Stopping worker for {self._domain}...")
        self._stop_event.set()

        if self._in_flight:
            logger.info(f"Waiting for {len(self._in_flight)} in-flight commands...")
            try:
                await asyncio.wait_for(
                    self._wait_for_in_flight(),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning(
                    f"Timeout waiting for in-flight commands, "
                    f"{len(self._in_flight)} commands may be redelivered"
                )

    async def _wait_for_in_flight(self) -> None:
        """Wait for all in-flight tasks to complete."""
        if self._in_flight:
            await asyncio.gather(*self._in_flight, return_exceptions=True)

    async def _run_with_notify(
        self,
        semaphore: asyncio.Semaphore,
        poll_interval: float,
    ) -> None:
        """Run the worker using pg_notify for wake-up with poll fallback.

        Uses a tight processing loop to drain the queue efficiently when
        multiple messages are pending. Only waits for notifications when
        the queue appears empty.
        """
        assert self._stop_event is not None

        async with self._pool.connection() as listen_conn:
            # Set autocommit mode - required for LISTEN/NOTIFY to work in real-time
            # Without autocommit, notifications are only received when a transaction ends
            await listen_conn.set_autocommit(True)

            # Subscribe to notifications for this queue
            channel = f"{PGMQ_NOTIFY_CHANNEL}_{self._queue_name}"
            await listen_conn.execute(f"LISTEN {channel}")
            logger.debug(f"Listening on channel {channel}")

            while not self._stop_event.is_set():
                # TIGHT LOOP: Process all available work before waiting
                await self._drain_queue(semaphore)

                if self._stop_event.is_set():
                    return

                # IDLE: Queue is empty, wait for notification or poll timeout
                try:
                    gen = listen_conn.notifies(timeout=poll_interval)
                    async for _ in gen:
                        break  # Got notification, return to tight loop
                except TimeoutError:
                    pass  # Poll fallback, return to tight loop

    async def _drain_queue(self, semaphore: asyncio.Semaphore) -> None:
        """Process commands continuously until queue is empty.

        This tight loop ensures high throughput when many messages are
        pending. It only exits when receive() returns no commands.

        A small yield between iterations allows other workers to fairly
        compete for messages when multiple workers are running.
        """
        assert self._stop_event is not None

        while not self._stop_event.is_set():
            available_slots = semaphore._value

            if available_slots == 0:
                # All slots busy - wait for at least one to complete
                await self._wait_for_slot()
                continue

            commands = await self.receive(batch_size=available_slots)

            if not commands:
                # Queue is empty (for this worker), exit tight loop
                return

            # Spawn concurrent processing tasks
            for cmd in commands:
                task = asyncio.create_task(self._process_command(cmd, semaphore))
                self._in_flight.add(task)
                task.add_done_callback(self._in_flight.discard)

            # Yield to allow other workers to compete for messages
            # This prevents one worker from monopolizing all queue reads
            await asyncio.sleep(0)

    async def _wait_for_slot(self) -> None:
        """Wait for at least one in-flight task to complete."""
        if not self._in_flight:
            return

        # Wait for any one task to complete
        _done, _ = await asyncio.wait(
            self._in_flight,
            return_when=asyncio.FIRST_COMPLETED,
        )

    async def _run_with_polling(
        self,
        semaphore: asyncio.Semaphore,
        poll_interval: float,
    ) -> None:
        """Run the worker using simple polling.

        Uses the same tight processing loop as notify mode for consistency.
        """
        assert self._stop_event is not None

        while not self._stop_event.is_set():
            # TIGHT LOOP: Process all available work before waiting
            await self._drain_queue(semaphore)

            if self._stop_event.is_set():
                return

            # IDLE: Wait for poll interval
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=poll_interval,
                )

    async def _process_command(
        self,
        received: ReceivedCommand,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Process a single command with semaphore control.

        The handler runs without a transaction wrapper to allow handlers with
        long-running operations (sleeps, external API calls) to not hold
        database connections open. Command completion happens in a separate
        transaction via self.complete().

        Handlers that need transactional guarantees should manage their own
        database transactions using their injected connection pool.

        Args:
            received: The received command to process
            semaphore: Semaphore for concurrency control
        """
        assert self._registry is not None

        async with semaphore:
            try:
                context = HandlerContext(
                    command=received.command,
                    attempt=received.context.attempt,
                    max_attempts=received.context.max_attempts,
                    msg_id=received.msg_id,
                    visibility_extender=received.context.visibility_extender,
                )

                result = await self._registry.dispatch(received.command, context)

                # Complete in separate transaction
                await self.complete(received, result=result)

            except TransientCommandError as e:
                # Explicit transient error - apply backoff and retry
                await self.fail(received, e, is_transient=True)
            except PermanentCommandError as e:
                # Permanent error - move to troubleshooting queue
                await self.fail_permanent(received, e)
            except Exception as e:
                # Unknown exception treated as transient
                logger.exception(f"Error processing command {received.command.command_id}")
                await self.fail(received, e, is_transient=True)
