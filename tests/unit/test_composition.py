"""Tests demonstrating the composition root pattern.

This module contains tests that verify the composition root pattern
for wiring dependencies in an application. The composition root is
the single place where all concrete implementations are instantiated
and dependencies are wired together.

These tests demonstrate:
- Proper layering of dependencies (repositories -> services -> handlers)
- Handler registration via register_instance()
- Testing composition with mocks
- Factory functions returning ready-to-use components
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from commandbus import Command, HandlerContext, HandlerRegistry
from commandbus.handler import handler

# =============================================================================
# Example Domain Classes for Testing Composition
# =============================================================================


class AccountRepository:
    """Example repository - Layer 1."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def get(self, account_id: str, conn: Any = None) -> dict | None:
        """Get account by ID."""
        return {"id": account_id, "balance": "100.00"}


class LedgerRepository:
    """Example repository - Layer 1."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def record(self, account_id: str, amount: str, entry_type: str, conn: Any = None) -> None:
        """Record a ledger entry."""
        pass


class PaymentService:
    """Example service - Layer 2 (depends on repositories)."""

    def __init__(
        self,
        accounts: AccountRepository,
        ledger: LedgerRepository,
    ) -> None:
        self._accounts = accounts
        self._ledger = ledger

    async def debit(self, account_id: str, amount: str, conn: Any = None) -> dict:
        """Debit an account."""
        account = await self._accounts.get(account_id, conn=conn)
        if account is None:
            raise ValueError(f"Account {account_id} not found")
        await self._ledger.record(account_id, amount, "DEBIT", conn=conn)
        return {"status": "debited", "amount": amount}

    async def credit(self, account_id: str, amount: str, conn: Any = None) -> dict:
        """Credit an account."""
        account = await self._accounts.get(account_id, conn=conn)
        if account is None:
            raise ValueError(f"Account {account_id} not found")
        await self._ledger.record(account_id, amount, "CREDIT", conn=conn)
        return {"status": "credited", "amount": amount}


class PaymentHandlers:
    """Example handlers - Layer 3 (depends on services)."""

    def __init__(self, service: PaymentService) -> None:
        self._service = service

    @handler(domain="payments", command_type="DebitAccount")
    async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> dict:
        """Handle debit command."""
        return await self._service.debit(
            cmd.data["account_id"],
            cmd.data["amount"],
            conn=ctx.conn,
        )

    @handler(domain="payments", command_type="CreditAccount")
    async def handle_credit(self, cmd: Command, ctx: HandlerContext) -> dict:
        """Handle credit command."""
        return await self._service.credit(
            cmd.data["account_id"],
            cmd.data["amount"],
            conn=ctx.conn,
        )


class TransferHandlers:
    """Another handler class for testing multiple registrations."""

    def __init__(self, service: PaymentService) -> None:
        self._service = service

    @handler(domain="payments", command_type="Transfer")
    async def handle_transfer(self, cmd: Command, ctx: HandlerContext) -> dict:
        """Handle transfer command."""
        # Debit from source
        await self._service.debit(
            cmd.data["from_account"],
            cmd.data["amount"],
            conn=ctx.conn,
        )
        # Credit to destination
        await self._service.credit(
            cmd.data["to_account"],
            cmd.data["amount"],
            conn=ctx.conn,
        )
        return {"status": "transferred", "amount": cmd.data["amount"]}


# =============================================================================
# Composition Root Function
# =============================================================================


def create_registry(pool: Any) -> HandlerRegistry:
    """Composition root - wire all dependencies.

    This is the ONLY place where concrete implementations are instantiated.
    All dependencies flow downward: repositories -> services -> handlers.
    """
    # ============================================================
    # Layer 1: Repositories (data access)
    # ============================================================
    account_repo = AccountRepository(pool)
    ledger_repo = LedgerRepository(pool)

    # ============================================================
    # Layer 2: Services (business logic)
    # ============================================================
    payment_service = PaymentService(
        accounts=account_repo,
        ledger=ledger_repo,
    )

    # ============================================================
    # Layer 3: Handlers (command handling)
    # ============================================================
    payment_handlers = PaymentHandlers(payment_service)
    transfer_handlers = TransferHandlers(payment_service)

    # ============================================================
    # Layer 4: Registry (discovery)
    # ============================================================
    registry = HandlerRegistry()
    registry.register_instance(payment_handlers)
    registry.register_instance(transfer_handlers)

    return registry


@dataclass
class AppConfig:
    """Example configuration for composition."""

    database_url: str
    max_retry_attempts: int = 3
    worker_concurrency: int = 5


def create_registry_with_config(pool: Any, config: AppConfig) -> HandlerRegistry:
    """Composition root with configuration."""
    # Same layered approach, but config can influence construction
    account_repo = AccountRepository(pool)
    ledger_repo = LedgerRepository(pool)

    payment_service = PaymentService(
        accounts=account_repo,
        ledger=ledger_repo,
    )

    payment_handlers = PaymentHandlers(payment_service)

    registry = HandlerRegistry()
    registry.register_instance(payment_handlers)

    return registry


# =============================================================================
# Tests
# =============================================================================


class TestCompositionRoot:
    """Tests for the composition root pattern."""

    def test_create_registry_registers_all_handlers(self) -> None:
        """Test that create_registry discovers all handler methods."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        # List all registered handlers
        handlers = registry.registered_handlers()

        expected = [
            ("payments", "DebitAccount"),
            ("payments", "CreditAccount"),
            ("payments", "Transfer"),
        ]

        for domain, command_type in expected:
            assert (domain, command_type) in handlers, f"Missing handler: {domain}.{command_type}"

    def test_registry_has_correct_handler_count(self) -> None:
        """Test that exactly the expected number of handlers are registered."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        handlers = registry.registered_handlers()
        assert len(handlers) == 3

    def test_handlers_wired_with_service(self) -> None:
        """Test that handlers receive correct dependencies."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        # Get handler and verify it's bound to instance with service
        handler_fn = registry.get("payments", "DebitAccount")
        assert handler_fn is not None

        # handler_fn is a bound method, so __self__ is the instance
        handler_instance = handler_fn.__self__
        assert hasattr(handler_instance, "_service")
        assert isinstance(handler_instance._service, PaymentService)

    def test_service_wired_with_repositories(self) -> None:
        """Test that services receive repository dependencies."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        # Get handler instance
        handler_fn = registry.get("payments", "DebitAccount")
        assert handler_fn is not None
        handler_instance = handler_fn.__self__

        # Check service has repositories
        service = handler_instance._service
        assert hasattr(service, "_accounts")
        assert hasattr(service, "_ledger")
        assert isinstance(service._accounts, AccountRepository)
        assert isinstance(service._ledger, LedgerRepository)

    def test_repositories_receive_pool(self) -> None:
        """Test that repositories are created with pool."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        # Get to the repository through the handler
        handler_fn = registry.get("payments", "DebitAccount")
        assert handler_fn is not None
        handler_instance = handler_fn.__self__
        service = handler_instance._service
        account_repo = service._accounts

        # Repository should have received the pool
        assert account_repo._pool is mock_pool

    @pytest.mark.asyncio
    async def test_handlers_dispatch_correctly(self) -> None:
        """Test that wired handlers can be dispatched."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        # Create test command
        cmd = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"account_id": str(uuid4()), "amount": "100.00"},
        )

        ctx = MagicMock(spec=HandlerContext)
        ctx.conn = None

        # Dispatch should work (service will be called)
        result = await registry.dispatch(cmd, ctx)

        # Verify result comes from service
        assert result["status"] == "debited"
        assert result["amount"] == "100.00"

    @pytest.mark.asyncio
    async def test_transfer_handler_uses_service_methods(self) -> None:
        """Test that transfer handler uses both debit and credit."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        from_account = str(uuid4())
        to_account = str(uuid4())

        cmd = Command(
            domain="payments",
            command_type="Transfer",
            command_id=uuid4(),
            data={
                "from_account": from_account,
                "to_account": to_account,
                "amount": "50.00",
            },
        )

        ctx = MagicMock(spec=HandlerContext)
        ctx.conn = None

        result = await registry.dispatch(cmd, ctx)

        assert result["status"] == "transferred"
        assert result["amount"] == "50.00"


