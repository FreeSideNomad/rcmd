"""Background event loop runner used by synchronous wrappers."""

from __future__ import annotations

import asyncio
import atexit
import threading
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Coroutine, Iterable
    from concurrent.futures import Future

T = TypeVar("T")


class SyncRuntime:
    """Runs async coroutines on a dedicated event loop thread."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="commandbus-sync-runtime",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self.shutdown)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, awaitable: Awaitable[T]) -> T:
        """Execute a coroutine synchronously and return its result."""
        if self._closed.is_set():
            raise RuntimeError("SyncRuntime has been shut down")

        coroutine: Coroutine[Any, Any, T]
        if asyncio.iscoroutine(awaitable):
            coroutine = awaitable
        else:

            async def _wrap() -> T:
                return await awaitable

            coroutine = _wrap()

        future: Future[T] = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result()

    def run_many(self, coroutines: Iterable[Awaitable[Any]]) -> list[Any]:
        """Execute multiple coroutines sequentially and return their results."""

        async def _gather() -> list[Any]:
            return await asyncio.gather(*coroutines)

        return self.run(_gather())

    def shutdown(self) -> None:
        """Stop the loop thread and release resources."""
        if self._closed.is_set():
            return
        self._closed.set()

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if not self._loop.is_closed():
            self._loop.close()
