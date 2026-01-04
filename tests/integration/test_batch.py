"""Integration tests for batch creation functionality."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus import (
    BatchCommand,
    BatchNotFoundError,
    BatchStatus,
    CommandBus,
    CommandStatus,
    DuplicateCommandError,
)
from commandbus.batch import clear_all_callbacks
from commandbus.exceptions import PermanentCommandError
from commandbus.handler import HandlerRegistry
from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.worker import Worker


@pytest.mark.asyncio
class TestCreateBatchAtomic:
    """Integration tests for atomic batch creation."""

    async def test_create_batch_stores_batch_and_commands(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that batch and all commands are stored atomically."""
        batch_id = uuid4()
        cmd1_id = uuid4()
        cmd2_id = uuid4()
        cmd3_id = uuid4()

        result = await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd1_id,
                    data={"account_id": "123", "amount": 100},
                ),
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd2_id,
                    data={"account_id": "456", "amount": 200},
                ),
                BatchCommand(
                    command_type="CreditAccount",
                    command_id=cmd3_id,
                    data={"account_id": "789", "amount": 300},
                ),
            ],
            batch_id=batch_id,
            name="Monthly billing run",
        )

        assert result.batch_id == batch_id
        assert result.total_commands == 3
        assert len(result.command_results) == 3

        # Verify batch is in database
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.batch_id == batch_id
        assert batch.domain == "payments"
        assert batch.name == "Monthly billing run"
        assert batch.status == BatchStatus.PENDING
        assert batch.total_count == 3
        assert batch.completed_count == 0
        assert batch.failed_count == 0
        assert batch.canceled_count == 0
        assert batch.in_troubleshooting_count == 0

        # Verify commands are in database with batch_id set
        for cmd_id in [cmd1_id, cmd2_id, cmd3_id]:
            cmd = await command_bus.get_command("payments", cmd_id)
            assert cmd is not None
            assert cmd.batch_id == batch_id
            assert cmd.status == CommandStatus.PENDING

    async def test_create_batch_with_custom_data(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that custom metadata is stored correctly."""
        batch_id = uuid4()
        custom = {"source": "csv", "file_id": "abc123", "row_count": 100}

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=uuid4(),
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
            name="Import job 12345",
            custom_data=custom,
        )

        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.name == "Import job 12345"
        assert batch.custom_data == custom

    async def test_create_batch_generates_batch_id(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that batch_id is auto-generated if not provided."""
        result = await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=uuid4(),
                    data={},
                ),
            ],
        )

        assert result.batch_id is not None
        batch = await command_bus.get_batch("payments", result.batch_id)
        assert batch is not None

    async def test_create_batch_messages_queued(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that messages are queued in PGMQ."""
        result = await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=uuid4(),
                    data={"account_id": "123"},
                )
                for _ in range(3)
            ],
        )

        assert result.total_commands == 3

        # Check messages are in PGMQ queue
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM pgmq.q_payments__commands")
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == 3

    async def test_create_batch_audit_events(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that SENT audit events are recorded with batch_id."""
        batch_id = uuid4()
        cmd_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={},
                ),
            ],
            batch_id=batch_id,
        )

        events = await command_bus.get_audit_trail(cmd_id)
        assert len(events) == 1
        assert events[0].event_type == "SENT"
        assert events[0].details is not None
        assert events[0].details.get("batch_id") == str(batch_id)


