from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.models import BatchMetadata, BatchSendResult, SendRequest, SendResult
from commandbus.sync.bus import SyncCommandBus
from commandbus.sync.runtime import SyncRuntime


def test_sync_bus_delegates_calls() -> None:
    runtime = SyncRuntime()
    bus = MagicMock()
    bus.send = AsyncMock(return_value=SendResult(command_id=uuid4(), msg_id=1))
    bus.send_batch = AsyncMock(
        return_value=BatchSendResult(results=[], chunks_processed=0, total_commands=0)
    )
    sync_bus = SyncCommandBus(bus=bus, runtime=runtime)

    send_result = sync_bus.send(domain="e2e", command_type="Test", command_id=uuid4(), data={})
    batch_result = sync_bus.send_batch(
        [SendRequest(domain="e2e", command_type="Test", command_id=uuid4(), data={})]
    )

    assert isinstance(send_result, SendResult)
    assert batch_result.total_commands == 0
    bus.send.assert_awaited_once()
    bus.send_batch.assert_awaited_once()
    runtime.shutdown()


def test_sync_bus_supports_constructor_args() -> None:
    runtime = SyncRuntime()
    with patch("commandbus.sync.bus.CommandBus.__init__", return_value=None) as ctor:
        SyncCommandBus("pool", runtime=runtime)  # type: ignore[arg-type]
        ctor.assert_called_once()
    runtime.shutdown()


def test_sync_bus_wraps_metadata_queries() -> None:
    runtime = SyncRuntime()
    bus = MagicMock()
    metadata = BatchMetadata(domain="e2e", batch_id=uuid4())
    bus.get_batch = AsyncMock(return_value=metadata)
    bus.list_batches = AsyncMock(return_value=[metadata])
    bus.list_batch_commands = AsyncMock(return_value=[])
    sync_bus = SyncCommandBus(bus=bus, runtime=runtime)

    assert sync_bus.get_batch("e2e", metadata.batch_id) == metadata
    assert sync_bus.list_batches(domain="e2e") == [metadata]
    assert sync_bus.list_batch_commands(domain="e2e", batch_id=metadata.batch_id) == []
    runtime.shutdown()


def test_sync_bus_requires_target() -> None:
    runtime = SyncRuntime()
    with pytest.raises(ValueError):
        SyncCommandBus(runtime=runtime)
    runtime.shutdown()


def test_sync_bus_getattr_passthrough() -> None:
    runtime = SyncRuntime()
    bus = MagicMock()
    bus.some_attr = "ok"
    sync_bus = SyncCommandBus(bus=bus, runtime=runtime)
    assert sync_bus.some_attr == "ok"
    runtime.shutdown()
