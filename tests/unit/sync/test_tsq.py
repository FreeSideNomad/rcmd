from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from commandbus.models import TroubleshootingItem
from commandbus.sync.runtime import SyncRuntime
from commandbus.sync.tsq import SyncTroubleshootingQueue


@pytest.fixture()
def runtime() -> SyncRuntime:
    rt = SyncRuntime()
    yield rt
    rt.shutdown()


def test_sync_tsq_delegates(runtime: SyncRuntime) -> None:
    queue = MagicMock()
    item = TroubleshootingItem(
        domain="e2e",
        command_id=uuid4(),
        command_type="Test",
        attempts=1,
        max_attempts=3,
        last_error_type=None,
        last_error_code=None,
        last_error_msg=None,
        correlation_id=None,
        reply_to=None,
        payload=None,
        created_at=None,
        updated_at=None,
    )
    queue.list_troubleshooting = AsyncMock(return_value=[item])
    queue.list_domains = AsyncMock(return_value=["e2e"])
    queue.list_all_troubleshooting = AsyncMock(return_value=([item], 1, [item.command_id]))
    queue.list_command_ids = AsyncMock(return_value=[item.command_id])
    queue.operator_retry = AsyncMock(return_value=None)

    sync_queue = SyncTroubleshootingQueue(queue=queue, runtime=runtime)

    assert sync_queue.list_troubleshooting(domain="e2e") == [item]
    assert sync_queue.list_domains() == ["e2e"]
    assert sync_queue.list_all_troubleshooting() == ([item], 1, [item.command_id])
    assert sync_queue.list_command_ids() == [item.command_id]
    sync_queue.operator_retry(domain="e2e", command_id=item.command_id)

    queue.operator_retry.assert_awaited_once()
