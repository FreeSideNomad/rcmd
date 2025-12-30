# Command Bus Python Library

A Python library providing Command Bus abstraction over PostgreSQL + PGMQ.

## Quick Reference

```bash
# Development
make install          # Install dependencies with uv
make lint             # Run ruff linter
make format           # Format code with ruff
make typecheck        # Run mypy type checking
make test             # Run all tests
make test-unit        # Run unit tests only
make test-integration # Run integration tests (requires Docker)
make coverage         # Run tests with coverage report

# Docker
make docker-up        # Start Postgres + PGMQ
make docker-down      # Stop containers
```

## Tech Stack

- Python 3.11+
- PostgreSQL 15+ with PGMQ extension
- psycopg3 (async support)
- pytest + pytest-asyncio
- ruff (linting/formatting)
- mypy (type checking)
- uv (package management)

## Project Structure

```
src/commandbus/
  api.py              # Public CommandBus interface
  models.py           # Domain models (Command, Reply, etc.)
  exceptions.py       # TransientCommandError, PermanentCommandError
  policies.py         # Retry policies and backoff
  handler.py          # Handler registry
  worker.py           # Worker loop with concurrency
  repositories/
    base.py           # Repository protocols
    postgres.py       # PostgreSQL implementation
  pgmq/
    client.py         # PGMQ SQL wrapper
    notify.py         # pg_notify/LISTEN implementation
  ops/
    troubleshooting.py # Operator APIs
  testing/
    fakes.py          # FakePgmqClient for unit tests

tests/
  unit/               # No external dependencies
  integration/        # Requires Postgres + PGMQ
  e2e/                # Full system tests
```

## Code Patterns

### Error Handling

Use custom exceptions for command failures:

```python
# Permanent failure - goes to troubleshooting immediately
raise PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")

# Transient failure - retried according to policy
raise TransientCommandError(code="TIMEOUT", message="Database timeout")
```

### Repository Pattern

All data access through repository protocols:

```python
class CommandRepository(Protocol):
    async def save(self, command: CommandMetadata) -> None: ...
    async def get_by_id(self, domain: str, command_id: UUID) -> CommandMetadata | None: ...
```

### Transactions

Use context managers for transactional operations:

```python
async with self.pool.connection() as conn:
    async with conn.transaction():
        await self.repo.save(command, conn=conn)
        await self.pgmq.send(queue, payload, conn=conn)
```

## Testing Requirements

- Unit tests: No Postgres, use `FakePgmqClient` from `testing/fakes.py`
- Integration tests: Use `@pytest.mark.integration` marker
- All public methods must have type hints

### Coverage Requirements (MANDATORY)

**80% line and branch coverage is required for ALL commits.**

This is enforced via pre-commit hook. Commits will be **rejected** if coverage falls below 80%.

```bash
# Check coverage before committing
make test-coverage

# View detailed coverage report
make coverage-html
```

If coverage drops below 80%:
1. Write additional tests to cover uncovered code paths
2. Focus on branch coverage (if/else, try/except paths)
3. Do NOT reduce coverage threshold - add tests instead
4. Report to user if unable to achieve 80% coverage

## Key Files Reference

| Purpose | File |
|---------|------|
| Public API | `src/commandbus/api.py` |
| Domain models | `src/commandbus/models.py` |
| Error types | `src/commandbus/exceptions.py` |
| PGMQ wrapper | `src/commandbus/pgmq/client.py` |
| Test fakes | `src/commandbus/testing/fakes.py` |
| Migrations | `src/commandbus/migrations/` |

## Anti-Patterns to Avoid

- No global state or module-level singletons
- No `print()` statements - use `logging`
- No bare `except:` clauses - catch specific exceptions
- No magic numbers - use named constants
- No mutable default arguments

## Verification Checklist

Before submitting changes:

1. `make lint` passes
2. `make typecheck` passes
3. `make test` passes
4. Coverage not decreased
