import asyncio
import itertools
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from commandbus.models import Reply, ReplyOutcome
from commandbus.pgmq.client import PgmqMessage
from commandbus.process import (
    BaseProcessManager,
    ProcessMetadata,
    ProcessReplyRouter,
    ProcessStatus,
)


@pytest.fixture
def mock_pool():
    pool = Mock()
    conn_ctx = AsyncMock()
    conn = Mock()  # Use Mock to avoid AsyncMock side effects on sync methods
    conn.execute = AsyncMock()  # Needed for LISTEN
    conn.set_autocommit = AsyncMock()  # Needed for notify listener
    conn_ctx.__aenter__.return_value = conn
    pool.connection.return_value = conn_ctx

    # Mock transaction() - returns async context manager
    trans_ctx = AsyncMock()
    # Explicitly make transaction() a Mock (sync) that returns the context manager
    conn.transaction = Mock(return_value=trans_ctx)

    # Mock notifies() - returns async iterator that sleeps
    async def async_iter(*args, timeout=None, **kwargs):
        if timeout is not None:
            # Sleep to simulate waiting for notification
            # We use a very short sleep for tests to be fast but yield control
            await asyncio.sleep(0.001)
        if False:
            yield  # Empty generator

    conn.notifies = Mock(side_effect=async_iter)

    return pool


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def mock_manager():
    manager = AsyncMock(spec=BaseProcessManager)
    return manager


@pytest.fixture
def router(mock_pool, mock_repo, mock_manager):
    managers = {"test_process": mock_manager}
    with patch("commandbus.process.router.PgmqClient") as MockPgmq:
        mock_pgmq = MockPgmq.return_value
        mock_pgmq.read = AsyncMock(return_value=[])
        mock_pgmq.delete = AsyncMock()

        router = ProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_repo,
            managers=managers,
            reply_queue="replies",
            domain="test",
        )
        # Verify pgmq was set on router
        assert router._pgmq == mock_pgmq
        return router


@pytest.mark.asyncio
async def test_run_and_stop(router):
    task = asyncio.create_task(router.run(poll_interval=0.01))
    await asyncio.sleep(0.02)
    assert router.is_running
    await router.stop()
    await task
    assert not router.is_running


@pytest.mark.asyncio
async def test_process_message_dispatch(router, mock_repo, mock_manager):
    # Setup message
    process_id = uuid4()
    msg = PgmqMessage(
        msg_id=1,
        read_count=1,
        enqueued_at="now",
        vt="now",
        message={
            "command_id": str(uuid4()),
            "correlation_id": str(process_id),
            "outcome": "SUCCESS",
            "result": {"foo": "bar"},
        },
    )

    # Setup mocks
    router._pgmq.read.side_effect = itertools.chain([[msg]], itertools.repeat([]))

    process = ProcessMetadata(
        domain="test",
        process_id=process_id,
        process_type="test_process",
        state={},
        status=ProcessStatus.IN_PROGRESS,
    )
    mock_repo.get_by_id.return_value = process

    # Run router briefly
    task = asyncio.create_task(router.run(poll_interval=0.01))
    await asyncio.sleep(0.05)
    await router.stop()
    await task

    # Verify
    assert mock_repo.get_by_id.called
    assert mock_manager.handle_reply.called
    assert router._pgmq.delete.called

    # Verify handle_reply args
    call_args = mock_manager.handle_reply.call_args
    reply_arg = call_args[0][0]
    assert isinstance(reply_arg, Reply)
    assert reply_arg.outcome == ReplyOutcome.SUCCESS
    assert reply_arg.data == {"foo": "bar"}


@pytest.mark.asyncio
async def test_process_message_unknown_process(router, mock_repo, mock_manager):
    # Setup message
    msg = PgmqMessage(
        msg_id=1,
        read_count=1,
        enqueued_at="now",
        vt="now",
        message={"command_id": str(uuid4()), "correlation_id": str(uuid4()), "outcome": "SUCCESS"},
    )

    router._pgmq.read.side_effect = itertools.chain([[msg]], itertools.repeat([]))
    mock_repo.get_by_id.return_value = None

    task = asyncio.create_task(router.run(poll_interval=0.01))
    await asyncio.sleep(0.05)
    await router.stop()
    await task

    assert mock_repo.get_by_id.called
    assert not mock_manager.handle_reply.called
    # Message should be deleted (discarded)
    assert router._pgmq.delete.called


@pytest.mark.asyncio
async def test_process_message_no_manager(router, mock_repo, mock_manager):
    # Setup message
    process_id = uuid4()
    msg = PgmqMessage(
        msg_id=1,
        read_count=1,
        enqueued_at="now",
        vt="now",
        message={
            "command_id": str(uuid4()),
            "correlation_id": str(process_id),
            "outcome": "SUCCESS",
        },
    )

    router._pgmq.read.side_effect = itertools.chain([[msg]], itertools.repeat([]))

    process = ProcessMetadata(
        domain="test",
        process_id=process_id,
        process_type="unknown_type",
        state={},
        status=ProcessStatus.IN_PROGRESS,
    )
    mock_repo.get_by_id.return_value = process

    task = asyncio.create_task(router.run(poll_interval=0.01))
    await asyncio.sleep(0.05)
    await router.stop()
    await task

    assert mock_repo.get_by_id.called
    assert not mock_manager.handle_reply.called
    # Message should be deleted (discarded)
    assert router._pgmq.delete.called


@pytest.mark.asyncio
async def test_process_message_missing_correlation_id(router, mock_repo):
    # Setup message without correlation_id
    msg = PgmqMessage(
        msg_id=1,
        read_count=1,
        enqueued_at="now",
        vt="now",
        message={"command_id": str(uuid4()), "outcome": "SUCCESS"},
    )

    router._pgmq.read.side_effect = itertools.chain([[msg]], itertools.repeat([]))

    task = asyncio.create_task(router.run(poll_interval=0.01))
    await asyncio.sleep(0.05)
    await router.stop()
    await task

    assert not mock_repo.get_by_id.called
    # Message should be deleted (discarded)
    assert router._pgmq.delete.called


@pytest.mark.asyncio
async def test_run_polling(router):
    # Test run with polling (use_notify=False)
    task = asyncio.create_task(router.run(poll_interval=0.01, use_notify=False))
    await asyncio.sleep(0.02)
    assert router.is_running
    await router.stop()
    await task
    assert not router.is_running
