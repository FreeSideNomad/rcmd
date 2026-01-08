"""Blocking wrapper for TroubleshootingQueue."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.sync.config import get_default_runtime

if TYPE_CHECKING:
    from uuid import UUID

    from commandbus.models import TroubleshootingItem
    from commandbus.sync.runtime import SyncRuntime


class SyncTroubleshootingQueue:
    """Synchronous façade for :class:`commandbus.ops.troubleshooting.TroubleshootingQueue`."""

    def __init__(
        self,
        *args: Any,
        queue: TroubleshootingQueue | None = None,
        runtime: SyncRuntime | None = None,
        **kwargs: Any,
    ) -> None:
        if queue is None and not args and not kwargs:
            raise ValueError("SyncTroubleshootingQueue requires a queue or constructor arguments")
        self._queue = queue or TroubleshootingQueue(*args, **kwargs)
        self._runtime = get_default_runtime(runtime)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._queue, item)

    def list_troubleshooting(
        self,
        domain: str,
        command_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TroubleshootingItem]:
        return self._runtime.run(
            self._queue.list_troubleshooting(
                domain=domain,
                command_type=command_type,
                limit=limit,
                offset=offset,
            )
        )

    def list_domains(self) -> list[str]:
        return self._runtime.run(self._queue.list_domains())

    def get_command_domain(self, command_id: UUID) -> str:
        return self._runtime.run(self._queue.get_command_domain(command_id))

    def list_all_troubleshooting(
        self,
        limit: int = 50,
        offset: int = 0,
        domain: str | None = None,
    ) -> tuple[list[TroubleshootingItem], int, list[UUID]]:
        return self._runtime.run(
            self._queue.list_all_troubleshooting(
                limit=limit,
                offset=offset,
                domain=domain,
            )
        )

    def list_command_ids(self, domain: str | None = None) -> list[UUID]:
        return self._runtime.run(self._queue.list_command_ids(domain))

    def count_troubleshooting(self, domain: str, command_type: str | None = None) -> int:
        return self._runtime.run(self._queue.count_troubleshooting(domain, command_type))

    def operator_retry(self, *args: Any, **kwargs: Any) -> None:
        self._runtime.run(self._queue.operator_retry(*args, **kwargs))

    def operator_cancel(self, *args: Any, **kwargs: Any) -> None:
        self._runtime.run(self._queue.operator_cancel(*args, **kwargs))

    def operator_complete(self, *args: Any, **kwargs: Any) -> None:
        self._runtime.run(self._queue.operator_complete(*args, **kwargs))
