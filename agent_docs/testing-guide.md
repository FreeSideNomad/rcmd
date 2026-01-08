# Testing Guide

Complete guide to writing and running tests for Command Bus.

## Running Tests

```bash
# All tests
make test

# Unit tests only (fast, no Docker)
make test-unit

# Integration tests (requires Docker)
make docker-up
make test-integration
make docker-down

# With coverage
make coverage

# Specific test file
pytest tests/unit/test_api.py -v

# Specific test
pytest tests/unit/test_api.py::test_send_command -v

# With output
pytest tests/unit/ -v -s

# Stop on first failure
pytest tests/unit/ -x
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures
├── factories.py             # Test data factories
├── unit/
│   ├── conftest.py          # Unit-specific fixtures
│   ├── test_api.py
│   ├── test_models.py
│   ├── test_policies.py
│   └── test_worker.py
├── integration/
│   ├── conftest.py          # Integration fixtures
│   ├── test_pgmq_client.py
│   └── test_repositories.py
└── e2e/
    ├── conftest.py
    └── test_scenarios.py
```

## Fixtures

### Shared Fixtures (conftest.py)

```python
# tests/conftest.py
import pytest
from uuid import uuid4

@pytest.fixture
def command_id() -> UUID:
    return uuid4()

@pytest.fixture
def correlation_id() -> UUID:
    return uuid4()
```

### Unit Test Fixtures

```python
# tests/unit/conftest.py
import pytest
from commandbus.testing.fakes import FakePgmqClient, FakeCommandRepository
from commandbus.api import CommandBus

@pytest.fixture
def fake_pgmq() -> FakePgmqClient:
    """In-memory PGMQ fake with VT simulation."""
    return FakePgmqClient()

@pytest.fixture
def fake_repo() -> FakeCommandRepository:
    """In-memory command repository."""
    return FakeCommandRepository()

@pytest.fixture
def command_bus(fake_pgmq, fake_repo) -> CommandBus:
    """CommandBus with fake dependencies."""
    return CommandBus(pgmq=fake_pgmq, repo=fake_repo)
```

### Integration Test Fixtures

```python
# tests/integration/conftest.py
import pytest
import os
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/commandbus"  # pragma: allowlist secret
)

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for session-scoped fixtures."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def db_pool():
    """Shared connection pool for integration tests."""
    pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=5)
    await pool.open()
    yield pool
    await pool.close()

@pytest.fixture
async def clean_db(db_pool):
    """Clean database before each test."""
    async with db_pool.connection() as conn:
        await conn.execute("TRUNCATE command_bus_command CASCADE")
        await conn.execute("TRUNCATE command_bus_audit CASCADE")
    yield
```

## Writing Unit Tests

### Basic Test Structure

```python
import pytest
from uuid import uuid4
from commandbus.exceptions import DuplicateCommandError

@pytest.mark.asyncio
async def test_send_command_succeeds(
    command_bus: CommandBus,
    command_id: UUID,
) -> None:
    """Sending a new command should succeed and return the command ID."""
    result = await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"amount": 100},
    )

    assert result == command_id
```

### Testing Exceptions

```python
@pytest.mark.asyncio
async def test_send_duplicate_raises_error(
    command_bus: CommandBus,
    command_id: UUID,
) -> None:
    """Sending a command with existing ID should raise DuplicateCommandError."""
    # First send succeeds
    await command_bus.send(
        domain="payments",
        command_type="DebitAccount",
        command_id=command_id,
        data={"amount": 100},
    )

    # Second send with same ID fails
    with pytest.raises(DuplicateCommandError) as exc_info:
        await command_bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"amount": 200},
        )

    assert exc_info.value.command_id == command_id
```

### Parameterized Tests

