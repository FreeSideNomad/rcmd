# Python Library Best Practices

Based on analysis of [PGMQ](https://github.com/pgmq/pgmq) and [pgmq-py](https://github.com/pgmq/pgmq-py), this document captures best practices for creating Python libraries.

---

## 1. Project Structure

### Source Layout (`src/` layout)

Use the `src/` layout for proper isolation between installed and development code:

```
project-name/
├── src/
│   └── package_name/
│       ├── __init__.py        # Public API exports
│       ├── core.py            # Core functionality
│       ├── async_module.py    # Async implementation (if needed)
│       ├── models.py          # Data structures
│       ├── decorators.py      # Utility decorators
│       └── logger.py          # Logging configuration
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── example/                   # Usage examples
├── benches/                   # Performance benchmarks
├── .github/
│   └── workflows/             # CI/CD pipelines
├── pyproject.toml             # Project configuration
├── Makefile                   # Development automation
├── .pre-commit-config.yaml    # Code quality hooks
└── README.md
```

### Module Organization

- **Separate sync and async implementations** into distinct modules (`queue.py` vs `async_queue.py`)
- **Keep public API minimal** - export only what users need from `__init__.py`
- **Group related functionality** - decorators, logging, and models in dedicated modules

---

## 2. Packaging & Dependencies

### Modern `pyproject.toml` Configuration

```toml
[project]
name = "your-package"
version = "1.0.0"
description = "Short, clear description"
readme = "README.md"
license = "Apache-2.0"
requires-python = ">=3.9"
authors = [
    { name = "Your Name", email = "you@example.com" }
]
maintainers = [
    { name = "Maintainer", email = "maintainer@example.com" }
]
keywords = ["keyword1", "keyword2"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]

dependencies = [
    "core-dependency>=1.0.0",
]

[project.optional-dependencies]
async = ["asyncpg>=0.30.0"]
dev = [
    "pre-commit>=4.3.0",
    "ruff>=0.12.0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]
bench = [
    "locust",
    "pandas",
]

[project.urls]
Homepage = "https://github.com/org/project"
Documentation = "https://github.com/org/project#readme"
Repository = "https://github.com/org/project"
Issues = "https://github.com/org/project/issues"
Changelog = "https://github.com/org/project/releases"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py39"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### Dependency Management Principles

1. **Minimize core dependencies** - PGMQ uses only `orjson` and `psycopg`
2. **Use optional dependency groups** for async, development, and benchmarking
3. **Pin minimum versions** with `>=` rather than exact versions
4. **Use lock files** (`uv.lock`) for reproducible development environments

---

## 3. API Design

### Configuration Patterns

Support both environment variables and explicit configuration:

```python
class MyClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
        *,
        verbose: bool = False,
        log_filename: str | None = None,
    ):
        self.host = host or os.environ.get("PG_HOST", "localhost")
        self.port = port or int(os.environ.get("PG_PORT", "5432"))
        # ... etc
```

### Async Initialization Pattern

Async clients require explicit initialization:

```python
class AsyncClient:
    async def init(self) -> None:
        """Must be called before using the client."""
        self._pool = await create_pool(...)

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, *args):
        await self.close()
```

### Batch Operations

Provide batch variants for performance-critical operations:

```python
def send(self, queue: str, message: dict) -> int:
    """Send a single message."""

def send_batch(self, queue: str, messages: list[dict]) -> list[int]:
    """Send multiple messages in one operation."""
```

### Transaction Support

Use decorators for transaction management:

```python
from functools import wraps

def transaction(func):
    @wraps(func)
    def wrapper(self, *args, conn=None, **kwargs):
        if conn is not None:
            return func(self, *args, conn=conn, **kwargs)
        with self.pool.connection() as conn:
            with conn.transaction():
                return func(self, *args, conn=conn, **kwargs)
    return wrapper
```

### Method Parameter Conventions

- Operations should accept optional `conn` parameter to participate in external transactions
- Use keyword-only arguments (`*`) for configuration options
- Provide sensible defaults

---

## 4. API Parity Strategy

When wrapping an existing system (like PGMQ wrapping SQS/RSMQ concepts):

1. **Mirror established APIs** - Use familiar method names (`send`, `read`, `delete`, `archive`)
2. **Preserve semantics** - Visibility timeout, at-least-once delivery, etc.
3. **Document differences** - Clearly state where your API differs from the inspiration

### Core Operation Categories

| Category | Operations |
|----------|------------|
| **Lifecycle** | `create_queue()`, `drop_queue()`, `list_queues()` |
| **Messaging** | `send()`, `send_batch()`, `read()`, `read_batch()`, `pop()` |
| **Polling** | `read_with_poll()` (blocks until message or timeout) |
| **Disposition** | `archive()`, `delete()`, `set_vt()` |
| **Admin** | `purge()`, `metrics()` |

---

## 5. Error Handling

### Custom Exception Hierarchy

```python
class CommandBusError(Exception):
    """Base exception for all library errors."""

class TransientCommandError(CommandBusError):
    """Retryable error - will be retried according to policy."""
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