class TestCompositionWithConfig:
    """Tests for composition with configuration."""

    def test_config_passed_to_factory(self) -> None:
        """Test that config can be passed to composition root."""
        mock_pool = MagicMock()
        config = AppConfig(
            database_url="postgresql://test",
            max_retry_attempts=5,
            worker_concurrency=10,
        )

        registry = create_registry_with_config(mock_pool, config)

        # Registry should be created
        assert registry.has_handler("payments", "DebitAccount")


class TestCompositionLayering:
    """Tests verifying correct dependency layering."""

    def test_handlers_do_not_access_pool_directly(self) -> None:
        """Test that handlers don't have direct pool access."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        handler_fn = registry.get("payments", "DebitAccount")
        assert handler_fn is not None
        handler_instance = handler_fn.__self__

        # Handler should not have pool
        assert not hasattr(handler_instance, "_pool")
        assert not hasattr(handler_instance, "pool")

    def test_handlers_access_service_only(self) -> None:
        """Test that handlers only have service dependency."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        handler_fn = registry.get("payments", "DebitAccount")
        assert handler_fn is not None
        handler_instance = handler_fn.__self__

        # Check instance __dict__ for dependencies
        instance_dict = handler_instance.__dict__
        assert set(instance_dict.keys()) == {"_service"}

    def test_service_accesses_repositories_only(self) -> None:
        """Test that service has only repository dependencies."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        handler_fn = registry.get("payments", "DebitAccount")
        assert handler_fn is not None
        service = handler_fn.__self__._service

        # Check service __dict__ for dependencies
        instance_dict = service.__dict__
        assert set(instance_dict.keys()) == {"_accounts", "_ledger"}

    def test_repositories_access_pool_only(self) -> None:
        """Test that repositories have only pool dependency."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        handler_fn = registry.get("payments", "DebitAccount")
        assert handler_fn is not None
        account_repo = handler_fn.__self__._service._accounts

        # Check repository __dict__ for dependencies
        instance_dict = account_repo.__dict__
        assert set(instance_dict.keys()) == {"_pool"}


class TestMultipleDomains:
    """Tests for multi-domain composition patterns."""

    def test_multiple_handler_classes_registered(self) -> None:
        """Test that multiple handler classes can be registered."""
        mock_pool = MagicMock()
        registry = create_registry(mock_pool)

        # Both PaymentHandlers and TransferHandlers should be registered
        assert registry.has_handler("payments", "DebitAccount")
        assert registry.has_handler("payments", "CreditAccount")
        assert registry.has_handler("payments", "Transfer")

    def test_handlers_share_service_instance(self) -> None:
        """Test that related handlers can share service instance."""
        mock_pool = MagicMock()

        # Create service once
        account_repo = AccountRepository(mock_pool)
        ledger_repo = LedgerRepository(mock_pool)
        payment_service = PaymentService(account_repo, ledger_repo)

        # Both handler classes use same service
        payment_handlers = PaymentHandlers(payment_service)
        transfer_handlers = TransferHandlers(payment_service)

        # Verify they share the same service instance
        assert payment_handlers._service is payment_service
        assert transfer_handlers._service is payment_service
        assert payment_handlers._service is transfer_handlers._service
