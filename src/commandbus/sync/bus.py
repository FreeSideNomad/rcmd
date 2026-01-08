"""Blocking wrapper for CommandBus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from commandbus.bus import CommandBus
from commandbus.sync.config import get_default_runtime

if TYPE_CHECKING:
    from commandbus.models import (
        BatchMetadata,
        BatchSendResult,
        CommandMetadata,
        CreateBatchResult,
        SendRequest,
        SendResult,
    )
    from commandbus.sync.runtime import SyncRuntime


class SyncCommandBus:
    """Synchronous façade over :class:`commandbus.bus.CommandBus`."""

    def __init__(
        self,
        *args: Any,
        bus: CommandBus | None = None,
        runtime: SyncRuntime | None = None,
        **kwargs: Any,
    ) -> None:
        if bus is None and not args and not kwargs:
            raise ValueError("SyncCommandBus requires a CommandBus or constructor arguments")
        self._bus = bus or CommandBus(*args, **kwargs)
        self._runtime = get_default_runtime(runtime)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._bus, item)

    def send(self, *args: Any, **kwargs: Any) -> SendResult:
        """Send a command using blocking semantics."""
        return self._runtime.run(self._bus.send(*args, **kwargs))

    def send_batch(self, requests: list[SendRequest], **kwargs: Any) -> BatchSendResult:
        return self._runtime.run(self._bus.send_batch(requests, **kwargs))

    def get_command(self, *args: Any, **kwargs: Any) -> CommandMetadata | None:
        return self._runtime.run(self._bus.get_command(*args, **kwargs))

    def command_exists(self, *args: Any, **kwargs: Any) -> bool:
        return self._runtime.run(self._bus.command_exists(*args, **kwargs))

    def get_audit_trail(self, *args: Any, **kwargs: Any) -> list[Any]:
        return self._runtime.run(self._bus.get_audit_trail(*args, **kwargs))

    def query_commands(self, *args: Any, **kwargs: Any) -> list[CommandMetadata]:
        return self._runtime.run(self._bus.query_commands(*args, **kwargs))

    def create_batch(self, *args: Any, **kwargs: Any) -> CreateBatchResult:
        return self._runtime.run(self._bus.create_batch(*args, **kwargs))

    def get_batch(self, *args: Any, **kwargs: Any) -> BatchMetadata | None:
        return self._runtime.run(self._bus.get_batch(*args, **kwargs))

    def list_batches(self, *args: Any, **kwargs: Any) -> list[BatchMetadata]:
        return self._runtime.run(self._bus.list_batches(*args, **kwargs))

    def list_batch_commands(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> list[CommandMetadata]:
        return self._runtime.run(self._bus.list_batch_commands(*args, **kwargs))
