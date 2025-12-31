# S024 - Automated E2E Tests - Failure Scenarios

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** developer
**I want** automated E2E tests for failure scenarios
**So that** I can verify error handling, retries, and TSQ functionality work correctly

## Context

These tests verify the failure handling paths including transient failures with retry, permanent failures moving to TSQ, retry exhaustion, timeout handling, and TSQ operator actions.

## Acceptance Criteria

### Scenario: Permanent failure moves to TSQ
**Given** a worker is running
**When** I send a command with behavior "fail_permanent"
**Then** the command status transitions: PENDING → IN_PROGRESS → IN_TSQ
**And** the audit trail shows MOVED_TO_TSQ event
**And** the command appears in troubleshooting queue

### Scenario: Transient failure with retry succeeds
**Given** a worker is running with max_attempts=3
**When** I send a command with behavior "fail_transient_then_succeed" and transient_failures=2
**Then** the command fails twice then succeeds on attempt 3
**And** the audit trail shows 2 FAILED events and 1 COMPLETED event
**And** final status is COMPLETED

### Scenario: Transient failures exhaust retries
**Given** a worker is running with max_attempts=3
**When** I send a command with behavior "fail_transient"
**Then** the command fails 3 times
**And** the command moves to TSQ after retry exhaustion
**And** the audit trail shows RETRY_EXHAUSTED event

### Scenario: Timeout causes redelivery
**Given** a worker is running with visibility_timeout=2s
**When** I send a command with behavior "timeout" and timeout_ms=5000
**Then** the command times out and becomes visible again
**And** the worker picks it up again
**And** eventually the command completes or moves to TSQ

### Scenario: Operator retry from TSQ
**Given** a command is in TSQ due to permanent failure
**When** I call operator_retry on the command
**Then** the command is re-queued with status PENDING
**And** the audit trail shows OPERATOR_RETRY event
**And** the command is processed again

### Scenario: Operator cancel from TSQ
**Given** a command is in TSQ
**When** I call operator_cancel on the command
**Then** the command status becomes CANCELLED
**And** the audit trail shows OPERATOR_CANCEL event

### Scenario: Operator complete from TSQ
**Given** a command is in TSQ
**When** I call operator_complete with result data
**Then** the command status becomes COMPLETED
**And** the audit trail shows OPERATOR_COMPLETE event
**And** the result data is recorded

### Scenario: Error details are preserved
**Given** a command fails with specific error_code and error_message
**When** the command moves to TSQ
**Then** the error details are preserved in command metadata
**And** the error details are visible in audit trail

## Test Implementation

### Test File Structure