```python
import pytest

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attempts,expected_status",
    [
        (1, CommandStatus.PENDING),
        (3, CommandStatus.IN_TROUBLESHOOTING_QUEUE),
    ],
)
async def test_retry_policy(
    command_bus: CommandBus,
    attempts: int,
    expected_status: CommandStatus,
) -> None:
    """Command status should reflect retry attempts."""
    command_id = uuid4()
    await command_bus.send(domain="test", command_type="Test", command_id=command_id, data={})

    for _ in range(attempts):
        await command_bus.fail_command(command_id, TransientCommandError("TEST", "test"))

    status = await command_bus.get_status(command_id)
    assert status == expected_status
```

## Writing Integration Tests

### Database Tests

```python
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_and_retrieve_command(
    db_pool,
    clean_db,
) -> None:
    """Command should be saved to and retrieved from database."""
    repo = PostgresCommandRepository(db_pool)
    command = CommandMetadata(
        domain="payments",
        command_id=uuid4(),
        command_type="DebitAccount",
        status=CommandStatus.PENDING,
    )

    await repo.save(command)
    retrieved = await repo.get_by_id(command.domain, command.command_id)

    assert retrieved is not None
    assert retrieved.command_id == command.command_id
    assert retrieved.status == CommandStatus.PENDING
```

### PGMQ Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_and_read_message(
    db_pool,
    clean_db,
) -> None:
    """Messages should be sent and read via PGMQ."""
    pgmq = PgmqClient(db_pool)

    # Send message
    msg_id = await pgmq.send("test__commands", {"test": "data"})
    assert msg_id > 0

    # Read message
    messages = await pgmq.read("test__commands", vt=30, limit=1)
    assert len(messages) == 1
    assert messages[0].msg_id == msg_id
    assert messages[0].message == {"test": "data"}

    # Delete message
    await pgmq.delete("test__commands", msg_id)
```

## Test Data Factories

```python
# tests/factories.py
from uuid import uuid4
from datetime import datetime, timezone
from commandbus.models import Command, CommandMetadata, CommandStatus

def make_command(
    *,
    domain: str = "test",
    command_type: str = "TestCommand",
    command_id: UUID | None = None,
    data: dict | None = None,
    correlation_id: UUID | None = None,
) -> Command:
    """Create a test command with defaults."""
    return Command(
        domain=domain,
        command_type=command_type,
        command_id=command_id or uuid4(),
        data=data or {},
        correlation_id=correlation_id or uuid4(),
        created_at=datetime.now(timezone.utc),
    )

def make_metadata(
    *,
    command: Command | None = None,
    status: CommandStatus = CommandStatus.PENDING,
    attempts: int = 0,
    max_attempts: int = 3,
) -> CommandMetadata:
    """Create test command metadata."""
    cmd = command or make_command()
    return CommandMetadata(
        domain=cmd.domain,
        command_id=cmd.command_id,
        command_type=cmd.command_type,
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
        created_at=cmd.created_at,
    )
```

## Async Testing Tips

### Timeouts

```python
import asyncio

@pytest.mark.asyncio
async def test_receive_with_timeout() -> None:
    """Receive should complete within timeout."""
    async with asyncio.timeout(5):
        result = await command_bus.receive("test", vt=30, limit=1)
    assert result == []
```

### Concurrent Operations

```python
@pytest.mark.asyncio
async def test_concurrent_sends() -> None:
    """Multiple concurrent sends should all succeed."""
    commands = [make_command() for _ in range(10)]

    results = await asyncio.gather(*[
        command_bus.send(
            domain=cmd.domain,
            command_type=cmd.command_type,
            command_id=cmd.command_id,
            data=cmd.data,
        )
        for cmd in commands
    ])

    assert len(results) == 10
    assert all(r is not None for r in results)
```

## Mocking External Services

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_handler_calls_external_service() -> None:
    """Handler should call external service."""
    mock_service = AsyncMock(return_value={"status": "ok"})

    with patch("commandbus.handlers.payments.external_service", mock_service):
        result = await handler.process(command)

    mock_service.assert_called_once_with(command.data)
    assert result.success
```
