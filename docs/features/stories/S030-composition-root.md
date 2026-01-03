# S030: Wire Dependencies in Composition Root

## Parent Feature

[F007 - Handler Dependency Injection](../F007-handler-dependency-injection.md)

## User Story

**As a** application developer
**I want** to wire all dependencies in a single composition root
**So that** my application startup is explicit, testable, and maintainable

## Context

Without a DI framework, dependencies are wired manually in a "composition root" - typically an `app.py` or factory function. This creates all repositories, services, and handlers, then registers handlers with the registry.

The composition root is the only place where concrete implementations are instantiated. All other code depends on abstractions (protocols/interfaces) passed via constructors.

## Acceptance Criteria (Given-When-Then)

### Scenario: Single place for all wiring

**Given** an application with multiple services and handlers
**When** the application starts
**Then** all dependencies are created in one function/module
**And** the dependency graph is visible in one place

### Scenario: Dependencies layered correctly

**Given** a composition root
**When** I read the wiring code
**Then** repositories are created first (Layer 1)
**And** services are created next, receiving repositories (Layer 2)
**And** handlers are created last, receiving services (Layer 3)

### Scenario: Registry populated with handlers

**Given** handler classes are instantiated with dependencies
**When** register_instance() is called for each handler class
**Then** all @handler methods are discovered
**And** the registry is ready for dispatch

### Scenario: Factory returns ready-to-use components

**Given** a composition root factory function
**When** the factory is called with pool
**Then** it returns a configured HandlerRegistry
**And** optionally returns other components (bus, worker)

### Scenario: Test composition root with mocks

**Given** a composition root function
**When** I call it with mock dependencies
**Then** I get handlers wired to mocks
**And** I can test the wiring logic

## Technical Design

### Basic Composition Root

```python
# app.py - Composition Root

from psycopg_pool import AsyncConnectionPool

from commandbus import CommandBus, HandlerRegistry, Worker

# Domain imports
from domain.payments.repositories import AccountRepository, LedgerRepository
from domain.payments.services import PaymentService
from domain.payments.handlers import PaymentHandlers, TransferHandlers


def create_registry(pool: AsyncConnectionPool) -> HandlerRegistry:
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


async def create_application(database_url: str) -> tuple[AsyncConnectionPool, CommandBus, Worker]:
    """Create fully configured application components."""
    pool = AsyncConnectionPool(conninfo=database_url)
    await pool.open()

    registry = create_registry(pool)

    bus = CommandBus(pool)
    worker = Worker(pool, domain="payments", registry=registry)

    return pool, bus, worker
```

### Multi-Domain Composition

```python
def create_registry(pool: AsyncConnectionPool) -> HandlerRegistry:
    """Composition root for multi-domain application."""
    registry = HandlerRegistry()

    # Payments domain
    registry.register_instance(
        PaymentHandlers(
            PaymentService(
                AccountRepository(pool),
                LedgerRepository(pool),
            )
        )
    )

    # Orders domain
    registry.register_instance(
        OrderHandlers(
            OrderService(
                OrderRepository(pool),
                InventoryRepository(pool),
            )
        )
    )

    # Notifications domain
    registry.register_instance(
        NotificationHandlers(
            NotificationService(
                EmailClient(),
                SmsClient(),
            )
        )
    )

    return registry
```

### Testing the Composition Root

```python
# tests/unit/test_composition.py

import pytest
from unittest.mock import MagicMock, AsyncMock

from app import create_registry


class TestCompositionRoot:
    def test_registry_has_all_handlers(self):
        """Verify composition root registers all expected handlers."""
        mock_pool = MagicMock()

        registry = create_registry(mock_pool)

        # Verify all handlers registered
        assert registry.has_handler("payments", "DebitAccount")
        assert registry.has_handler("payments", "CreditAccount")
        assert registry.has_handler("payments", "Transfer")

    def test_handlers_wired_correctly(self):
        """Verify handlers receive correct dependencies."""
        mock_pool = MagicMock()

        registry = create_registry(mock_pool)

        # Get handler and verify it's bound to instance with service
        handler_fn = registry.get("payments", "DebitAccount")

        # handler_fn is a bound method, so __self__ is the instance
        handler_instance = handler_fn.__self__
        assert hasattr(handler_instance, "_service")
        assert handler_instance._service is not None
```

### Composition with Configuration

```python
from dataclasses import dataclass


@dataclass
class AppConfig:
    database_url: str
    max_retry_attempts: int = 3
    worker_concurrency: int = 5
    visibility_timeout: int = 30


def create_registry(pool: AsyncConnectionPool, config: AppConfig) -> HandlerRegistry:
    """Composition root with configuration."""
    # Repositories with config
    account_repo = AccountRepository(pool)

    # Services with config
    payment_service = PaymentService(
        accounts=account_repo,
        ledger=LedgerRepository(pool),
        max_retries=config.max_retry_attempts,  # Config passed to service
    )

    # Handlers
    registry = HandlerRegistry()
    registry.register_instance(PaymentHandlers(payment_service))

    return registry


async def create_application(config: AppConfig) -> Application:
    """Create application with full configuration."""
    pool = AsyncConnectionPool(
        conninfo=config.database_url,
        min_size=2,
        max_size=config.worker_concurrency + 5,
    )
    await pool.open()

    registry = create_registry(pool, config)

    bus = CommandBus(pool, default_max_attempts=config.max_retry_attempts)

    worker = Worker(
        pool=pool,
        domain="payments",
        registry=registry,
        visibility_timeout=config.visibility_timeout,
    )

    return Application(pool=pool, bus=bus, worker=worker)
```

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Single wiring place | Review | Code review checklist |
| Layers correct | Unit | `tests/unit/test_composition.py::test_dependency_layers` |
| All handlers registered | Unit | `tests/unit/test_composition.py::test_all_handlers_registered` |
| Factory returns components | Unit | `tests/unit/test_composition.py::test_factory_returns_components` |
| Testable with mocks | Unit | `tests/unit/test_composition.py::test_with_mock_dependencies` |