```python
# tests/e2e/tests/test_failure_scenarios.py

import pytest
from uuid import uuid4

@pytest.mark.e2e
class TestPermanentFailure:

    @pytest.mark.asyncio
    async def test_permanent_failure_moves_to_tsq(
        self, command_bus, worker_task, tsq, wait_for_status
    ):
        """Test permanent failure goes directly to TSQ."""
        command_id = uuid4()

        await create_test_command(command_id, {
            "type": "fail_permanent",
            "error_code": "INVALID_ACCOUNT",
            "error_message": "Account does not exist"
        })

        await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={}
        )

        # Wait for TSQ
        await wait_for_status(command_id, CommandStatus.IN_TSQ, timeout=10)

        # Verify in TSQ
        cmd = await command_bus.get_command("test", command_id)
        assert cmd.status == CommandStatus.IN_TSQ
        assert cmd.last_error_code == "INVALID_ACCOUNT"

        # Verify audit trail
        events = await command_bus.get_audit_trail(command_id)
        event_types = [e.event_type for e in events]
        assert "MOVED_TO_TSQ" in event_types


@pytest.mark.e2e
class TestTransientFailure:

    @pytest.mark.asyncio
    async def test_transient_then_succeed(
        self, command_bus, worker_task, wait_for_completion
    ):
        """Test transient failures followed by success."""
        command_id = uuid4()

        await create_test_command(command_id, {
            "type": "fail_transient_then_succeed",
            "transient_failures": 2
        })

        await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={},
            max_attempts=5
        )

        # Wait for completion
        await wait_for_completion(command_id, timeout=30)

        # Verify completed after 3 attempts
        cmd = await command_bus.get_command("test", command_id)
        assert cmd.status == CommandStatus.COMPLETED
        assert cmd.attempts == 3

        # Verify audit trail shows failures then success
        events = await command_bus.get_audit_trail(command_id)
        failed_events = [e for e in events if e.event_type == "FAILED"]
        assert len(failed_events) == 2

    @pytest.mark.asyncio
    async def test_retry_exhaustion(
        self, command_bus, worker_task, wait_for_status
    ):
        """Test transient failures exhaust retries."""
        command_id = uuid4()

        await create_test_command(command_id, {
            "type": "fail_transient",
            "error_code": "TIMEOUT"
        })

        await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={},
            max_attempts=3
        )

        # Wait for TSQ
        await wait_for_status(command_id, CommandStatus.IN_TSQ, timeout=60)

        # Verify attempts exhausted
        cmd = await command_bus.get_command("test", command_id)
        assert cmd.attempts == 3

        # Verify audit trail
        events = await command_bus.get_audit_trail(command_id)
        event_types = [e.event_type for e in events]
        assert "RETRY_EXHAUSTED" in event_types


@pytest.mark.e2e
class TestTimeout:

    @pytest.mark.asyncio
    async def test_timeout_causes_redelivery(
        self, command_bus, pool, wait_for_completion
    ):
        """Test timeout causes message redelivery."""
        command_id = uuid4()

        # First call times out, second succeeds
        await create_test_command(command_id, {
            "type": "fail_transient_then_succeed",
            "transient_failures": 1,
            "delay_ms": 100  # Short delay for success
        })

        # Start worker with short visibility timeout
        worker = await create_worker(
            pool,
            concurrency=1,
            visibility_timeout=2
        )
        worker_task = asyncio.create_task(worker.run())

        try:
            await command_bus.send(
                domain="test",
                command_type="TestCommand",
                command_id=command_id,
                data={},
                max_attempts=5
            )

            # Wait for completion
            await wait_for_completion(command_id, timeout=30)

            cmd = await command_bus.get_command("test", command_id)
            assert cmd.status == CommandStatus.COMPLETED
        finally:
            worker.stop()
            await worker_task


@pytest.mark.e2e
class TestTSQOperations:

    @pytest.mark.asyncio
    async def test_operator_retry(
        self, command_bus, tsq, worker_task, wait_for_status, wait_for_completion
    ):
        """Test operator retry from TSQ."""
        command_id = uuid4()

        # Create permanent failure command
        await create_test_command(command_id, {"type": "fail_permanent"})

        await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={}
        )

        # Wait for TSQ
        await wait_for_status(command_id, CommandStatus.IN_TSQ, timeout=10)

        # Update behavior to succeed on retry
        await update_test_command(command_id, {"type": "success"})

        # Operator retry
        await tsq.operator_retry(
            domain="test",
            command_id=command_id,
            operator="test-operator"
        )

        # Wait for completion
        await wait_for_completion(command_id, timeout=10)

        cmd = await command_bus.get_command("test", command_id)
        assert cmd.status == CommandStatus.COMPLETED

        # Verify audit trail
        events = await command_bus.get_audit_trail(command_id)
        event_types = [e.event_type for e in events]
        assert "OPERATOR_RETRY" in event_types

    @pytest.mark.asyncio
    async def test_operator_cancel(
        self, command_bus, tsq, worker_task, wait_for_status
    ):
        """Test operator cancel from TSQ."""
        command_id = uuid4()

        await create_test_command(command_id, {"type": "fail_permanent"})

        await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={}
        )

        await wait_for_status(command_id, CommandStatus.IN_TSQ, timeout=10)

        await tsq.operator_cancel(
            domain="test",
            command_id=command_id,
            operator="test-operator",
            reason="Test cancellation"
        )

        cmd = await command_bus.get_command("test", command_id)
        assert cmd.status == CommandStatus.CANCELLED

        events = await command_bus.get_audit_trail(command_id)
        event_types = [e.event_type for e in events]
        assert "OPERATOR_CANCEL" in event_types

    @pytest.mark.asyncio
    async def test_operator_complete(
        self, command_bus, tsq, worker_task, wait_for_status
    ):
        """Test operator complete from TSQ."""
        command_id = uuid4()

        await create_test_command(command_id, {"type": "fail_permanent"})

        await command_bus.send(
            domain="test",
            command_type="TestCommand",
            command_id=command_id,
            data={}
        )

        await wait_for_status(command_id, CommandStatus.IN_TSQ, timeout=10)

        await tsq.operator_complete(
            domain="test",
            command_id=command_id,
            operator="test-operator",
            result_data={"manually_resolved": True, "notes": "Fixed manually"}
        )

        cmd = await command_bus.get_command("test", command_id)
        assert cmd.status == CommandStatus.COMPLETED

        events = await command_bus.get_audit_trail(command_id)
        operator_event = next(e for e in events if e.event_type == "OPERATOR_COMPLETE")
        assert operator_event.details["operator"] == "test-operator"
```

## Additional Fixtures

```python
# Add to conftest.py

@pytest.fixture
async def tsq(pool):
    """TroubleshootingQueue instance."""
    from commandbus.ops import TroubleshootingQueue
    return TroubleshootingQueue(pool)

@pytest.fixture
def wait_for_status(command_bus):
    """Helper to wait for specific status."""
    async def _wait(command_id, expected_status, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            cmd = await command_bus.get_command("test", command_id)
            if cmd and cmd.status == expected_status:
                return cmd
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Command {command_id} did not reach {expected_status}")
    return _wait
```

## Files to Create

- `tests/e2e/tests/test_failure_scenarios.py` - Failure and TSQ tests

## Definition of Done

- [ ] Permanent failure test passes
- [ ] Transient-then-succeed test passes
- [ ] Retry exhaustion test passes
- [ ] Timeout/redelivery test passes
- [ ] Operator retry test passes
- [ ] Operator cancel test passes
- [ ] Operator complete test passes
- [ ] Error details preserved in all scenarios
- [ ] All tests run independently

## Story Size
L (5000-10000 tokens)

## Priority
Must Have

## Dependencies
- S017 - Base Infrastructure Setup
- S023 - Automated E2E Tests - Success Scenarios (shares fixtures)
