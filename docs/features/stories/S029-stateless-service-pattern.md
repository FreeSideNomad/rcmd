# S029: Implement Stateless Service Pattern

## Parent Feature

[F007 - Handler Dependency Injection](../F007-handler-dependency-injection.md)

## User Story

**As a** application developer
**I want** guidance on implementing stateless services for handlers
**So that** my services are safe for concurrent asyncio execution

## Context

When using singleton services shared across concurrent handler tasks, developers must follow the stateless service pattern to avoid race conditions. This story documents the pattern and provides tests to verify correct implementation.

Services are instantiated once at startup and shared across all concurrent asyncio tasks. Since asyncio uses cooperative multitasking (single thread, multiple tasks interleaved at await points), mutable instance state can cause race conditions.

## Acceptance Criteria (Given-When-Then)

### Scenario: Service has no mutable instance state

**Given** a service class with constructor-injected dependencies
**When** the service is used by multiple concurrent handlers
**Then** there are no race conditions
**And** each handler call is isolated

### Scenario: All request data passed via parameters

**Given** a service method handling a request
**When** the method executes
**Then** all request-specific data comes from method parameters
**And** no request data is stored in `self`

### Scenario: Connection passed per-request

**Given** a repository method that needs database access
**When** the method is called
**Then** the connection is passed as a parameter
**And** the repository never stores connections in `self`

### Scenario: Service methods are reentrant

**Given** two concurrent handler tasks calling the same service method
**When** both tasks interleave at await points
**Then** each task maintains its own local state
**And** neither task corrupts the other's data

## Technical Design

### Safe Pattern: Stateless Service

```python
class PaymentService:
    """Stateless service - safe for concurrent use."""

    def __init__(
        self,
        accounts: AccountRepository,
        ledger: LedgerRepository,
    ):
        # Only immutable references to dependencies
        self._accounts = accounts  # Never reassigned
        self._ledger = ledger      # Never reassigned
        # NO mutable instance state (no self._cache, self._current_*, etc.)

    async def debit(
        self,
        account_id: UUID,
        amount: Decimal,
        conn: AsyncConnection | None = None,
    ) -> dict:
        # All state is in parameters and local variables
        account = await self._accounts.get(account_id, conn=conn)

        if account.balance < amount:
            raise InsufficientFundsError(account_id, amount)

        new_balance = account.balance - amount  # Local variable

        await self._accounts.update_balance(account_id, new_balance, conn=conn)
        await self._ledger.record(account_id, -amount, "DEBIT", conn=conn)

        return {"new_balance": str(new_balance)}
```

### Unsafe Pattern: Mutable Instance State

```python
class UnsafePaymentService:
    """UNSAFE - race conditions with concurrent tasks."""

    def __init__(self, accounts: AccountRepository):
        self._accounts = accounts
        self._cache = {}              # DANGER: Shared mutable state
        self._current_account = None  # DANGER: Overwritten by concurrent tasks
        self._request_count = 0       # DANGER: Race condition on increment

    async def debit(self, account_id: UUID, amount: Decimal) -> dict:
        self._request_count += 1      # Race condition!

        self._current_account = await self._accounts.get(account_id)
        await asyncio.sleep(0)        # Task yields here
        # Another task might overwrite self._current_account!

        # Using stale/wrong data
        new_balance = self._current_account.balance - amount
        # ...
```

### Repository Pattern with Optional Connection

```python
class AccountRepository:
    """Repository with optional connection for transaction participation."""

    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool  # Immutable reference

    async def get(
        self,
        account_id: UUID,
        conn: AsyncConnection | None = None,
    ) -> Account | None:
        """Get account, using provided connection or acquiring from pool."""
        if conn is not None:
            return await self._get_impl(account_id, conn)

        async with self._pool.connection() as acquired_conn:
            return await self._get_impl(account_id, acquired_conn)

    async def _get_impl(
        self,
        account_id: UUID,
        conn: AsyncConnection,
    ) -> Account | None:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, balance, currency FROM accounts WHERE id = %s",
                (account_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return Account(id=row[0], balance=row[1], currency=row[2])
```

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| No mutable state | Unit | `tests/unit/test_service_pattern.py::test_service_no_mutable_state` |
| Concurrent safety | Integration | `tests/integration/test_concurrency.py::test_concurrent_service_calls` |
| Connection per-request | Unit | `tests/unit/test_service_pattern.py::test_connection_per_request` |
| Reentrant methods | Integration | `tests/integration/test_concurrency.py::test_service_reentrant` |

## Example Test

