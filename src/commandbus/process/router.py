"""Reply router for process managers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from commandbus.models import Reply, ReplyOutcome
from commandbus.pgmq.client import PGMQ_NOTIFY_CHANNEL, PgmqClient

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from commandbus.process.base import BaseProcessManager
    from commandbus.process.repository import ProcessRepository

logger = logging.getLogger(__name__)


class ProcessReplyRouter:
    """Routes replies from process queue to appropriate process managers.

    Implements a high-concurrency worker pattern similar to command workers,
    using semaphores and pg_notify for efficient throughput.
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        process_repo: ProcessRepository,
        managers: dict[str, BaseProcessManager[Any, Any]],
        reply_queue: str,
        domain: str,
        visibility_timeout: int = 30,
    ):
        self._pool = pool
        self._process_repo = process_repo
        self._managers = managers
        self._reply_queue = reply_queue
        self._domain = domain
        self._visibility_timeout = visibility_timeout
        self._pgmq = PgmqClient(pool)

        self._running = False
        self._stop_event: asyncio.Event | None = None
        self._in_flight: set[asyncio.Task[None]] = set()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def reply_queue(self) -> str:
        """Return the reply queue name."""
        return self._reply_queue

    @property
    def domain(self) -> str:
        """Return the domain handled by this router."""
        return self._domain

    async def run(
        self,
        concurrency: int = 10,
        poll_interval: float = 1.0,
        use_notify: bool = True,
    ) -> None:
        """Run the router continuously."""
        self._running = True
        self._stop_event = asyncio.Event()
        semaphore = asyncio.Semaphore(concurrency)

        logger.info(
            f"Starting process reply router on {self._reply_queue} (concurrency={concurrency})"
        )

        try:
            if use_notify:
                await self._run_with_notify(semaphore, poll_interval)
            else:
                await self._run_with_polling(semaphore, poll_interval)
        except asyncio.CancelledError:
            logger.info("Reply router received cancellation signal")
        except Exception:
            logger.exception("Reply router crashed; propagate error to supervisor")
            raise
        finally:
            await self._wait_for_in_flight()
            self._running = False
            logger.info("Reply router stopped")

    async def stop(self, timeout: float | None = None) -> None:
        """Stop the router gracefully."""
        if not self._running or self._stop_event is None:
            return

        logger.info("Stopping reply router...")
        self._stop_event.set()

        if self._in_flight:
            logger.info(f"Waiting for {len(self._in_flight)} in-flight replies...")
            try:
                await asyncio.wait_for(
                    self._wait_for_in_flight(),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning("Timeout waiting for in-flight replies")

    async def _wait_for_in_flight(self) -> None:
        if self._in_flight:
            await asyncio.gather(*self._in_flight, return_exceptions=True)

    async def _run_with_notify(
        self,
        semaphore: asyncio.Semaphore,
        poll_interval: float,
    ) -> None:
        assert self._stop_event is not None

        async with self._pool.connection() as listen_conn:
            await listen_conn.set_autocommit(True)
            channel = f"{PGMQ_NOTIFY_CHANNEL}_{self._reply_queue}"
            await listen_conn.execute(f"LISTEN {channel}")
            logger.debug(f"Listening on channel {channel}")

            while not self._stop_event.is_set():
                await self._drain_queue(semaphore)
                if self._stop_event.is_set():
                    return

                try:
                    gen = listen_conn.notifies(timeout=poll_interval)
                    async for _ in gen:
                        break
                except TimeoutError:
                    pass

    async def _run_with_polling(
        self,
        semaphore: asyncio.Semaphore,
        poll_interval: float,
    ) -> None:
        assert self._stop_event is not None

        while not self._stop_event.is_set():
            await self._drain_queue(semaphore)
            if self._stop_event.is_set():
                return

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=poll_interval,
                )

    async def _drain_queue(self, semaphore: asyncio.Semaphore) -> None:
        assert self._stop_event is not None

        while not self._stop_event.is_set():
            available_slots = semaphore._value
            if available_slots == 0:
                await self._wait_for_slot()
                continue

            # Read messages
            async with self._pool.connection() as conn:
                messages = await self._pgmq.read(
                    self._reply_queue,
                    visibility_timeout=self._visibility_timeout,
                    batch_size=available_slots,
                    conn=conn,
                )

            if not messages:
                return

            for msg in messages:
                task = asyncio.create_task(self._process_message(msg, semaphore))
                self._in_flight.add(task)
                task.add_done_callback(self._in_flight.discard)

            await asyncio.sleep(0)

    async def _wait_for_slot(self) -> None:
        if not self._in_flight:
            return
        _done, _ = await asyncio.wait(
            self._in_flight,
            return_when=asyncio.FIRST_COMPLETED,
        )

    async def _process_message(
        self,
        msg: Any,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            try:
                await self._dispatch_reply(msg)
            except Exception:
                logger.exception(f"Error processing reply message {msg.msg_id}")
                # Leave message for retry (visibility timeout)

    async def _dispatch_reply(self, msg: Any) -> None:
        """Process a single reply message transactionally."""
        msg_id = msg.msg_id
        message = msg.message

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

        async with self._pool.connection() as conn, conn.transaction():
            if reply.correlation_id is None:
                logger.warning(f"Reply {msg_id} has no correlation_id, discarding")
                await self._pgmq.delete(self._reply_queue, msg_id, conn=conn)
                return

            # Look up process by correlation_id (which is process_id)
            process = await self._process_repo.get_by_id(
                # We need to know the domain to fetch the process.
                # The schema has composite PK (domain, process_id).
                # We assume the router is initialized for a specific domain.
                self._domain,
                reply.correlation_id,
                conn=conn,
            )

            if process is None:
                logger.warning(f"Reply for unknown process {reply.correlation_id}, discarding")
                await self._pgmq.delete(self._reply_queue, msg_id, conn=conn)
                return

            manager = self._managers.get(process.process_type)
            if manager is None:
                logger.error(f"No manager for process type {process.process_type}, discarding")
                await self._pgmq.delete(self._reply_queue, msg_id, conn=conn)
                return

            # Dispatch to manager (updates process state and sends next command)
            await manager.handle_reply(reply, process, conn=conn)

            # Delete message (atomically with process update)
            await self._pgmq.delete(self._reply_queue, msg_id, conn=conn)
