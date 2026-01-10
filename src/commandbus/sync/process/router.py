"""Native synchronous process reply router.

This module provides a native sync reply router for process managers using
ThreadPoolExecutor for concurrency, without the overhead of async wrappers.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg import errors as psycopg_errors
from psycopg_pool import PoolTimeout

from commandbus._core.pgmq_sql import PGMQ_NOTIFY_CHANNEL
from commandbus.models import Reply, ReplyOutcome
from commandbus.sync.health import HealthStatus
from commandbus.sync.pgmq import SyncPgmqClient
from commandbus.sync.timeouts import validate_timeouts

if TYPE_CHECKING:
    from psycopg import Connection
    from psycopg_pool import ConnectionPool

    from commandbus.process.models import ProcessMetadata
    from commandbus.sync.repositories.process import SyncProcessRepository


# Protocol for sync process managers
class SyncProcessManager:
    """Protocol for process managers with sync support.

    Process managers that want to work with SyncProcessReplyRouter must
    implement the handle_reply_sync method.
    """

    def handle_reply_sync(
        self,
        reply: Reply,
        process: ProcessMetadata[Any, Any],
        conn: Connection[Any] = ...,
    ) -> None:
        """Handle a reply synchronously.

        Args:
            reply: The reply received
            process: The process metadata
            conn: Database connection for transaction
        """
        ...


logger = logging.getLogger(__name__)


class SyncProcessReplyRouter:
    """Native synchronous router for process replies.

    Routes replies from a reply queue to appropriate process managers using
    a ThreadPoolExecutor for concurrent processing.

    Example:
        pool = ConnectionPool(conninfo=DATABASE_URL)
        process_repo = SyncProcessRepository(pool)

        managers = {
            "OrderProcess": OrderProcessManager(pool),
        }

        router = SyncProcessReplyRouter(
            pool=pool,
            process_repo=process_repo,
            managers=managers,
            reply_queue="orders__process_replies",
            domain="orders",
        )

        # Run the router (blocks until stop() is called)
        router.run(concurrency=4)
    """

    def __init__(
        self,
        pool: ConnectionPool[Any],
        process_repo: SyncProcessRepository,
        managers: dict[str, SyncProcessManager],
        reply_queue: str,
        domain: str,
        *,
        visibility_timeout: int = 30,
        statement_timeout: int = 25000,
    ) -> None:
        """Initialize the sync process reply router.

        Args:
            pool: psycopg sync connection pool
            process_repo: Sync process repository
            managers: Dict mapping process_type to ProcessManager
            reply_queue: PGMQ queue name for replies
            domain: Domain this router handles
            visibility_timeout: Default visibility timeout in seconds
            statement_timeout: PostgreSQL statement timeout in milliseconds

        Raises:
            ValueError: If statement_timeout >= visibility_timeout
        """
        # Validate timeout hierarchy
        validate_timeouts(statement_timeout, visibility_timeout)

        self._pool = pool
        self._process_repo = process_repo
        self._managers = managers
        self._reply_queue = reply_queue
        self._domain = domain
        self._visibility_timeout = visibility_timeout
        self._statement_timeout = statement_timeout

        # Sync PGMQ client
        self._pgmq = SyncPgmqClient(pool)

        # Runtime state
        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = threading.Event()
        self._in_flight: dict[int, tuple[Future[None], float]] = {}
        self._in_flight_lock = threading.Lock()
        self._health = HealthStatus()
        self._concurrency = 1

    @property
    def reply_queue(self) -> str:
        """Get the reply queue name."""
        return self._reply_queue

    @property
    def domain(self) -> str:
        """Get the domain this router handles."""
        return self._domain

    @property
    def health_status(self) -> HealthStatus:
        """Get the health status tracker."""
        return self._health

    @property
    def is_running(self) -> bool:
        """Check if the router is currently running."""
        return self._executor is not None and not self._stop_event.is_set()

    @property
    def in_flight_count(self) -> int:
        """Get the number of replies currently being processed."""
        with self._in_flight_lock:
            return len(self._in_flight)

    def run(
        self,
        concurrency: int = 4,
        poll_interval: float = 1.0,
        use_notify: bool = True,
    ) -> None:
        """Run the router continuously, processing replies.

        This method blocks until stop() is called. Replies are processed
        concurrently using a ThreadPoolExecutor.

        Args:
            concurrency: Maximum number of replies to process concurrently
            poll_interval: Seconds between queue polls when idle (or notify timeout)
            use_notify: If True, use LISTEN/NOTIFY for immediate wakeup on new messages
        """
        self._concurrency = concurrency
        self._stop_event.clear()
        self._executor = ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix=f"router-{self._domain}",
        )

        mode = "notify" if use_notify else "polling"
        logger.info(
            f"Starting sync process reply router for {self._domain} "
            f"(queue={self._reply_queue}, concurrency={concurrency}, mode={mode})"
        )

        try:
            if use_notify:
                self._run_with_notify(poll_interval)
            else:
                self._run_with_polling(poll_interval)
        except Exception:
            logger.exception(f"Sync reply router for {self._domain} crashed")
            raise
        finally:
            self._drain_in_flight()
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
            logger.info(f"Sync reply router for {self._domain} stopped")

    def _run_with_notify(self, poll_interval: float) -> None:
        """Run loop using LISTEN/NOTIFY for immediate wakeup."""
        # Get a dedicated connection for LISTEN - must stay open for notifications
        with self._pool.connection() as listen_conn:
            # Set autocommit - required for LISTEN/NOTIFY to work in real-time
            listen_conn.autocommit = True

            # Subscribe to notifications for this queue
            channel = f"{PGMQ_NOTIFY_CHANNEL}_{self._reply_queue}"
            listen_conn.execute(f"LISTEN {channel}")
            logger.debug(f"Listening on channel {channel}")

            while not self._stop_event.is_set():
                # TIGHT LOOP: Process all available work before waiting
                self._drain_queue()

                if self._stop_event.is_set():
                    return

                # IDLE: Queue is empty, wait for notification or poll timeout
                try:
                    gen = listen_conn.notifies(timeout=poll_interval)
                    for _ in gen:
                        break  # Got notification, return to tight loop
                except TimeoutError:
                    pass  # Poll fallback, return to tight loop

    def _drain_queue(self) -> None:
        """Process replies continuously until queue is empty."""
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
                logger.exception("Error in router drain loop")
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
                logger.exception("Error in router poll loop")
                self._health.record_failure()
                # Brief pause before retrying
                if self._stop_event.wait(timeout=1.0):
                    break

    def _poll_and_dispatch(self) -> int:
        """Poll for replies and dispatch to thread pool.

        Returns:
            Number of replies dispatched
        """
        with self._in_flight_lock:
            available = self._concurrency - len(self._in_flight)

        if available <= 0:
            return 0

        # Read messages from reply queue, handling pool exhaustion
        try:
            with self._pool.connection() as conn:
                conn.execute(f"SET statement_timeout = {self._statement_timeout}")
                messages = self._pgmq.read(
                    self._reply_queue,
                    visibility_timeout=self._visibility_timeout,
                    batch_size=available,
                    conn=conn,
                )
        except PoolTimeout:
            logger.warning(f"Pool exhaustion while polling for {self._domain} replies")
            self._health.record_pool_exhaustion()
            return 0

        for msg in messages:
            future = self._executor.submit(self._process_reply, msg)  # type: ignore[union-attr]
            with self._in_flight_lock:
                self._in_flight[msg.msg_id] = (future, time.monotonic())

        return len(messages)

    def _process_reply(self, msg: Any) -> None:
        """Process a single reply message in a worker thread.

        Args:
            msg: The PGMQ message containing the reply
        """
        msg_id = msg.msg_id
        try:
            self._dispatch_reply(msg)
            self._health.record_success()
        except psycopg_errors.QueryCanceled:
            logger.warning(f"Statement timeout processing reply message {msg_id}")
            self._health.record_failure()
            # Leave message for retry (visibility timeout)
        except PoolTimeout:
            logger.warning(f"Pool timeout processing reply message {msg_id}")
            self._health.record_pool_exhaustion()
            self._health.record_failure()
            # Leave message for retry (visibility timeout)
        except Exception:
            logger.exception(f"Error processing reply message {msg_id}")
            self._health.record_failure()
            # Leave message for retry (visibility timeout)
        finally:
            # Remove from in-flight tracking
            with self._in_flight_lock:
                self._in_flight.pop(msg_id, None)

    def _dispatch_reply(self, msg: Any) -> None:
        """Dispatch a reply to the appropriate process manager.

        Args:
            msg: The PGMQ message containing the reply
        """
        msg_id = msg.msg_id
        message = msg.message

        # Build Reply object
        reply = Reply(
            command_id=UUID(message["command_id"]),
            correlation_id=UUID(message["correlation_id"])
            if message.get("correlation_id")
            else None,
            outcome=ReplyOutcome(message["outcome"]),
            data=message.get("result"),
            error_code=message.get("error_code"),
            error_message=message.get("error_message"),
        )

        with self._pool.connection() as conn, conn.transaction():
            conn.execute(f"SET statement_timeout = {self._statement_timeout}")

            if reply.correlation_id is None:
                logger.warning(f"Reply {msg_id} has no correlation_id, discarding")
                self._pgmq.delete(self._reply_queue, msg_id, conn=conn)
                return

            # Look up process by correlation_id (which is process_id)
            process = self._process_repo.get_by_id(
                self._domain,
                reply.correlation_id,
                conn=conn,
            )

            if process is None:
                logger.warning(f"Reply for unknown process {reply.correlation_id}, discarding")
                self._pgmq.delete(self._reply_queue, msg_id, conn=conn)
                return

            manager = self._managers.get(process.process_type)
            if manager is None:
                logger.error(f"No manager for process type {process.process_type}, discarding")
                self._pgmq.delete(self._reply_queue, msg_id, conn=conn)
                return

            # Dispatch to manager (updates process state and sends next command)
            manager.handle_reply_sync(reply, process, conn=conn)

            # Delete message (atomically with process update)
            self._pgmq.delete(self._reply_queue, msg_id, conn=conn)

        logger.debug(f"Processed reply for process {self._domain}.{reply.correlation_id}")

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
                    logger.error(
                        f"Thread stuck for {elapsed:.1f}s processing reply msg_id={msg_id}"
                    )
                    self._health.record_stuck_thread()

    def _wait_for_slot(self, timeout: float = 5.0) -> None:
        """Wait for at least one in-flight task to complete.

        Args:
            timeout: Maximum time to wait in seconds
        """
        with self._in_flight_lock:
            futures = [f for f, _ in self._in_flight.values()]

        if not futures:
            return

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

        logger.info(f"Draining {len(futures)} in-flight replies...")
        _done, not_done = wait(futures, timeout=timeout)

        if not_done:
            logger.warning(
                f"Timeout draining in-flight replies, {len(not_done)} replies may be redelivered"
            )

    def stop(self, timeout: float | None = None) -> None:
        """Stop the router gracefully.

        Signals the router to stop receiving new replies and waits for
        in-flight replies to complete (or timeout).

        Args:
            timeout: Maximum seconds to wait for in-flight replies.
                     If None, uses default drain timeout.
        """
        logger.info(f"Stopping sync reply router for {self._domain}...")
        self._stop_event.set()

        if self.in_flight_count > 0:
            logger.info(f"Waiting for {self.in_flight_count} in-flight replies...")
            self._drain_in_flight(timeout=timeout or 30.0)