class PermanentCommandError(CommandBusError):
    """Non-retryable error - goes directly to troubleshooting."""
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)
```

### Error Classification

- **Transient errors**: Network issues, timeouts, temporary unavailability
- **Permanent errors**: Validation failures, business rule violations, missing data

---

## 6. Testing Strategy

### Three-Tier Testing Approach

```
tests/
├── unit/              # No external dependencies
│   ├── test_models.py
│   ├── test_policies.py
│   └── test_handlers.py
├── integration/       # Requires Postgres + PGMQ
│   ├── test_queue_ops.py
│   ├── test_transactions.py
│   └── conftest.py    # Docker fixtures
└── e2e/               # Full system tests
    ├── test_happy_path.py
    ├── test_retry_scenarios.py
    └── test_troubleshooting.py
```

### Unit Tests (No External Dependencies)

Use fakes and mocks for isolation:

```python
class FakePgmqClient:
    """In-memory PGMQ simulation with visibility timeout."""

    def __init__(self):
        self.queues: dict[str, list] = {}
        self.visibility: dict[tuple, datetime] = {}

    def send(self, queue: str, message: dict) -> int:
        if queue not in self.queues:
            self.queues[queue] = []
        msg_id = len(self.queues[queue]) + 1
        self.queues[queue].append((msg_id, message))
        return msg_id
```

### Integration Tests (Docker-based)

```python
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("ghcr.io/pgmq/pg17-pgmq:latest") as pg:
        yield pg

@pytest.fixture
def queue(postgres):
    from pgmq import PGMQueue
    return PGMQueue(
        host=postgres.get_container_host_ip(),
        port=postgres.get_exposed_port(5432),
        username="postgres",
        password="postgres",
        database="postgres",
    )
```

### E2E Test Scenarios

1. Happy path - send, process, complete
2. Transient failure with successful retry
3. Permanent failure to troubleshooting queue
4. Retry exhaustion to troubleshooting queue
5. Operator retry from troubleshooting
6. Operator cancel from troubleshooting
7. Duplicate send (idempotency)

---

## 7. Documentation

### README Structure

1. **One-liner description** - What the library does
2. **Installation** - pip install commands including optional deps
3. **Quick start** - Minimal working example
4. **Configuration** - Environment variables and explicit options
5. **API reference** - Table of operations with brief descriptions
6. **Examples** - Link to examples directory
7. **Contributing** - Development setup instructions

### Inline Documentation

- Type hints on all public methods
- Docstrings with Args, Returns, Raises
- Link to related methods in docstrings

```python
def read_with_poll(
    self,
    queue: str,
    vt: int = 30,
    max_wait_seconds: int = 5,
    poll_interval_ms: int = 100,
) -> Message | None:
    """
    Read a message, polling until one is available or timeout.

    Args:
        queue: Queue name to read from
        vt: Visibility timeout in seconds
        max_wait_seconds: Maximum time to wait for a message
        poll_interval_ms: Polling interval in milliseconds

    Returns:
        Message if available, None if timeout

    See Also:
        read: Single non-blocking read
        read_batch: Read multiple messages at once
    """
```

---

## 8. Observability

### Logging Configuration

```python
import logging

def configure_logging(
    verbose: bool = False,
    log_filename: str | None = None,
) -> logging.Logger:
    logger = logging.getLogger("commandbus")
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    handler = (
        logging.FileHandler(log_filename)
        if log_filename
        else logging.StreamHandler()
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)
    return logger
```

### Metrics Support

Provide queue metrics for monitoring:

```python
@dataclass
class QueueMetrics:
    queue_name: str
    queue_length: int
    oldest_msg_age_sec: float | None
    newest_msg_age_sec: float | None
    total_messages: int
    scrape_time: datetime
```

---

## 9. Development Workflow

### Makefile Tasks

```makefile
.PHONY: install lint test test-unit test-integration format

install:
	uv sync --all-extras

lint:
	ruff check src tests

format:
	ruff format src tests

test-unit:
	pytest tests/unit -v

test-integration:
	docker-compose up -d postgres
	pytest tests/integration -v
	docker-compose down

test: test-unit test-integration

pre-commit:
	pre-commit run --all-files
```

### Pre-commit Configuration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.12.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

---

## 10. Key Takeaways

| Principle | Implementation |
|-----------|----------------|
| **Minimal dependencies** | Only include what's essential |
| **Environment-first config** | Default to env vars for production |
| **Batch operations** | Always provide batch variants |
| **Transaction support** | Allow operations to join external transactions |
| **Sync + async** | Separate implementations, not wrappers |
| **Three-tier testing** | Unit (fast), integration (containers), E2E (full system) |
| **Metrics built-in** | Provide queue statistics out of the box |
| **Clear error types** | Transient vs permanent for retry logic |

---

## References

- [PGMQ Repository](https://github.com/pgmq/pgmq)
- [pgmq-py Python Client](https://github.com/pgmq/pgmq-py)
- [Python Packaging User Guide](https://packaging.python.org/)
- [uv Package Manager](https://docs.astral.sh/uv/)