@pytest.mark.asyncio
class TestCreateBatchDuplicateRollback:
    """Tests for atomicity - rollback on duplicate."""

    async def test_duplicate_command_id_in_batch_rollback(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that duplicate command_id in batch causes rollback."""
        cmd_id = uuid4()

        with pytest.raises(DuplicateCommandError):
            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(
                        command_type="DebitAccount",
                        command_id=cmd_id,
                        data={},
                    ),
                    BatchCommand(
                        command_type="DebitAccount",
                        command_id=cmd_id,  # duplicate
                        data={},
                    ),
                ],
            )

    async def test_duplicate_existing_command_rollback(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that duplicate against existing command causes rollback."""
        existing_id = uuid4()
        batch_id = uuid4()

        # Create a command first
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=existing_id,
            data={},
        )

        # Try to create batch with that command ID
        with pytest.raises(DuplicateCommandError):
            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(
                        command_type="DebitAccount",
                        command_id=uuid4(),
                        data={},
                    ),
                    BatchCommand(
                        command_type="DebitAccount",
                        command_id=existing_id,  # exists in DB
                        data={},
                    ),
                ],
                batch_id=batch_id,
            )

        # Batch should not exist
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is None


@pytest.mark.asyncio
class TestBatchGetAndList:
    """Tests for batch retrieval operations."""

    async def test_get_batch_returns_metadata(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that get_batch returns full metadata."""
        batch_id = uuid4()
        custom = {"key": "value"}

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="Cmd",
                    command_id=uuid4(),
                    data={},
                )
                for _ in range(5)
            ],
            batch_id=batch_id,
            name="Test Batch",
            custom_data=custom,
        )

        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.batch_id == batch_id
        assert batch.domain == "payments"
        assert batch.name == "Test Batch"
        assert batch.custom_data == custom
        assert batch.status == BatchStatus.PENDING
        assert batch.total_count == 5
        assert batch.created_at is not None

    async def test_get_batch_returns_none_for_nonexistent(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that get_batch returns None for non-existent batch."""
        batch = await command_bus.get_batch("payments", uuid4())
        assert batch is None

    async def test_get_batch_domain_scoped(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that get_batch is domain-scoped."""
        batch_id = uuid4()

        # Create queue for orders domain
        async with pool.connection() as conn:
            await conn.execute("SELECT pgmq.create('orders__commands')")
            await conn.execute("SELECT pgmq.create('orders__replies')")

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="Cmd",
                    command_id=uuid4(),
                    data={},
                ),
            ],
            batch_id=batch_id,
        )

        # Same batch_id but different domain should return None
        batch = await command_bus.get_batch("orders", batch_id)
        assert batch is None

        # Correct domain should return batch
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None


@pytest.mark.asyncio
class TestBatchCommandMetadata:
    """Tests for command metadata in batches."""

    async def test_command_has_batch_id(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that commands in batch have batch_id set."""
        batch_id = uuid4()
        cmd_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={},
                ),
            ],
            batch_id=batch_id,
        )

        cmd = await command_bus.get_command("payments", cmd_id)
        assert cmd is not None
        assert cmd.batch_id == batch_id

    async def test_regular_command_no_batch_id(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that regular commands have no batch_id."""
        cmd_id = uuid4()

        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=cmd_id,
            data={},
        )

        cmd = await command_bus.get_command("payments", cmd_id)
        assert cmd is not None
        assert cmd.batch_id is None

    async def test_command_max_attempts_inherited(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that commands inherit max_attempts from BatchCommand or default."""
        batch_id = uuid4()
        cmd1_id = uuid4()
        cmd2_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="Cmd",
                    command_id=cmd1_id,
                    data={},
                    # uses default
                ),
                BatchCommand(
                    command_type="Cmd",
                    command_id=cmd2_id,
                    data={},
                    max_attempts=5,  # override
                ),
            ],
            batch_id=batch_id,
        )

        cmd1 = await command_bus.get_command("payments", cmd1_id)
        assert cmd1 is not None
        assert cmd1.max_attempts == 3  # default

        cmd2 = await command_bus.get_command("payments", cmd2_id)
        assert cmd2 is not None
        assert cmd2.max_attempts == 5  # overridden


