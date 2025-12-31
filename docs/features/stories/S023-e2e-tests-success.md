# S023 - Automated E2E Tests - Success Scenarios

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** developer
**I want** automated E2E tests for success scenarios
**So that** I can verify the complete command lifecycle works correctly

## Context

These automated tests verify the happy path scenarios using the E2E application infrastructure. Tests use the same database and worker as the demo UI.

## Acceptance Criteria

### Scenario: Command completes successfully
**Given** a worker is running
**When** I send a command with behavior "success"
**Then** the command status transitions: PENDING → IN_PROGRESS → COMPLETED
**And** the audit trail shows SENT, RECEIVED, COMPLETED events

### Scenario: Command with processing delay
**Given** a worker is running
**When** I send a command with behavior "success" and delay_ms=500
**Then** the command takes at least 500ms to complete
**And** the command status becomes COMPLETED

### Scenario: Multiple commands process concurrently
**Given** a worker with concurrency=4 is running
**When** I send 10 commands with behavior "success"
**Then** all 10 commands complete within reasonable time
**And** processing is parallelized (not sequential)

### Scenario: Correlation ID is preserved
**Given** a worker is running
**When** I send a command with a specific correlation_id
**Then** the correlation_id is present in the completed command metadata

### Scenario: Reply is sent when reply_to specified
**Given** a worker is running
**And** a reply queue exists
**When** I send a command with reply_to set
**Then** the command completes
**And** a reply message is sent to the reply queue

### Scenario: Command data is passed to handler
**Given** a worker is running
**When** I send a command with custom payload data
**Then** the handler receives the correct payload
**And** the result includes the processed data

## Test Implementation

### Test File Structure

```python
# tests/e2e/tests/test_success_scenarios.py

import pytest
from uuid import uuid4

@pytest.mark.e2e
class TestSuccessScenarios:

    @pytest.mark.asyncio
    async def test_command_completes_successfully(
        self, command_bus, worker_task, wait_for_completion
    ):
        """Test basic command completion."""
        command_id = uuid4()

        # Create test command with success behavior
        await create_test_command(command_id, {"type": "success"})

        # Send command
        result = await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={"test": "data"}
        )

        # Wait for completion
        await wait_for_completion(command_id, timeout=10)

        # Verify status
        cmd = await command_bus.get_command("test", command_id)
        assert cmd.status == CommandStatus.COMPLETED

        # Verify audit trail
        events = await command_bus.get_audit_trail(command_id)
        event_types = [e.event_type for e in events]
        assert "SENT" in event_types
        assert "RECEIVED" in event_types
        assert "COMPLETED" in event_types

    @pytest.mark.asyncio
    async def test_command_with_delay(
        self, command_bus, worker_task, wait_for_completion
    ):
        """Test command with processing delay."""
        command_id = uuid4()
        delay_ms = 500

        await create_test_command(command_id, {
            "type": "success",
            "delay_ms": delay_ms
        })

        start = time.time()
        await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={}
        )

        await wait_for_completion(command_id, timeout=10)
        elapsed = time.time() - start

        assert elapsed >= delay_ms / 1000
        cmd = await command_bus.get_command("test", command_id)
        assert cmd.status == CommandStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_concurrent_processing(
        self, command_bus, worker_task, wait_for_completion
    ):
        """Test multiple commands process concurrently."""
        command_ids = [uuid4() for _ in range(10)]

        # Create all test commands
        for cid in command_ids:
            await create_test_command(cid, {
                "type": "success",
                "delay_ms": 100
            })

        # Send all commands
        start = time.time()
        for cid in command_ids:
            await command_bus.send(
                domain="test",
                command_type="TestCommand",
                command_id=cid,
                data={}
            )

        # Wait for all to complete
        for cid in command_ids:
            await wait_for_completion(cid, timeout=30)

        elapsed = time.time() - start

        # With concurrency=4, 10 commands at 100ms each
        # should take ~300ms (3 batches), not 1000ms (sequential)
        assert elapsed < 1.0  # Allow some overhead

        # Verify all completed
        for cid in command_ids:
            cmd = await command_bus.get_command("test", cid)
            assert cmd.status == CommandStatus.COMPLETED
```

### Fixtures

```python
# tests/e2e/tests/conftest.py

import pytest
import asyncio
from psycopg_pool import AsyncConnectionPool

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def pool():
    """Database connection pool."""
    async with AsyncConnectionPool(
        conninfo="postgresql://postgres:postgres@localhost:5432/commandbus_e2e",  # pragma: allowlist secret
        min_size=1,
        max_size=10
    ) as pool:
        yield pool

@pytest.fixture
async def command_bus(pool):
    """CommandBus instance."""
    from commandbus import CommandBus
    return CommandBus(pool)

@pytest.fixture
async def worker_task(pool):
    """Start worker in background."""
    from tests.e2e.app.worker import create_worker

    worker = await create_worker(pool, concurrency=4)
    task = asyncio.create_task(worker.run())

    yield worker

    worker.stop()
    await task

@pytest.fixture
def wait_for_completion(command_bus):
    """Helper to wait for command completion."""
    async def _wait(command_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            cmd = await command_bus.get_command("test", command_id)
            if cmd and cmd.status in (CommandStatus.COMPLETED, CommandStatus.CANCELLED, CommandStatus.IN_TSQ):
                return cmd
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Command {command_id} did not complete in {timeout}s")
    return _wait

@pytest.fixture(autouse=True)
async def cleanup(pool):
    """Clean up test data before each test."""
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM test_command")
        await conn.execute("DELETE FROM command_bus_audit")
        await conn.execute("DELETE FROM command_bus_command")
        await conn.execute("SELECT pgmq.purge_queue('test__commands')")
    yield
```

## Files to Create

- `tests/e2e/tests/conftest.py` - Shared fixtures
- `tests/e2e/tests/test_success_scenarios.py` - Success tests

## Definition of Done

- [ ] All success scenario tests pass
- [ ] Tests run independently (proper cleanup)
- [ ] Tests use E2E database (not integration DB)
- [ ] Tests marked with @pytest.mark.e2e
- [ ] Concurrent processing verified
- [ ] Correlation ID preservation verified
- [ ] Reply queue functionality verified

## Story Size
M (2000-5000 tokens)

## Priority
Must Have

## Dependencies
- S017 - Base Infrastructure Setup