```python
import pytest
import asyncio
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock


class TestStatelessServicePattern:
    """Tests demonstrating stateless service pattern."""

    def test_service_has_no_mutable_state(self):
        """Verify service only has immutable dependency references."""
        mock_accounts = MagicMock()
        mock_ledger = MagicMock()

        service = PaymentService(mock_accounts, mock_ledger)

        # Only private attributes should be dependency references
        instance_attrs = [a for a in dir(service) if not a.startswith('__')]
        private_attrs = [a for a in instance_attrs if a.startswith('_')]

        # Should only have _accounts and _ledger
        assert set(private_attrs) == {'_accounts', '_ledger'}

        # They should be the injected dependencies (immutable refs)
        assert service._accounts is mock_accounts
        assert service._ledger is mock_ledger

    @pytest.mark.asyncio
    async def test_concurrent_calls_isolated(self):
        """Verify concurrent calls don't interfere with each other."""
        call_log = []

        class TestService:
            def __init__(self, repo):
                self._repo = repo

            async def process(self, item_id: str, value: int, conn=None) -> dict:
                # Simulate async work
                call_log.append(f"start:{item_id}")
                await asyncio.sleep(0.01)

                # Local computation
                result = value * 2

                call_log.append(f"end:{item_id}")
                return {"id": item_id, "result": result}

        service = TestService(MagicMock())

        # Run concurrent calls
        results = await asyncio.gather(
            service.process("A", 10),
            service.process("B", 20),
            service.process("C", 30),
        )

        # Each call should have correct result (not mixed up)
        assert results[0] == {"id": "A", "result": 20}
        assert results[1] == {"id": "B", "result": 40}
        assert results[2] == {"id": "C", "result": 60}

        # Calls interleaved but isolated
        assert call_log.count("start:A") == 1
        assert call_log.count("end:A") == 1

    @pytest.mark.asyncio
    async def test_unsafe_service_race_condition(self):
        """Demonstrate race condition with mutable state (anti-pattern)."""

        class UnsafeService:
            def __init__(self):
                self._current_value = None  # UNSAFE!

            async def process(self, value: int) -> int:
                self._current_value = value
                await asyncio.sleep(0.01)  # Yield point
                # Another task may have overwritten _current_value!
                return self._current_value * 2

        service = UnsafeService()

        # Run concurrent calls - results may be wrong!
        results = await asyncio.gather(
            service.process(10),
            service.process(20),
            service.process(30),
        )

        # This demonstrates the problem - results are unpredictable
        # All might return 60 (30*2) because last write wins
        # In production this would be a subtle, hard-to-debug bug

    @pytest.mark.asyncio
    async def test_repository_uses_provided_connection(self):
        """Verify repository uses provided connection, not pool."""
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(uuid4(), Decimal("100"), "USD"))
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor

        repo = AccountRepository(mock_pool)

        # Call with explicit connection
        await repo.get(uuid4(), conn=mock_conn)

        # Pool should NOT be used
        mock_pool.connection.assert_not_called()

        # Provided connection should be used
        mock_conn.cursor.assert_called_once()

    @pytest.mark.asyncio
    async def test_repository_acquires_from_pool_when_no_conn(self):
        """Verify repository acquires from pool when no connection provided."""
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_pool.connection.return_value.__aenter__.return_value = mock_conn

        repo = AccountRepository(mock_pool)

        # Call without connection
        await repo.get(uuid4())

        # Pool should be used
        mock_pool.connection.assert_called_once()
```

## Story Size

M (2000-4000 tokens, medium feature - mostly documentation)

## Priority (MoSCoW)

Should Have

## Dependencies

- [S028](S028-transaction-participation.md) - Transaction pattern for connection passing

## Technical Notes

### Rules for Stateless Services

1. **Constructor only assigns dependencies**
   ```python
   def __init__(self, repo: Repository):
       self._repo = repo  # OK: immutable reference
       self._cache = {}   # BAD: mutable state
   ```

2. **All request data via parameters**
   ```python
   async def process(self, item_id: str, data: dict, conn=None):  # OK
       self._current_item = item_id  # BAD: storing request state
   ```

3. **Local variables for computation**
   ```python
   result = compute(data)  # OK: local variable
   self._result = compute(data)  # BAD: instance state
   ```

4. **Connection passed, not stored**
   ```python
   async def save(self, entity, conn=None):  # OK
       self._conn = conn  # BAD: storing connection
   ```

### If You Need Caching

Use thread-safe/asyncio-safe primitives:

```python
import asyncio
from cachetools import TTLCache

class CachedRepository:
    def __init__(self, pool):
        self._pool = pool
        self._cache = TTLCache(maxsize=1000, ttl=60)
        self._lock = asyncio.Lock()  # Protect mutations

    async def get(self, id: UUID, conn=None) -> Entity | None:
        # Read without lock (safe in asyncio)
        if id in self._cache:
            return self._cache[id]

        entity = await self._fetch(id, conn)

        # Write with lock
        async with self._lock:
            self._cache[id] = entity

        return entity
```

## LLM Agent Instructions

**Reference Files:**
- Create `docs/patterns/stateless-services.md` - Pattern documentation
- Create `tests/unit/test_service_pattern.py` - Pattern verification tests

**Constraints:**
- This is primarily a documentation/testing story
- No changes to commandbus library code
- Focus on demonstrating correct and incorrect patterns

**Verification Steps:**
1. Run `pytest tests/unit/test_service_pattern.py -v`
2. Review documentation for completeness

## Definition of Done

- [ ] Pattern documentation created
- [ ] Example tests demonstrating safe pattern
- [ ] Example tests demonstrating unsafe anti-patterns
- [ ] Concurrency tests verifying isolation
- [ ] Documentation reviewed for clarity