## Example Test

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from commandbus import Command, HandlerContext, HandlerRegistry


class TestCompositionRoot:
    def test_create_registry_registers_all_handlers(self):
        """Test that create_registry discovers all handler methods."""
        from app import create_registry

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
            assert (domain, command_type) in handlers, \
                f"Missing handler: {domain}.{command_type}"

    @pytest.mark.asyncio
    async def test_handlers_dispatch_correctly(self):
        """Test that wired handlers can be dispatched."""
        from app import create_registry

        # Mock pool that handlers will use
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_pool.connection.return_value.__aenter__.return_value = mock_conn

        registry = create_registry(mock_pool)

        # Create test command
        cmd = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"account_id": str(uuid4()), "amount": "100.00"},
        )

        ctx = MagicMock(spec=HandlerContext)
        ctx.conn = mock_conn

        # This will fail at DB level but proves wiring works
        with pytest.raises(Exception):
            await registry.dispatch(cmd, ctx)

    def test_repositories_receive_pool(self):
        """Test that repositories are created with pool."""
        from app import create_registry

        mock_pool = MagicMock()

        with patch('app.AccountRepository') as MockAccountRepo:
            with patch('app.LedgerRepository') as MockLedgerRepo:
                create_registry(mock_pool)

                MockAccountRepo.assert_called_once_with(mock_pool)
                MockLedgerRepo.assert_called_once_with(mock_pool)

    def test_services_receive_repositories(self):
        """Test that services receive repository dependencies."""
        from app import create_registry

        mock_pool = MagicMock()

        with patch('app.AccountRepository') as MockAccountRepo:
            with patch('app.LedgerRepository') as MockLedgerRepo:
                with patch('app.PaymentService') as MockPaymentService:
                    mock_account_repo = MockAccountRepo.return_value
                    mock_ledger_repo = MockLedgerRepo.return_value

                    create_registry(mock_pool)

                    MockPaymentService.assert_called_once_with(
                        accounts=mock_account_repo,
                        ledger=mock_ledger_repo,
                    )

    @pytest.mark.asyncio
    async def test_create_application_returns_components(self):
        """Test that create_application returns all needed components."""
        from app import create_application

        with patch('app.AsyncConnectionPool') as MockPool:
            mock_pool = AsyncMock()
            MockPool.return_value = mock_pool

            pool, bus, worker = await create_application("postgresql://test")

            assert pool is mock_pool
            assert bus is not None
            assert worker is not None
            mock_pool.open.assert_called_once()
```

## Story Size

M (2000-4000 tokens, medium feature - mostly patterns)

## Priority (MoSCoW)

Should Have

## Dependencies

- [S026](S026-handler-decorator-class.md) - @handler decorator
- [S027](S027-register-instance.md) - register_instance()
- [S029](S029-stateless-service-pattern.md) - Stateless service pattern

## Technical Notes

### Composition Root Principles

1. **One place for all wiring** - Don't scatter `new` calls throughout code
2. **Layered construction** - Build dependencies bottom-up
3. **Explicit over implicit** - No hidden singletons or service locators
4. **Returns ready components** - Caller receives fully configured objects

### When Composition Root Grows

As the application grows, the composition root becomes verbose. Options:

1. **Split by domain** - One factory per bounded context
   ```python
   def create_payments_handlers(pool): ...
   def create_orders_handlers(pool): ...
   ```

2. **Module-level factories** - Each domain module exports its handlers
   ```python
   # domain/payments/__init__.py
   def create_handlers(pool) -> list[object]:
       return [PaymentHandlers(PaymentService(...))]
   ```

3. **Add DI library later** - When wiring becomes painful, add lagom/dependency-injector

### Avoid These Anti-Patterns

```python
# BAD: Service locator
class PaymentService:
    def __init__(self):
        self._accounts = ServiceLocator.get(AccountRepository)  # Hidden dependency

# BAD: Global singletons
account_repo = AccountRepository(global_pool)  # Module-level instance

# BAD: Constructor creates dependencies
class PaymentHandlers:
    def __init__(self, pool):
        self._service = PaymentService(AccountRepository(pool))  # Inline creation
```

## LLM Agent Instructions

**Reference Files:**
- Create `docs/patterns/composition-root.md` - Pattern documentation
- Create example `app.py` in documentation

**Constraints:**
- This is primarily a documentation/pattern story
- No changes to commandbus library code
- Focus on demonstrating correct composition patterns

**Verification Steps:**
1. Run `pytest tests/unit/test_composition.py -v`
2. Review documentation for completeness

## Definition of Done

- [ ] Pattern documentation created
- [ ] Example composition root documented
- [ ] Multi-domain example included
- [ ] Testing patterns documented
- [ ] Anti-patterns documented
- [ ] Documentation reviewed for clarity
