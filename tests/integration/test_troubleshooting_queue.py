"""Integration tests for TroubleshootingQueue operations."""

import os
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus import (
    Command,
    CommandBus,
    CommandNotFoundError,
    CommandStatus,
    HandlerContext,
    HandlerRegistry,
    InvalidOperationError,
    PermanentCommandError,
    PgmqClient,
    PostgresAuditLogger,
    PostgresCommandRepository,
    RetryPolicy,
    TransientCommandError,
    TroubleshootingQueue,
    Worker,
)


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/commandbus"
    )


@pytest.fixture
async def pool(database_url: str) -> AsyncConnectionPool:
    """Create a connection pool for testing."""
    async with AsyncConnectionPool(conninfo=database_url, min_size=1, max_size=5, open=False) as p:
        yield p


@pytest.fixture
async def command_bus(pool: AsyncConnectionPool) -> CommandBus:
    """Create a CommandBus with real database connection."""
    return CommandBus(pool)


@pytest.fixture
def handler_registry() -> HandlerRegistry:
    """Create handler registry."""
    return HandlerRegistry()


@pytest.fixture
def tsq(pool: AsyncConnectionPool) -> TroubleshootingQueue:
    """Create a TroubleshootingQueue."""
    return TroubleshootingQueue(pool)


class TestListTroubleshootingIntegration:
    """Integration tests for listing troubleshooting queue items."""

    @pytest.mark.asyncio
    async def test_list_empty_queue(self, tsq: TroubleshootingQueue) -> None:
        """Test listing empty troubleshooting queue."""
        # Use a unique domain to ensure we get empty results
        items = await tsq.list_troubleshooting(f"empty_domain_{uuid4().hex[:8]}")

        assert items == []

    @pytest.mark.asyncio
    async def test_list_exhausted_command(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test listing a command that exhausted retries."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise TransientCommandError("TIMEOUT", "Service timeout")

        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={"test_key": "test_value"},
        )

        # Worker with max_attempts=1 (immediate exhaustion)
        worker = Worker(
            pool,
            domain=domain,
            registry=handler_registry,
            retry_policy=RetryPolicy(max_attempts=1, backoff_schedule=[1]),
        )

        # Exhaust the command
        received = await worker.receive()
        await worker.fail(received[0], TransientCommandError("TIMEOUT", "Service timeout"))

        # List troubleshooting items
        items = await tsq.list_troubleshooting(domain)

        assert len(items) == 1
        item = items[0]
        assert item.command_id == command_id
        assert item.command_type == "TestCommand"
        assert item.domain == domain
        assert item.last_error_type == "TRANSIENT"
        assert item.last_error_code == "TIMEOUT"
        assert item.last_error_msg == "Service timeout"

    @pytest.mark.asyncio
    async def test_list_permanent_failure_command(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test listing a command that failed permanently."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID_DATA", "Invalid account format")

        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={"account": "invalid"},
        )

        worker = Worker(
            pool,
            domain=domain,
            registry=handler_registry,
        )

        # Fail permanently
        received = await worker.receive()
        error = PermanentCommandError("INVALID_DATA", "Invalid account format")
        await worker.fail(received[0], error)

        # List troubleshooting items
        items = await tsq.list_troubleshooting(domain)

        assert len(items) == 1
        item = items[0]
        assert item.command_id == command_id
        assert item.last_error_type == "PERMANENT"
        assert item.last_error_code == "INVALID_DATA"

    @pytest.mark.asyncio
    async def test_list_with_payload(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test that listed items include original payload from archive."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"
        original_data = {"account_id": "ACC-123", "amount": 500, "currency": "USD"}

        @handler_registry.handler(domain, "TransferCommand")
        async def handle_transfer(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INSUFFICIENT_FUNDS", "Not enough balance")

        await command_bus.send(
            domain=domain,
            command_type="TransferCommand",
            command_id=command_id,
            data=original_data,
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        error = PermanentCommandError("INSUFFICIENT_FUNDS", "Not enough balance")
        await worker.fail(received[0], error)

        items = await tsq.list_troubleshooting(domain)

        assert len(items) == 1
        assert items[0].payload is not None
        # Payload contains command envelope including the data
        assert items[0].payload.get("data") == original_data

    @pytest.mark.asyncio
    async def test_list_with_command_type_filter(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test filtering by command type."""
        domain = f"test_domain_{uuid4().hex[:8]}"
        debit_id = uuid4()
        credit_id = uuid4()

        @handler_registry.handler(domain, "DebitCommand")
        async def handle_debit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        @handler_registry.handler(domain, "CreditCommand")
        async def handle_credit(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send both commands
        await command_bus.send(
            domain=domain,
            command_type="DebitCommand",
            command_id=debit_id,
            data={},
        )
        await command_bus.send(
            domain=domain,
            command_type="CreditCommand",
            command_id=credit_id,
            data={},
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)

        # Fail both commands
        for _ in range(2):
            received = await worker.receive()
            for cmd in received:
                await worker.fail(cmd, PermanentCommandError("INVALID", "Invalid"))

        # Filter by DebitCommand
        debit_items = await tsq.list_troubleshooting(domain, command_type="DebitCommand")
        assert len(debit_items) == 1
        assert debit_items[0].command_id == debit_id

        # Filter by CreditCommand
        credit_items = await tsq.list_troubleshooting(domain, command_type="CreditCommand")
        assert len(credit_items) == 1
        assert credit_items[0].command_id == credit_id

    @pytest.mark.asyncio
    async def test_list_pagination(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test pagination with limit and offset."""
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send 5 commands
        command_ids = [uuid4() for _ in range(5)]
        for cid in command_ids:
            await command_bus.send(
                domain=domain,
                command_type="TestCommand",
                command_id=cid,
                data={},
            )

        worker = Worker(pool, domain=domain, registry=handler_registry)

        # Fail all commands
        while True:
            received = await worker.receive()
            if not received:
                break
            for cmd in received:
                await worker.fail(cmd, PermanentCommandError("INVALID", "Invalid"))

        # Test limit
        page1 = await tsq.list_troubleshooting(domain, limit=2, offset=0)
        assert len(page1) == 2

        # Test offset
        page2 = await tsq.list_troubleshooting(domain, limit=2, offset=2)
        assert len(page2) == 2

        # Ensure no overlap
        page1_ids = {item.command_id for item in page1}
        page2_ids = {item.command_id for item in page2}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_list_with_correlation_id_and_reply_to(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test that correlation_id and reply_to are preserved."""
        command_id = uuid4()
        correlation_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"
        reply_queue = f"{domain}__replies"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("FAILED", "Failed")

        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={},
            correlation_id=correlation_id,
            reply_to=reply_queue,
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("FAILED", "Failed"))

        items = await tsq.list_troubleshooting(domain)

        assert len(items) == 1
        assert items[0].correlation_id == correlation_id
        assert items[0].reply_to == reply_queue


class TestCountTroubleshootingIntegration:
    """Integration tests for counting troubleshooting queue items."""

    @pytest.mark.asyncio
    async def test_count_empty_queue(self, tsq: TroubleshootingQueue) -> None:
        """Test counting empty troubleshooting queue."""
        count = await tsq.count_troubleshooting(f"empty_domain_{uuid4().hex[:8]}")

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_items(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test counting items in troubleshooting queue."""
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send 3 commands
        for _ in range(3):
            await command_bus.send(
                domain=domain,
                command_type="TestCommand",
                command_id=uuid4(),
                data={},
            )

        worker = Worker(pool, domain=domain, registry=handler_registry)

        # Fail all commands
        while True:
            received = await worker.receive()
            if not received:
                break
            for cmd in received:
                await worker.fail(cmd, PermanentCommandError("INVALID", "Invalid"))

        count = await tsq.count_troubleshooting(domain)

        assert count == 3

    @pytest.mark.asyncio
    async def test_count_with_command_type_filter(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test counting with command type filter."""
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TypeA")
        async def handle_a(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        @handler_registry.handler(domain, "TypeB")
        async def handle_b(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send commands: 2 TypeA, 3 TypeB
        for _ in range(2):
            await command_bus.send(domain=domain, command_type="TypeA", command_id=uuid4(), data={})
        for _ in range(3):
            await command_bus.send(domain=domain, command_type="TypeB", command_id=uuid4(), data={})

        worker = Worker(pool, domain=domain, registry=handler_registry)

        # Fail all commands
        while True:
            received = await worker.receive()
            if not received:
                break
            for cmd in received:
                await worker.fail(cmd, PermanentCommandError("INVALID", "Invalid"))

        # Count by type
        type_a_count = await tsq.count_troubleshooting(domain, command_type="TypeA")
        type_b_count = await tsq.count_troubleshooting(domain, command_type="TypeB")
        total_count = await tsq.count_troubleshooting(domain)

        assert type_a_count == 2
        assert type_b_count == 3
        assert total_count == 5


class TestOperatorRetryIntegration:
    """Integration tests for operator_retry()."""

    @pytest.mark.asyncio
    async def test_operator_retry_raises_command_not_found(self, tsq: TroubleshootingQueue) -> None:
        """Test operator_retry raises CommandNotFoundError for missing command."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        with pytest.raises(CommandNotFoundError) as exc_info:
            await tsq.operator_retry(domain, command_id)

        assert exc_info.value.domain == domain
        assert exc_info.value.command_id == str(command_id)

    @pytest.mark.asyncio
    async def test_operator_retry_raises_invalid_operation_not_in_tsq(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test operator_retry raises InvalidOperationError when command not in TSQ."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            return {"status": "ok"}

        # Send command - it will be in PENDING status
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={"test": "data"},
        )

        with pytest.raises(InvalidOperationError) as exc_info:
            await tsq.operator_retry(domain, command_id)

        assert "not in troubleshooting queue" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_operator_retry_success(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test successful operator_retry re-enqueues the command."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"
        original_data = {"account_id": "ACC-123", "amount": 500}

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send and fail the command to put it in TSQ
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data=original_data,
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Verify command is in TSQ
        items = await tsq.list_troubleshooting(domain)
        assert len(items) == 1
        assert items[0].command_id == command_id

        # Retry the command
        new_msg_id = await tsq.operator_retry(domain, command_id, operator="admin")

        assert new_msg_id > 0

        # Verify command is now in PENDING status
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get(domain, command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.PENDING
        assert metadata.attempts == 0
        assert metadata.msg_id == new_msg_id
        assert metadata.last_error_type is None
        assert metadata.last_error_code is None
        assert metadata.last_error_msg is None

    @pytest.mark.asyncio
    async def test_operator_retry_records_audit_event(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test operator_retry records OPERATOR_RETRY audit event."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send and fail the command
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={},
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Retry with operator identity
        await tsq.operator_retry(domain, command_id, operator="admin_user")

        # Verify audit event was recorded
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain)

        operator_retry_events = [e for e in events if e["event_type"] == "OPERATOR_RETRY"]
        assert len(operator_retry_events) == 1
        assert operator_retry_events[0]["details"]["operator"] == "admin_user"

    @pytest.mark.asyncio
    async def test_operator_retry_command_can_be_processed_again(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test retried command can be received and processed by worker."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"
        original_data = {"test_key": "test_value"}
        processed_data: dict[str, str] = {}

        call_count = 0

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermanentCommandError("INVALID", "Invalid")
            # Second time - success
            processed_data.update(command.data)
            return {"status": "ok"}

        # Send and fail the command
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data=original_data,
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Retry the command
        await tsq.operator_retry(domain, command_id, operator="admin")

        # Receive and process the retried command
        received2 = await worker.receive()
        assert len(received2) == 1
        assert received2[0].command_id == command_id

        # Process successfully this time
        await worker.complete(received2[0], {"status": "ok"})

        # Verify command was processed with original data
        assert processed_data == original_data

        # Verify command is now completed
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get(domain, command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_operator_retry_removes_from_tsq_list(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test retried command no longer appears in troubleshooting list."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send and fail the command
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={},
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Verify in TSQ
        count_before = await tsq.count_troubleshooting(domain)
        assert count_before == 1

        # Retry the command
        await tsq.operator_retry(domain, command_id)

        # Verify no longer in TSQ
        count_after = await tsq.count_troubleshooting(domain)
        assert count_after == 0

        items = await tsq.list_troubleshooting(domain)
        assert len(items) == 0


class TestOperatorCancelIntegration:
    """Integration tests for operator_cancel()."""

    @pytest.mark.asyncio
    async def test_operator_cancel_raises_command_not_found(
        self, tsq: TroubleshootingQueue
    ) -> None:
        """Test operator_cancel raises CommandNotFoundError for missing command."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        with pytest.raises(CommandNotFoundError) as exc_info:
            await tsq.operator_cancel(domain, command_id, "Invalid account")

        assert exc_info.value.domain == domain
        assert exc_info.value.command_id == str(command_id)

    @pytest.mark.asyncio
    async def test_operator_cancel_raises_invalid_operation_not_in_tsq(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test operator_cancel raises InvalidOperationError when command not in TSQ."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            return {"status": "ok"}

        # Send command - it will be in PENDING status
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={"test": "data"},
        )

        with pytest.raises(InvalidOperationError) as exc_info:
            await tsq.operator_cancel(domain, command_id, "Invalid account")

        assert "not in troubleshooting queue" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_operator_cancel_sets_status_to_canceled(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test operator_cancel sets command status to CANCELED."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send and fail the command to put it in TSQ
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={},
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Cancel the command
        await tsq.operator_cancel(domain, command_id, "Invalid account")

        # Verify command is now CANCELED
        command_repo = PostgresCommandRepository(pool)
        metadata = await command_repo.get(domain, command_id)
        assert metadata is not None
        assert metadata.status == CommandStatus.CANCELED

    @pytest.mark.asyncio
    async def test_operator_cancel_sends_reply(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test operator_cancel sends CANCELED reply to reply queue."""
        command_id = uuid4()
        correlation_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"
        reply_queue = f"{domain}__replies"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Create reply queue
        pgmq = PgmqClient(pool)
        await pgmq.create_queue(reply_queue)

        # Send command with reply_to
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={},
            correlation_id=correlation_id,
            reply_to=reply_queue,
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Cancel the command
        await tsq.operator_cancel(domain, command_id, "Invalid account format")

        # Read the reply from the queue
        replies = await pgmq.read(reply_queue, visibility_timeout=30, batch_size=1)

        assert len(replies) == 1
        reply = replies[0].message
        assert reply["command_id"] == str(command_id)
        assert reply["correlation_id"] == str(correlation_id)
        assert reply["outcome"] == "CANCELED"
        assert reply["reason"] == "Invalid account format"

    @pytest.mark.asyncio
    async def test_operator_cancel_records_audit_event(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test operator_cancel records OPERATOR_CANCEL audit event."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send and fail the command
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={},
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Cancel with operator identity and reason
        await tsq.operator_cancel(domain, command_id, "Duplicate request", operator="admin_user")

        # Verify audit event was recorded
        audit_logger = PostgresAuditLogger(pool)
        events = await audit_logger.get_events(command_id, domain)

        cancel_events = [e for e in events if e["event_type"] == "OPERATOR_CANCEL"]
        assert len(cancel_events) == 1
        assert cancel_events[0]["details"]["operator"] == "admin_user"
        assert cancel_events[0]["details"]["reason"] == "Duplicate request"

    @pytest.mark.asyncio
    async def test_operator_cancel_removes_from_tsq_list(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        handler_registry: HandlerRegistry,
        tsq: TroubleshootingQueue,
    ) -> None:
        """Test canceled command no longer appears in troubleshooting list."""
        command_id = uuid4()
        domain = f"test_domain_{uuid4().hex[:8]}"

        @handler_registry.handler(domain, "TestCommand")
        async def handle_test(command: Command, context: HandlerContext) -> dict[str, str]:
            raise PermanentCommandError("INVALID", "Invalid")

        # Send and fail the command
        await command_bus.send(
            domain=domain,
            command_type="TestCommand",
            command_id=command_id,
            data={},
        )

        worker = Worker(pool, domain=domain, registry=handler_registry)
        received = await worker.receive()
        await worker.fail(received[0], PermanentCommandError("INVALID", "Invalid"))

        # Verify in TSQ
        count_before = await tsq.count_troubleshooting(domain)
        assert count_before == 1

        # Cancel the command
        await tsq.operator_cancel(domain, command_id, "Invalid request")

        # Verify no longer in TSQ
        count_after = await tsq.count_troubleshooting(domain)
        assert count_after == 0

        items = await tsq.list_troubleshooting(domain)
        assert len(items) == 0