@pytest.mark.asyncio
class TestBatchStatusTracking:
    """Integration tests for batch status tracking (S042)."""

    async def test_batch_transitions_to_in_progress_on_receive(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that batch status changes from PENDING to IN_PROGRESS on first receive."""
        batch_id = uuid4()
        cmd_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
        )

        # Verify initial status
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.PENDING
        assert batch.started_at is None

        # Receive the command via worker
        worker = Worker(pool, domain="payments")
        received = await worker.receive(batch_size=1)
        assert len(received) == 1

        # Verify batch is now IN_PROGRESS
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.IN_PROGRESS
        assert batch.started_at is not None

    async def test_batch_completed_count_increments_on_complete(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that completed_count increments when command completes."""
        batch_id = uuid4()
        cmd_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
        )

        # Create worker with a handler
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)

        # Receive and complete command
        received = await worker.receive(batch_size=1)
        assert len(received) == 1
        await worker.complete(received[0], result={"processed": True})

        # Verify batch counters
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.COMPLETED
        assert batch.completed_count == 1
        assert batch.completed_at is not None

    async def test_batch_tsq_count_increments_on_permanent_failure(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that in_troubleshooting_count increments when command moves to TSQ."""
        batch_id = uuid4()
        cmd_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
        )

        # Create worker
        worker = Worker(pool, domain="payments")

        # Receive command
        received = await worker.receive(batch_size=1)
        assert len(received) == 1

        # Fail permanently
        error = PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")
        await worker.fail_permanent(received[0], error)

        # Verify batch counters
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.in_troubleshooting_count == 1
        # Batch is not complete because command is in TSQ
        assert batch.status == BatchStatus.IN_PROGRESS

    async def test_batch_completes_when_all_commands_complete(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that batch transitions to COMPLETED when all commands complete."""
        batch_id = uuid4()
        cmd1_id = uuid4()
        cmd2_id = uuid4()
        cmd3_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd1_id,
                    data={"account_id": "123"},
                ),
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd2_id,
                    data={"account_id": "456"},
                ),
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd3_id,
                    data={"account_id": "789"},
                ),
            ],
            batch_id=batch_id,
        )

        # Create worker
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)

        # Receive and complete all commands
        for _ in range(3):
            received = await worker.receive(batch_size=1)
            assert len(received) == 1
            await worker.complete(received[0], result={"processed": True})

        # Verify batch is complete
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.COMPLETED
        assert batch.total_count == 3
        assert batch.completed_count == 3
        assert batch.completed_at is not None

    async def test_batch_completed_with_failures(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that batch transitions to COMPLETED_WITH_FAILURES when commands are canceled."""
        batch_id = uuid4()
        cmd1_id = uuid4()
        cmd2_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd1_id,
                    data={"account_id": "123"},
                ),
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd2_id,
                    data={"account_id": "456"},
                ),
            ],
            batch_id=batch_id,
        )

        # Create worker
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)

        # Complete first command
        received = await worker.receive(batch_size=1)
        await worker.complete(received[0], result={"processed": True})

        # Fail second command permanently
        received = await worker.receive(batch_size=1)
        error = PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")
        await worker.fail_permanent(received[0], error)

        # Verify batch is in progress with TSQ count
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.IN_PROGRESS
        assert batch.completed_count == 1
        assert batch.in_troubleshooting_count == 1

        # Cancel the command in TSQ
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_cancel("payments", cmd2_id, reason="Test cancel")

        # Verify batch is now COMPLETED_WITH_FAILURES
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.COMPLETED_WITH_FAILURES
        assert batch.completed_count == 1
        assert batch.canceled_count == 1
        assert batch.in_troubleshooting_count == 0
        assert batch.completed_at is not None

    async def test_operator_retry_decrements_tsq_count(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that operator retry decrements in_troubleshooting_count."""
        batch_id = uuid4()
        cmd_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
        )

        # Create worker
        worker = Worker(pool, domain="payments")

        # Receive and fail permanently
        received = await worker.receive(batch_size=1)
        error = PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")
        await worker.fail_permanent(received[0], error)

        # Verify TSQ count
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.in_troubleshooting_count == 1

        # Retry the command
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_retry("payments", cmd_id)

        # Verify TSQ count decremented
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.in_troubleshooting_count == 0

    async def test_operator_complete_updates_batch(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that operator complete decrements TSQ and increments completed."""
        batch_id = uuid4()
        cmd_id = uuid4()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
        )

        # Create worker
        worker = Worker(pool, domain="payments")

        # Receive and fail permanently
        received = await worker.receive(batch_size=1)
        error = PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")
        await worker.fail_permanent(received[0], error)

        # Verify initial state
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.in_troubleshooting_count == 1
        assert batch.completed_count == 0

        # Operator completes the command
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_complete("payments", cmd_id, result_data={"manual": True})

        # Verify batch is now complete
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.COMPLETED
        assert batch.completed_count == 1
        assert batch.in_troubleshooting_count == 0
        assert batch.completed_at is not None


@pytest.mark.asyncio
class TestBatchCompletionCallback:
    """Integration tests for batch completion callbacks (S043)."""

    async def test_callback_invoked_when_batch_completes(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that callback is invoked when batch completes."""
        clear_all_callbacks()

        batch_id = uuid4()
        cmd_id = uuid4()
        callback = AsyncMock()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
            on_complete=callback,
        )

        # Create worker
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)

        # Receive and complete command
        received = await worker.receive(batch_size=1)
        await worker.complete(received[0], result={"processed": True})

        # Callback should have been invoked
        callback.assert_called_once()
        batch_arg = callback.call_args[0][0]
        assert batch_arg.batch_id == batch_id
        assert batch_arg.status == BatchStatus.COMPLETED

        clear_all_callbacks()

    async def test_callback_invoked_on_tsq_complete(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that callback is invoked when operator completes TSQ item."""
        clear_all_callbacks()

        batch_id = uuid4()
        cmd_id = uuid4()
        callback = AsyncMock()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
            on_complete=callback,
        )

        # Create worker
        worker = Worker(pool, domain="payments")

        # Receive and fail permanently
        received = await worker.receive(batch_size=1)
        error = PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")
        await worker.fail_permanent(received[0], error)

        # Callback should not be invoked yet
        callback.assert_not_called()

        # Operator completes the command
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_complete("payments", cmd_id, result_data={"manual": True})

        # Callback should have been invoked
        callback.assert_called_once()
        batch_arg = callback.call_args[0][0]
        assert batch_arg.batch_id == batch_id
        assert batch_arg.status == BatchStatus.COMPLETED

        clear_all_callbacks()

    async def test_callback_invoked_on_tsq_cancel(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that callback is invoked when operator cancels TSQ item."""
        clear_all_callbacks()

        batch_id = uuid4()
        cmd_id = uuid4()
        callback = AsyncMock()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
            on_complete=callback,
        )

        # Create worker
        worker = Worker(pool, domain="payments")

        # Receive and fail permanently
        received = await worker.receive(batch_size=1)
        error = PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")
        await worker.fail_permanent(received[0], error)

        # Callback should not be invoked yet
        callback.assert_not_called()

        # Operator cancels the command
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_cancel("payments", cmd_id, reason="Test cancel")

        # Callback should have been invoked
        callback.assert_called_once()
        batch_arg = callback.call_args[0][0]
        assert batch_arg.batch_id == batch_id
        assert batch_arg.status == BatchStatus.COMPLETED_WITH_FAILURES

        clear_all_callbacks()

    async def test_callback_not_invoked_while_batch_in_progress(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that callback is not invoked while batch is still in progress."""
        clear_all_callbacks()

        batch_id = uuid4()
        cmd1_id = uuid4()
        cmd2_id = uuid4()
        callback = AsyncMock()

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd1_id,
                    data={"account_id": "123"},
                ),
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd2_id,
                    data={"account_id": "456"},
                ),
            ],
            batch_id=batch_id,
            on_complete=callback,
        )

        # Create worker
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)

        # Complete first command
        received = await worker.receive(batch_size=1)
        await worker.complete(received[0], result={"processed": True})

        # Callback should NOT be invoked - batch still has pending commands
        callback.assert_not_called()

        # Complete second command
        received = await worker.receive(batch_size=1)
        await worker.complete(received[0], result={"processed": True})

        # Now callback should be invoked
        callback.assert_called_once()

        clear_all_callbacks()

    async def test_callback_exception_does_not_propagate(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that callback exceptions are caught and don't affect the worker."""
        clear_all_callbacks()

        batch_id = uuid4()
        cmd_id = uuid4()
        callback = AsyncMock(side_effect=ValueError("Callback failed!"))

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"account_id": "123"},
                ),
            ],
            batch_id=batch_id,
            on_complete=callback,
        )

        # Create worker
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)

        # Receive and complete command - should not raise
        received = await worker.receive(batch_size=1)
        await worker.complete(received[0], result={"processed": True})

        # Callback was called (and failed)
        callback.assert_called_once()

        # Batch should still be marked as complete
        batch = await command_bus.get_batch("payments", batch_id)
        assert batch is not None
        assert batch.status == BatchStatus.COMPLETED

        clear_all_callbacks()


