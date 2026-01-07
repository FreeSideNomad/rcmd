from datetime import datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from psycopg import AsyncConnection

from commandbus.models import ReplyOutcome
from commandbus.process import (
    PostgresProcessRepository,
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessStatus,
)


@pytest.fixture
def mock_pool():
    pool = Mock()
    conn_ctx = AsyncMock()
    conn = Mock()  # Use Mock instead of AsyncMock
    conn.execute = AsyncMock()  # Explicitly make execute async
    conn_ctx.__aenter__.return_value = conn
    pool.connection.return_value = conn_ctx

    # Mock cursor() - returns async context manager
    cursor_ctx = AsyncMock()
    conn.cursor.return_value = cursor_ctx

    return pool


@pytest.fixture
def repo(mock_pool):
    return PostgresProcessRepository(mock_pool)


@pytest.mark.asyncio
async def test_save(repo, mock_pool):
    process = ProcessMetadata(
        domain="d",
        process_id=uuid4(),
        process_type="t",
        state={"foo": "bar"},
        status=ProcessStatus.PENDING,
    )

    await repo.save(process)

    conn = mock_pool.connection.return_value.__aenter__.return_value
    assert conn.execute.called
    args = conn.execute.call_args[0]
    assert "INSERT INTO commandbus.process" in args[0]
    assert args[1][0] == "d"  # domain
    assert args[1][5] == {"foo": "bar"}  # state


@pytest.mark.asyncio
async def test_save_with_conn(repo, mock_pool):
    process = ProcessMetadata(
        domain="d",
        process_id=uuid4(),
        process_type="t",
        state={"foo": "bar"},
        status=ProcessStatus.PENDING,
    )

    conn = AsyncMock(spec=AsyncConnection)
    await repo.save(process, conn=conn)

    assert conn.execute.called
    args = conn.execute.call_args[0]
    assert "INSERT INTO commandbus.process" in args[0]
    # Pool connection NOT used
    assert not mock_pool.connection.called


@pytest.mark.asyncio
async def test_get_by_id(repo, mock_pool):
    pid = uuid4()
    conn = mock_pool.connection.return_value.__aenter__.return_value
    # Get the cursor mock from our setup
    cursor_ctx = conn.cursor.return_value
    cursor = AsyncMock()
    cursor_ctx.__aenter__.return_value = cursor

    # Mock row
    cursor.fetchone.return_value = (
        "d",
        pid,
        "t",
        "PENDING",
        None,
        {"foo": "bar"},
        None,
        None,
        datetime.now(),
        datetime.now(),
        None,
    )

    process = await repo.get_by_id("d", pid)

    assert process is not None
    assert process.process_id == pid
    assert process.state == {"foo": "bar"}


@pytest.mark.asyncio
async def test_update(repo, mock_pool):
    process = ProcessMetadata(
        domain="d",
        process_id=uuid4(),
        process_type="t",
        state={"foo": "baz"},
        status=ProcessStatus.IN_PROGRESS,
    )

    await repo.update(process)

    conn = mock_pool.connection.return_value.__aenter__.return_value
    assert conn.execute.called
    args = conn.execute.call_args[0]
    assert "UPDATE commandbus.process" in args[0]
    assert args[1][2] == {"foo": "baz"}  # state


@pytest.mark.asyncio
async def test_log_step(repo, mock_pool):
    pid = uuid4()
    entry = ProcessAuditEntry(
        step_name="step1",
        command_id=uuid4(),
        command_type="cmd",
        command_data={},
        sent_at=datetime.now(),
    )

    await repo.log_step("d", pid, entry)

    conn = mock_pool.connection.return_value.__aenter__.return_value
    assert conn.execute.called
    assert "INSERT INTO commandbus.process_audit" in conn.execute.call_args[0][0]


@pytest.mark.asyncio
async def test_find_by_status(repo, mock_pool):
    conn = mock_pool.connection.return_value.__aenter__.return_value
    cursor_ctx = conn.cursor.return_value
    cursor = AsyncMock()
    cursor_ctx.__aenter__.return_value = cursor

    # Mock rows
    pid = uuid4()
    cursor.fetchall.return_value = [
        ("d", pid, "t", "PENDING", None, {}, None, None, datetime.now(), datetime.now(), None)
    ]

    results = await repo.find_by_status("d", [ProcessStatus.PENDING])

    assert len(results) == 1
    assert results[0].process_id == pid
    assert results[0].status == ProcessStatus.PENDING


@pytest.mark.asyncio
async def test_update_step_reply(repo, mock_pool):
    pid = uuid4()
    cmd_id = uuid4()
    entry = ProcessAuditEntry(
        step_name="step1",
        command_id=cmd_id,
        command_type="cmd",
        command_data=None,
        sent_at=datetime.now(),
        reply_outcome=ReplyOutcome.SUCCESS,
        reply_data={"res": "ok"},
        received_at=datetime.now(),
    )

    await repo.update_step_reply("d", pid, cmd_id, entry)

    conn = mock_pool.connection.return_value.__aenter__.return_value
    assert conn.execute.called
    assert "UPDATE commandbus.process_audit" in conn.execute.call_args[0][0]


@pytest.mark.asyncio
async def test_get_audit_trail(repo, mock_pool):
    pid = uuid4()
    conn = mock_pool.connection.return_value.__aenter__.return_value
    cursor_ctx = conn.cursor.return_value
    cursor = AsyncMock()
    cursor_ctx.__aenter__.return_value = cursor

    cmd_id = uuid4()
    cursor.fetchall.return_value = [
        ("step1", cmd_id, "cmd", {}, datetime.now(), "SUCCESS", {}, datetime.now())
    ]

    trail = await repo.get_audit_trail("d", pid)

    assert len(trail) == 1
    assert trail[0].command_id == cmd_id
    assert trail[0].reply_outcome == ReplyOutcome.SUCCESS


@pytest.mark.asyncio
async def test_get_completed_steps(repo, mock_pool):
    pid = uuid4()
    conn = mock_pool.connection.return_value.__aenter__.return_value
    cursor_ctx = conn.cursor.return_value
    cursor = AsyncMock()
    cursor_ctx.__aenter__.return_value = cursor

    cursor.fetchall.return_value = [("step1",), ("step2",)]

    steps = await repo.get_completed_steps("d", pid)

    assert len(steps) == 2
    assert steps == ["step1", "step2"]
