"""Tests demonstrating the stateless service pattern for asyncio safety.

This module contains tests that verify correct and incorrect patterns
for implementing services that are safe for concurrent asyncio execution.

Services instantiated once at startup and shared across concurrent handlers
must follow the stateless service pattern to avoid race conditions.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest


@dataclass
class Account:
    """Sample account entity for tests."""

    id: UUID
    balance: Decimal
    currency: str


class AccountRepository:
    """Repository with optional connection for transaction participation.

    This demonstrates the correct pattern where the connection is passed
    per-request rather than stored as instance state.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool  # Immutable reference

    async def get(
        self,
        account_id: UUID,
        conn: Any | None = None,
    ) -> Account | None:
        """Get account, using provided connection or acquiring from pool."""
        if conn is not None:
            return await self._get_impl(account_id, conn)

        async with self._pool.connection() as acquired_conn:
            return await self._get_impl(account_id, acquired_conn)

    async def _get_impl(
        self,
        account_id: UUID,
        conn: Any,
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


class PaymentService:
    """Stateless service - safe for concurrent use.

    This demonstrates the correct pattern:
    - Only immutable references to dependencies in __init__
    - All request data via parameters
    - Local variables for computation
    - Connection passed, not stored
    """

    def __init__(
        self,
        accounts: AccountRepository,
        ledger: Any,
    ) -> None:
        # Only immutable references to dependencies
        self._accounts = accounts  # Never reassigned
        self._ledger = ledger  # Never reassigned
        # NO mutable instance state (no self._cache, self._current_*, etc.)

    async def debit(
        self,
        account_id: UUID,
        amount: Decimal,
        conn: Any | None = None,
    ) -> dict:
        """Debit an account - all state is in parameters and locals."""
        # All state is in parameters and local variables
        account = await self._accounts.get(account_id, conn=conn)

        if account is None:
            raise ValueError(f"Account {account_id} not found")

        if account.balance < amount:
            raise ValueError(f"Insufficient funds in account {account_id}")

        new_balance = account.balance - amount  # Local variable

        # In real code, would update account and record ledger entry
        return {"new_balance": str(new_balance)}


class UnsafePaymentService:
    """UNSAFE - race conditions with concurrent tasks.

    This demonstrates the WRONG pattern:
    - Mutable instance state (_cache, _current_account)
    - Request data stored in self
    """

    def __init__(self, accounts: AccountRepository) -> None:
        self._accounts = accounts
        self._cache: dict[UUID, Account] = {}  # DANGER: Shared mutable state
        self._current_account: Account | None = None  # DANGER: Overwritten
        self._request_count = 0  # DANGER: Race condition on increment

    async def debit(self, account_id: UUID, amount: Decimal) -> dict:
        """UNSAFE: Uses mutable instance state."""
        self._request_count += 1  # Race condition!

        self._current_account = await self._accounts.get(account_id)
        await asyncio.sleep(0)  # Task yields here
        # Another task might overwrite self._current_account!

        if self._current_account is None:
            raise ValueError(f"Account {account_id} not found")

        # Using potentially stale/wrong data
        new_balance = self._current_account.balance - amount
        return {"new_balance": str(new_balance)}


class TestStatelessServicePattern:
    """Tests demonstrating stateless service pattern."""

    def test_service_has_no_mutable_state(self) -> None:
        """Verify service only has immutable dependency references."""
        mock_accounts = MagicMock(spec=AccountRepository)
        mock_ledger = MagicMock()

        service = PaymentService(mock_accounts, mock_ledger)

        # Check that the service only stores immutable references
        # by verifying instance __dict__ (actual instance attributes)
        instance_dict = service.__dict__

        assert set(instance_dict.keys()) == {"_accounts", "_ledger"}

        # They should be the injected dependencies (immutable refs)
        assert service._accounts is mock_accounts
        assert service._ledger is mock_ledger

    def test_unsafe_service_has_mutable_state(self) -> None:
        """Verify unsafe service has mutable state (anti-pattern demo)."""
        mock_accounts = MagicMock(spec=AccountRepository)

        service = UnsafePaymentService(mock_accounts)

        # This service has mutable state - this is BAD
        assert hasattr(service, "_cache")
        assert hasattr(service, "_current_account")
        assert hasattr(service, "_request_count")

        # The mutable attributes are initialized
        assert service._cache == {}
        assert service._current_account is None
        assert service._request_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_calls_isolated(self) -> None:
        """Verify concurrent calls to stateless service are isolated."""
        call_log: list[str] = []

        class TestService:
            def __init__(self, repo: Any) -> None:
                self._repo = repo

            async def process(self, item_id: str, value: int, conn: Any = None) -> dict:
                # Simulate async work
                call_log.append(f"start:{item_id}")
                await asyncio.sleep(0.01)

                # Local computation - safe from interference
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
        assert call_log.count("start:B") == 1
        assert call_log.count("end:B") == 1
        assert call_log.count("start:C") == 1
        assert call_log.count("end:C") == 1

    @pytest.mark.asyncio
    async def test_unsafe_service_race_condition(self) -> None:
        """Demonstrate race condition with mutable state (anti-pattern)."""

        class UnsafeService:
            def __init__(self) -> None:
                self._current_value: int | None = None  # UNSAFE!

            async def process(self, value: int) -> int:
                self._current_value = value
                await asyncio.sleep(0.01)  # Yield point
                # Another task may have overwritten _current_value!
                assert self._current_value is not None
                return self._current_value * 2

        service = UnsafeService()

        # Run concurrent calls - results may be wrong!
        # We use _ to indicate we're intentionally not using the result
        # because this test demonstrates the race condition exists,
        # not the specific incorrect values
        _ = await asyncio.gather(
            service.process(10),
            service.process(20),
            service.process(30),
        )

        # This demonstrates the problem - at least one result is likely wrong
        # All might return 60 (30*2) because last write wins
        # We can't assert exact values because behavior is non-deterministic
        # The key point is this code is UNSAFE and should not be used


class TestRepositoryConnectionPattern:
    """Tests for repository connection passing pattern."""

    @pytest.mark.asyncio
    async def test_repository_uses_provided_connection(self) -> None:
        """Verify repository uses provided connection, not pool."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        account_id = uuid4()
        mock_cursor.fetchone = AsyncMock(return_value=(account_id, Decimal("100"), "USD"))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor

        repo = AccountRepository(mock_pool)

        # Call with explicit connection
        result = await repo.get(account_id, conn=mock_conn)

        # Pool should NOT be used
        mock_pool.connection.assert_not_called()

        # Provided connection should be used
        mock_conn.cursor.assert_called_once()

        # Result should be correct
        assert result is not None
        assert result.id == account_id
        assert result.balance == Decimal("100")

    @pytest.mark.asyncio
    async def test_repository_acquires_from_pool_when_no_conn(self) -> None:
        """Verify repository acquires from pool when no connection provided."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor

        @asynccontextmanager
        async def mock_connection():
            yield mock_conn

        mock_pool.connection = mock_connection

        repo = AccountRepository(mock_pool)

        # Call without connection
        result = await repo.get(uuid4())

        # Pool connection should be used via context manager
        mock_conn.cursor.assert_called_once()

        # Result should be None (no account found)
        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_repository_calls_with_separate_connections(
        self,
    ) -> None:
        """Verify concurrent calls with different connections are isolated."""
        results: list[tuple[str, UUID]] = []

        class TestRepository:
            def __init__(self) -> None:
                pass  # No pool needed for test

            async def get_with_tracking(self, item_id: UUID, conn_name: str) -> dict:
                # Simulate async database work
                results.append((f"start:{conn_name}", item_id))
                await asyncio.sleep(0.01)
                results.append((f"end:{conn_name}", item_id))
                return {"id": str(item_id), "conn": conn_name}

        repo = TestRepository()

        id_a = uuid4()
        id_b = uuid4()
        id_c = uuid4()

        # Run concurrent calls with different "connections"
        call_results = await asyncio.gather(
            repo.get_with_tracking(id_a, "conn_a"),
            repo.get_with_tracking(id_b, "conn_b"),
            repo.get_with_tracking(id_c, "conn_c"),
        )

        # Each call should have correct result
        assert call_results[0] == {"id": str(id_a), "conn": "conn_a"}
        assert call_results[1] == {"id": str(id_b), "conn": "conn_b"}
        assert call_results[2] == {"id": str(id_c), "conn": "conn_c"}


class TestServiceReentrancy:
    """Tests verifying service methods are reentrant."""

    @pytest.mark.asyncio
    async def test_service_method_is_reentrant(self) -> None:
        """Verify that multiple concurrent calls to same method are safe."""
        execution_order: list[str] = []

        class ReentrantService:
            def __init__(self) -> None:
                self._call_count_lock = asyncio.Lock()
                self._total_calls = 0

            async def process(self, task_id: str, delay: float) -> dict:
                # Track entry
                execution_order.append(f"enter:{task_id}")

                # Simulate varying work times
                await asyncio.sleep(delay)

                # Local computation only
                result = f"result_{task_id}"

                # Track exit
                execution_order.append(f"exit:{task_id}")

                return {"task_id": task_id, "result": result}

        service = ReentrantService()

        # Start multiple calls with different delays
        results = await asyncio.gather(
            service.process("fast", 0.01),
            service.process("slow", 0.03),
            service.process("medium", 0.02),
        )

        # All should complete with correct results
        assert results[0] == {"task_id": "fast", "result": "result_fast"}
        assert results[1] == {"task_id": "slow", "result": "result_slow"}
        assert results[2] == {"task_id": "medium", "result": "result_medium"}

        # Execution was interleaved (entries happened before all exits)
        # Fast should exit before slow due to shorter delay
        fast_exit_idx = execution_order.index("exit:fast")
        slow_exit_idx = execution_order.index("exit:slow")
        assert fast_exit_idx < slow_exit_idx
