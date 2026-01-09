"""Blocking wrapper for ProcessReplyRouter."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from commandbus.process.router import ProcessReplyRouter
from commandbus.sync.config import get_default_runtime, get_thread_pool_size

if TYPE_CHECKING:
    from concurrent.futures import Future

    from commandbus.sync.runtime import SyncRuntime


logger = logging.getLogger(__name__)


class SyncProcessReplyRouter:
    """Synchronous adapter for :class:`commandbus.process.router.ProcessReplyRouter`."""

    def __init__(
        self,
        *args: Any,
        router: ProcessReplyRouter | None = None,
        runtime: SyncRuntime | None = None,
        thread_pool_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        if router is None and not args and not kwargs:
            raise ValueError("SyncProcessReplyRouter requires a router or constructor arguments")
        self._router = router or ProcessReplyRouter(*args, **kwargs)
        self._runtime = get_default_runtime(runtime)
        self._executor = ThreadPoolExecutor(max_workers=get_thread_pool_size(thread_pool_size))
        self._future_lock = threading.Lock()
        self._run_future: Future[None] | None = None

    def __getattr__(self, item: str) -> Any:
        return getattr(self._router, item)

    def run(
        self,
        *,
        block: bool = True,
        concurrency: int = 10,
        poll_interval: float = 1.0,
        use_notify: bool = True,
    ) -> None:
        """Start the reply router loop."""

        def _target() -> None:
            try:
                self._runtime.run(
                    self._router.run(
                        concurrency=concurrency,
                        poll_interval=poll_interval,
                        use_notify=use_notify,
                    )
                )
            except Exception:
                logger.exception("Sync wrapper for reply router crashed")
                raise

        with self._future_lock:
            if self._run_future is not None and not self._run_future.done():
                raise RuntimeError("Process router is already running")
            self._run_future = self._executor.submit(_target)

        if block:
            self._run_future.result()

    def stop(self, *, timeout: float | None = None) -> None:
        """Stop the router and wait for threads to exit."""
        self._runtime.run(self._router.stop(timeout=timeout))
        with self._future_lock:
            future = self._run_future
        if future is not None:
            future.result(timeout)

    def shutdown(self) -> None:
        """Stop the router (if running) and cleanup the executor."""
        with self._future_lock:
            future = self._run_future
        if future is not None and not future.done():
            self.stop()
        self._executor.shutdown(wait=True)

    @property
    def reply_queue(self) -> str:
        """Expose wrapped router reply queue."""
        return self._router.reply_queue

    @property
    def domain(self) -> str:
        """Expose wrapped router domain."""
        return self._router.domain