@pytest.mark.asyncio
class TestBatchQueries:
    """Integration tests for S044: Query Batches and Their Commands."""

    async def test_list_batches(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test list_batches returns all batches for a domain."""
        batch_ids = []
        for i in range(5):
            result = await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(
                        command_type="DebitAccount",
                        command_id=uuid4(),
                        data={"index": i},
                    ),
                ],
                name=f"Batch {i}",
            )
            batch_ids.append(result.batch_id)

        # List all batches
        batches = await command_bus.list_batches("payments")
        assert len(batches) == 5

        # Verify ordering (newest first - by created_at DESC)
        returned_ids = [b.batch_id for b in batches]
        assert returned_ids == list(reversed(batch_ids))

    async def test_list_batches_status_filter(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test list_batches with status filter."""
        # Create multiple batches
        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=uuid4(),
                    data={},
                ),
            ],
        )

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=uuid4(),
                    data={},
                ),
            ],
        )

        # Start processing one batch to make it IN_PROGRESS
        worker = Worker(pool, domain="payments")
        received = await worker.receive(batch_size=1)
        assert len(received) == 1
        # Don't complete - leave in progress

        # Filter by status
        pending = await command_bus.list_batches("payments", status=BatchStatus.PENDING)
        in_progress = await command_bus.list_batches("payments", status=BatchStatus.IN_PROGRESS)

        # One batch should be pending, one in progress
        assert len(pending) == 1
        assert len(in_progress) == 1
        assert in_progress[0].status == BatchStatus.IN_PROGRESS

    async def test_list_batches_pagination(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test list_batches with pagination."""
        # Create 25 batches
        for i in range(25):
            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(
                        command_type="Cmd",
                        command_id=uuid4(),
                        data={"index": i},
                    ),
                ],
            )

        # Get first page
        page1 = await command_bus.list_batches("payments", limit=10, offset=0)
        assert len(page1) == 10

        # Get second page
        page2 = await command_bus.list_batches("payments", limit=10, offset=10)
        assert len(page2) == 10

        # Get third page
        page3 = await command_bus.list_batches("payments", limit=10, offset=20)
        assert len(page3) == 5

        # Verify no overlap
        all_ids = set()
        for batch in page1 + page2 + page3:
            assert batch.batch_id not in all_ids
            all_ids.add(batch.batch_id)
        assert len(all_ids) == 25

    async def test_list_batch_commands(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test list_batch_commands returns all commands in a batch."""
        batch_id = uuid4()
        cmd_ids = [uuid4() for _ in range(5)]

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={"index": i},
                )
                for i, cmd_id in enumerate(cmd_ids)
            ],
            batch_id=batch_id,
        )

        # List commands in batch
        commands = await command_bus.list_batch_commands("payments", batch_id)
        assert len(commands) == 5

        # Verify all commands belong to batch
        for cmd in commands:
            assert cmd.batch_id == batch_id
            assert cmd.command_id in cmd_ids

    async def test_list_batch_commands_with_status_filter(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test list_batch_commands with status filter."""
        batch_id = uuid4()
        cmd_ids = [uuid4() for _ in range(3)]

        await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=cmd_id,
                    data={},
                )
                for cmd_id in cmd_ids
            ],
            batch_id=batch_id,
        )

        # Create worker and complete one command
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command, context):
            return {"processed": True}

        worker = Worker(pool, domain="payments", registry=registry)
        received = await worker.receive(batch_size=1)
        await worker.complete(received[0], result={"processed": True})

        # List pending commands
        pending = await command_bus.list_batch_commands(
            "payments", batch_id, status=CommandStatus.PENDING
        )
        assert len(pending) == 2

        # List completed commands
        completed = await command_bus.list_batch_commands(
            "payments", batch_id, status=CommandStatus.COMPLETED
        )
        assert len(completed) == 1

    async def test_list_batch_commands_empty_for_nonexistent(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test list_batch_commands returns empty list for non-existent batch."""
        commands = await command_bus.list_batch_commands("payments", uuid4())
        assert commands == []

    async def test_list_batches_domain_scoped(
        self,
        command_bus: CommandBus,
        pool: AsyncConnectionPool,
        cleanup_payments_domain: None,
    ) -> None:
        """Test that list_batches is domain-scoped."""
        # Create queue for orders domain
        async with pool.connection() as conn:
            await conn.execute("SELECT pgmq.create('orders__commands')")
            await conn.execute("SELECT pgmq.create('orders__replies')")

        # Create batches in payments domain
        for _ in range(3):
            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(
                        command_type="Cmd",
                        command_id=uuid4(),
                        data={},
                    ),
                ],
            )

        # List batches in orders domain (should be empty)
        orders_batches = await command_bus.list_batches("orders")
        assert len(orders_batches) == 0

        # List batches in payments domain (should have 3)
        payments_batches = await command_bus.list_batches("payments")
        assert len(payments_batches) == 3


