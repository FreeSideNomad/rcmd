"""Blocking worker wrapper."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from commandbus.sync.config import get_default_runtime, get_thread_pool_size
from commandbus.worker import Worker

if TYPE_CHECKING:
    from concurrent.futures import Future

    from commandbus.sync.runtime import SyncRuntime


class SyncWorker:
    """Synchronous adapter for :class:`commandbus.worker.Worker`."""

    def __init__(
        self,
        *args: Any,
        worker: Worker | None = None,
        runtime: SyncRuntime | None = None,
        thread_pool_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        if worker is None and not args and not kwargs:
            raise ValueError("SyncWorker requires a Worker or constructor arguments")
        self._worker = worker or Worker(*args, **kwargs)
        self._runtime = get_default_runtime(runtime)
        self._executor = ThreadPoolExecutor(max_workers=get_thread_pool_size(thread_pool_size))
        self._future_lock = threading.Lock()
        self._run_future: Future[None] | None = None

    def run(
        self,
        *,
        block: bool = True,
        concurrency: int = 1,
        poll_interval: float = 1.0,
        use_notify: bool = True,
    ) -> None:
        """Start the worker loop in a background thread."""

        def _target() -> None:
            self._runtime.run(
                self._worker.run(
                    concurrency=concurrency,
                    poll_interval=poll_interval,
                    use_notify=use_notify,
                )
            )

        with self._future_lock:
            if self._run_future is not None and not self._run_future.done():
                raise RuntimeError("Worker is already running")
            self._run_future = self._executor.submit(_target)

        if block:
            self._run_future.result()

    def stop(self, *, timeout: float | None = None) -> None:
        """Signal the worker to stop and wait for completion."""
        self._runtime.run(self._worker.stop(timeout=timeout))
        with self._future_lock:
            future = self._run_future
        if future is not None:
            future.result(timeout)

    def shutdown(self) -> None:
        """Stop the worker (if running) and release resources."""
        with self._future_lock:
            future = self._run_future
        if future is not None and not future.done():
            self.stop()
        self._executor.shutdown(wait=True)
