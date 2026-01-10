"""Native synchronous worker for processing commands.

This module provides a native sync worker using ThreadPoolExecutor for
concurrency, without the overhead of async wrapper patterns.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg import errors as psycopg_errors
from psycopg_pool import PoolTimeout

from commandbus._core.pgmq_sql import PGMQ_NOTIFY_CHANNEL
from commandbus.batch import invoke_sync_batch_callback
from commandbus.exceptions import PermanentCommandError, TransientCommandError
from commandbus.models import (
    Command,
    CommandMetadata,
    CommandStatus,
    HandlerContext,
    ReplyOutcome,
)
from commandbus.policies import DEFAULT_RETRY_POLICY, RetryPolicy
from commandbus.sync.health import HealthStatus
from commandbus.sync.pgmq import SyncPgmqClient
from commandbus.sync.repositories.audit import SyncAuditLogger
from commandbus.sync.repositories.batch import SyncBatchRepository
from commandbus.sync.repositories.command import SyncCommandRepository
from commandbus.sync.timeouts import validate_timeouts

if TYPE_CHECKING:
    from psycopg import Connection
    from psycopg_pool import ConnectionPool

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


class SyncWorker:
    """Native synchronous worker for processing commands.

    The worker uses a ThreadPoolExecutor for concurrent command processing,
    polling the queue for messages and dispatching handlers in worker threads.

    Example:
        pool = ConnectionPool(conninfo=DATABASE_URL)
        registry = HandlerRegistry()

        @registry.sync_handler("payments", "DebitAccount")
        def handle_debit(command, context):
            return {"processed": True}

        worker = SyncWorker(pool, domain="payments", registry=registry)
        worker.run(concurrency=4)  # Blocks until stop() is called
    """

    def __init__(
        self,
        pool: ConnectionPool[Any],
        domain: str,
        registry: HandlerRegistry | None = None,
        *,
        visibility_timeout: int = 30,
        retry_policy: RetryPolicy | None = None,
        statement_timeout: int = 25000,
    ) -> None:
        """Initialize the sync worker.

        Args:
            pool: psycopg sync connection pool
            domain: The domain to process commands for
            registry: Handler registry for dispatching commands
            visibility_timeout: Default visibility timeout in seconds
            retry_policy: Policy for retry behavior and backoff
            statement_timeout: PostgreSQL statement timeout in milliseconds

        Raises:
            ValueError: If statement_timeout >= visibility_timeout
        """
        # Validate timeout hierarchy
        validate_timeouts(statement_timeout, visibility_timeout)

        self._pool = pool
        self._domain = domain
        self._registry = registry
        self._visibility_timeout = visibility_timeout
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._statement_timeout = statement_timeout
        self._queue_name = _make_queue_name(domain)

        # Sync components
        self._pgmq = SyncPgmqClient(pool)
        self._command_repo = SyncCommandRepository(pool)
        self._batch_repo = SyncBatchRepository(pool)
        self._audit_logger = SyncAuditLogger(pool)

        # Runtime state
        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = threading.Event()
        self._in_flight: dict[int, tuple[Future[None], float]] = {}
        self._in_flight_lock = threading.Lock()
        self._health = HealthStatus()
        self._concurrency = 1

    @property
    def domain(self) -> str:
        """Get the domain this worker processes."""
        return self._domain

    @property
    def queue_name(self) -> str:
        """Get the queue name this worker reads from."""
        return self._queue_name

    @property
    def health_status(self) -> HealthStatus:
        """Get the health status tracker."""
        return self._health

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._executor is not None and not self._stop_event.is_set()

    @property
    def in_flight_count(self) -> int:
        """Get the number of commands currently being processed."""
        with self._in_flight_lock:
            return len(self._in_flight)

    def run(
        self,
        concurrency: int = 4,
        poll_interval: float = 1.0,
        use_notify: bool = True,
    ) -> None:
        """Run the worker continuously, processing commands.

        This method blocks until stop() is called. Commands are processed
        concurrently using a ThreadPoolExecutor with the specified concurrency.

        Args:
            concurrency: Maximum number of commands to process concurrently
            poll_interval: Seconds between queue polls when idle (or notify timeout)
            use_notify: If True, use LISTEN/NOTIFY for immediate wakeup on new messages

        Raises:
            RuntimeError: If no handler registry is configured
        """
        if self._registry is None:
            raise RuntimeError("Cannot run worker without a handler registry")

        self._concurrency = concurrency
        self._stop_event.clear()
        self._executor = ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix=f"worker-{self._domain}",
        )

        mode = "notify" if use_notify else "polling"
        logger.info(
            f"Starting sync worker for {self._domain} "
            f"(concurrency={concurrency}, poll_interval={poll_interval}s, mode={mode})"
        )

        try:
            if use_notify:
                self._run_with_notify(poll_interval)
            else:
                self._run_with_polling(poll_interval)
        except Exception:
            logger.exception(f"Sync worker for {self._domain} crashed")
            raise
        finally:
            self._drain_in_flight()
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
            logger.info(f"Sync worker for {self._domain} stopped")

    def _run_with_notify(self, poll_interval: float) -> None:
        """Run loop using LISTEN/NOTIFY for immediate wakeup."""
        # Get a dedicated connection for LISTEN - must stay open for notifications
        with self._pool.connection() as listen_conn:
            # Set autocommit - required for LISTEN/NOTIFY to work in real-time
            listen_conn.autocommit = True

            # Subscribe to notifications for this queue
            channel = f"{PGMQ_NOTIFY_CHANNEL}_{self._queue_name}"
            listen_conn.execute(f"LISTEN {channel}")
            logger.debug(f"Listening on channel {channel}")

            while not self._stop_event.is_set():
                # TIGHT LOOP: Process all available work before waiting
                self._drain_queue()

                if self._stop_event.is_set():
                    return

                # IDLE: Queue is empty, wait for notification or poll timeout
                try:
                    # notifies() returns a generator; consume with timeout
                    gen = listen_conn.notifies(timeout=poll_interval)
                    for _ in gen:
                        break  # Got notification, return to tight loop
                except TimeoutError:
                    pass  # Poll fallback, return to tight loop

    def _drain_queue(self) -> None:
        """Process commands continuously until queue is empty.

        This tight loop ensures high throughput when many messages are
        pending. It only exits when poll returns no commands.
        """
        while not self._stop_event.is_set():
            try:
                dispatched = self._poll_and_dispatch()

                # Check for completed tasks and clean up
                self._cleanup_completed()

                # Check for stuck threads
                self._check_stuck_threads()

                # If no messages were available, queue is drained
                if dispatched == 0:
                    return

                # If at capacity, wait for a slot before continuing
                with self._in_flight_lock:
                    available = self._concurrency - len(self._in_flight)

                if available <= 0:
                    self._wait_for_slot(timeout=1.0)

            except Exception:
                logger.exception("Error in worker drain loop")
                self._health.record_failure()
                return  # Exit drain loop on error

    def _run_with_polling(self, poll_interval: float) -> None:
        """Run loop using simple polling (fallback mode)."""
        while not self._stop_event.is_set():
            try:
                dispatched = self._poll_and_dispatch()

                # Check for completed tasks and clean up
                self._cleanup_completed()

                # Check for stuck threads
                self._check_stuck_threads()

                # If at capacity, wait for a slot
                with self._in_flight_lock:
                    available = self._concurrency - len(self._in_flight)

                if available <= 0:
                    self._wait_for_slot(timeout=poll_interval)
                elif dispatched == 0 and self._stop_event.wait(timeout=poll_interval):
                    # Queue was empty, wait before polling again (or stop requested)
                    break
                # else: got messages and have slots, immediately poll again

            except Exception:
                logger.exception("Error in worker poll loop")
                self._health.record_failure()
                # Brief pause before retrying
                if self._stop_event.wait(timeout=1.0):
                    break

    def _poll_and_dispatch(self) -> int:
        """Poll for messages and dispatch to thread pool.

        Returns:
            Number of messages dispatched
        """
        with self._in_flight_lock:
            available = self._concurrency - len(self._in_flight)

        if available <= 0:
            return 0

        # Read messages from queue, handling pool exhaustion
        try:
            received_commands = self._receive(batch_size=available)
        except PoolTimeout:
            logger.warning(f"Pool exhaustion while polling for {self._domain}")
            self._health.record_pool_exhaustion()
            return 0

        for received in received_commands:
            future = self._executor.submit(self._process_command, received)  # type: ignore[union-attr]
            with self._in_flight_lock:
                self._in_flight[received.msg_id] = (future, time.monotonic())

        return len(received_commands)

    def _receive(
        self,
        batch_size: int = 1,
        visibility_timeout: int | None = None,
    ) -> list[ReceivedCommand]:
        """Receive commands from the queue.

        Args:
            batch_size: Maximum number of commands to receive
            visibility_timeout: Override default visibility timeout

        Returns:
            List of received commands (may be empty)
        """
        vt = visibility_timeout or self._visibility_timeout
        received: list[ReceivedCommand] = []

        with self._pool.connection() as conn:
            # Set statement timeout for this connection
            conn.execute(f"SET statement_timeout = {self._statement_timeout}")

            messages = self._pgmq.read(
                self._queue_name,
                visibility_timeout=vt,
                batch_size=batch_size,
                conn=conn,
            )

            for msg in messages:
                try:
                    result = self._process_message(msg.msg_id, msg.message, conn)
                    if result is not None:
                        received.append(result)
                except Exception:
                    logger.exception(f"Error processing message {msg.msg_id}")
                    # Message will reappear after visibility timeout

        return received

    def _process_message(
        self,
        msg_id: int,
        message: dict[str, Any],
        conn: Connection[Any],
    ) -> ReceivedCommand | None:
        """Process a single message from the queue.

        Args:
            msg_id: PGMQ message ID
            message: Message payload
            conn: Database connection

        Returns:
            ReceivedCommand if ready for processing, None if skipped
        """
        domain = message.get("domain", self._domain)
        command_id_str = message.get("command_id")
        if not command_id_str:
            logger.warning(f"Message {msg_id} missing command_id, archiving")
            self._pgmq.archive(self._queue_name, msg_id, conn)
            return None

        command_id = UUID(command_id_str)

        # Use stored procedure to receive command
        result = self._command_repo.sp_receive_command(domain, command_id, msg_id=msg_id, conn=conn)

        if result is None:
            logger.warning(f"No metadata for command {command_id} in domain {domain}, archiving")
            self._pgmq.archive(self._queue_name, msg_id, conn)
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

        return ReceivedCommand(
            command=command,
            context=context,
            msg_id=msg_id,
            metadata=metadata,
        )

    def _process_command(self, received: ReceivedCommand) -> None:
        """Process a single command in a worker thread.

        Args:
            received: The received command to process
        """
        assert self._registry is not None

        try:
            context = HandlerContext(
                command=received.command,
                attempt=received.context.attempt,
                max_attempts=received.context.max_attempts,
                msg_id=received.msg_id,
                visibility_extender=received.context.visibility_extender,
            )

            result = self._registry.dispatch_sync(received.command, context)

            # Complete in separate connection/transaction
            self._complete(received, result=result)
            self._health.record_success()

        except TransientCommandError as e:
            # Explicit transient error - apply backoff and retry
            self._fail(received, e, is_transient=True)
            self._health.record_failure(e)
        except PermanentCommandError as e:
            # Permanent error - move to troubleshooting queue
            self._fail_permanent(received, e)
            self._health.record_failure(e)
        except psycopg_errors.QueryCanceled as e:
            # Statement timeout exceeded - treat as transient
            logger.warning(
                f"Statement timeout for command {received.command.command_id} "
                f"(attempt {received.context.attempt})"
            )
            transient_error = TransientCommandError(
                code="STATEMENT_TIMEOUT",
                message="PostgreSQL statement timeout exceeded",
            )
            self._fail(received, transient_error, is_transient=True)
            self._health.record_failure(e)
        except PoolTimeout as e:
            # Pool exhaustion during processing - treat as transient
            logger.warning(
                f"Pool timeout for command {received.command.command_id} "
                f"(attempt {received.context.attempt})"
            )
            self._health.record_pool_exhaustion()
            transient_error = TransientCommandError(
                code="POOL_TIMEOUT",
                message="Connection pool exhausted",
            )
            self._fail(received, transient_error, is_transient=True)
            self._health.record_failure(e)
        except Exception as e:
            # Unknown exception treated as transient
            logger.exception(f"Error processing command {received.command.command_id}")
            self._fail(received, e, is_transient=True)
            self._health.record_failure(e)
        finally:
            # Remove from in-flight tracking
            with self._in_flight_lock:
                self._in_flight.pop(received.msg_id, None)

    def _complete(
        self,
        received: ReceivedCommand,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Complete a command successfully.

        Args:
            received: The received command to complete
            result: Optional result data to include in the reply
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain

        with self._pool.connection() as conn, conn.transaction():
            # Delete message from queue
            self._pgmq.delete(self._queue_name, received.msg_id, conn)

            # Use stored procedure to finish command
            is_batch_complete = self._command_repo.sp_finish_command(
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
                self._pgmq.send(command.reply_to, reply_message, conn=conn)

        logger.info(f"Completed command {domain}.{command.command_type} (command_id={command_id})")

        # Invoke batch completion callback - outside transaction
        if is_batch_complete and received.metadata.batch_id is not None:
            invoke_sync_batch_callback(domain, received.metadata.batch_id, self._batch_repo)

    def _fail(
        self,
        received: ReceivedCommand,
        error: TransientCommandError | Exception,
        is_transient: bool = True,
    ) -> None:
        """Record a command failure and schedule retry if applicable.

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
            error_type = "TRANSIENT"
            error_code = type(error).__name__
            error_msg = str(error)

        # Check if retries are exhausted for transient errors
        if is_transient and not self._retry_policy.should_retry(attempt):
            self._fail_exhausted(received, error_type, error_code, error_msg)
            return

        with self._pool.connection() as conn, conn.transaction():
            # Use stored procedure to fail command
            self._command_repo.sp_fail_command(
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
                self._pgmq.set_vt(self._queue_name, received.msg_id, backoff, conn)

        if is_transient:
            delay = self._retry_policy.get_backoff(attempt)
            logger.info(
                f"Transient failure for {domain}.{command.command_type} "
                f"(command_id={command_id}, attempt={attempt}, backoff={delay}s): "
                f"[{error_code}] {error_msg}"
            )
        else:
            logger.warning(
                f"Failure for {domain}.{command.command_type} "
                f"(command_id={command_id}, attempt={attempt}): "
                f"[{error_code}] {error_msg}"
            )

    def _fail_permanent(
        self,
        received: ReceivedCommand,
        error: PermanentCommandError,
    ) -> None:
        """Handle a permanent failure by moving command to troubleshooting queue.

        Args:
            received: The received command that failed
            error: The permanent error that occurred
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain

        with self._pool.connection() as conn, conn.transaction():
            # Archive message
            self._pgmq.archive(self._queue_name, received.msg_id, conn)

            # Use stored procedure to finish command
            self._command_repo.sp_finish_command(
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

    def _fail_exhausted(
        self,
        received: ReceivedCommand,
        error_type: str,
        error_code: str,
        error_msg: str,
    ) -> None:
        """Handle retry exhaustion by moving command to troubleshooting queue.

        Args:
            received: The received command that exhausted retries
            error_type: Type of the error
            error_code: Error code from the exception
            error_msg: Error message from the exception
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain
        attempt = received.context.attempt

        with self._pool.connection() as conn, conn.transaction():
            # Archive message
            self._pgmq.archive(self._queue_name, received.msg_id, conn)

            # Use stored procedure to finish command
            self._command_repo.sp_finish_command(
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

    def _cleanup_completed(self) -> None:
        """Remove completed futures from in-flight tracking."""
        with self._in_flight_lock:
            completed = [msg_id for msg_id, (future, _) in self._in_flight.items() if future.done()]
            for msg_id in completed:
                del self._in_flight[msg_id]

    def _check_stuck_threads(self) -> None:
        """Check for threads that have been running too long."""
        now = time.monotonic()
        stuck_threshold = self._visibility_timeout + 5.0

        with self._in_flight_lock:
            for msg_id, (future, start_time) in list(self._in_flight.items()):
                elapsed = now - start_time
                if elapsed > stuck_threshold and not future.done():
                    logger.error(f"Thread stuck for {elapsed:.1f}s processing msg_id={msg_id}")
                    self._health.record_stuck_thread()
                    # Note: We don't cancel the future as it may complete eventually
                    # The message will become visible again after visibility timeout

    def _wait_for_slot(self, timeout: float = 5.0) -> None:
        """Wait for at least one in-flight task to complete.

        Args:
            timeout: Maximum time to wait in seconds
        """
        with self._in_flight_lock:
            futures = [f for f, _ in self._in_flight.values()]

        if not futures:
            return

        # Wait for any one task to complete
        wait(futures, timeout=timeout, return_when="FIRST_COMPLETED")

    def _drain_in_flight(self, timeout: float = 30.0) -> None:
        """Wait for all in-flight tasks to complete.

        Args:
            timeout: Maximum time to wait in seconds
        """
        with self._in_flight_lock:
            futures = [f for f, _ in self._in_flight.values()]

        if not futures:
            return

        logger.info(f"Draining {len(futures)} in-flight commands...")
        _done, not_done = wait(futures, timeout=timeout)

        if not_done:
            logger.warning(
                f"Timeout draining in-flight commands, {len(not_done)} commands may be redelivered"
            )

    def stop(self, timeout: float | None = None) -> None:
        """Stop the worker gracefully.

        Signals the worker to stop receiving new commands and waits for
        in-flight commands to complete (or timeout).

        Args:
            timeout: Maximum seconds to wait for in-flight commands.
                     If None, uses default drain timeout.
        """
        logger.info(f"Stopping sync worker for {self._domain}...")
        self._stop_event.set()

        if self.in_flight_count > 0:
            logger.info(f"Waiting for {self.in_flight_count} in-flight commands...")
            self._drain_in_flight(timeout=timeout or 30.0)