@pytest.mark.asyncio
class TestSendWithBatchValidation:
    """Integration tests for S044: Send with batch_id validation."""

    async def test_send_with_nonexistent_batch_raises_error(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test send with non-existent batch_id raises BatchNotFoundError."""
        fake_batch_id = uuid4()
        cmd_id = uuid4()

        with pytest.raises(BatchNotFoundError) as exc_info:
            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=cmd_id,
                data={"amount": 100},
                batch_id=fake_batch_id,
            )

        assert str(fake_batch_id) in str(exc_info.value)
        assert "payments" in str(exc_info.value)

        # Command should not exist
        cmd = await command_bus.get_command("payments", cmd_id)
        assert cmd is None

    async def test_send_with_valid_batch_succeeds(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test send with valid batch_id succeeds."""
        # Create a batch first
        batch_result = await command_bus.create_batch(
            domain="payments",
            commands=[
                BatchCommand(
                    command_type="DebitAccount",
                    command_id=uuid4(),
                    data={},
                ),
            ],
        )

        # Send additional command to the batch
        cmd_id = uuid4()
        result = await command_bus.send(
            domain="payments",
            command_type="CreditAccount",
            command_id=cmd_id,
            data={"amount": 50},
            batch_id=batch_result.batch_id,
        )

        assert result.command_id == cmd_id

        # Verify command has batch_id
        cmd = await command_bus.get_command("payments", cmd_id)
        assert cmd is not None
        assert cmd.batch_id == batch_result.batch_id

    async def test_send_without_batch_id_works(
        self,
        command_bus: CommandBus,
        cleanup_payments_domain: None,
    ) -> None:
        """Test send without batch_id still works."""
        cmd_id = uuid4()

        result = await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=cmd_id,
            data={"amount": 100},
        )

        assert result.command_id == cmd_id

        # Verify command has no batch_id
        cmd = await command_bus.get_command("payments", cmd_id)
        assert cmd is not None
        assert cmd.batch_id is None
