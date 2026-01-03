# F007: Handler Dependency Injection & Transaction Participation

## Summary

Enable handler classes with constructor-injected dependencies and optional transaction participation via `HandlerContext.conn`.

## Motivation

The current handler pattern has limitations:

1. **No Dependency Injection** - Handlers are plain functions that must capture dependencies via closures, making them hard to test and organize across files.

2. **No Transaction Participation** - Handlers run outside the worker's transaction, so handler business logic and command completion are not atomic.

3. **No Service Layer Pattern** - Without DI, it's difficult to implement clean service/repository layering.

Applications need:
- Handler classes with constructor-injected services
- Decorator-based handler discovery (`@handler`)
- Optional transaction participation for atomicity
- Testable, stateless service pattern

## User Stories

- [S026](stories/S026-handler-decorator-class.md) - Use @handler decorator on class methods
- [S027](stories/S027-register-instance.md) - Discover handlers via register_instance()
- [S028](stories/S028-transaction-participation.md) - Handler participates in worker transaction
- [S029](stories/S029-stateless-service-pattern.md) - Implement stateless service pattern
- [S030](stories/S030-composition-root.md) - Wire dependencies in composition root

## Acceptance Criteria (Feature-Level)

- [ ] `@handler(domain, command_type)` decorator marks class methods as handlers
- [ ] `HandlerRegistry.register_instance(obj)` discovers decorated methods
- [ ] `HandlerContext.conn` provides optional database connection
- [ ] Worker wraps handler execution in transaction when conn is used
- [ ] Services/repositories accept optional `conn` parameter
- [ ] Singleton services are safe for concurrent asyncio tasks
- [ ] Existing function-based handlers continue to work

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Composition Root                             │
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐         │
│  │ Repositories │────▶│   Services   │────▶│   Handlers   │         │
│  └──────────────┘     └──────────────┘     └──────────────┘         │
│         │                    │                    │                 │
│         │                    │                    ▼                 │
│         │                    │           ┌──────────────┐           │
│         │                    │           │   Registry   │           │
│         │                    │           │ (discovers   │           │
│         │                    │           │  @handler)   │           │
│         │                    │           └──────────────┘           │
│         │                    │                    │                 │
│         └────────────────────┴────────────────────┘                 │
│                              │                                      │
│                    All share same pool                              │
│                    Each request gets own conn                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Handler Class Pattern

```python
class PaymentHandlers:
    def __init__(self, payment_service: PaymentService):
        self._service = payment_service  # Injected dependency

    @handler(domain="payments", command_type="DebitAccount")
    async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> dict:
        return await self._service.debit(
            account_id=UUID(cmd.data["account_id"]),
            amount=Decimal(cmd.data["amount"]),
            conn=ctx.conn,  # Transaction participation
        )
```

### Transaction Flow

The worker has two phases with different transaction semantics:

#### Phase 1: Receive (Outside Transaction)

```
Worker.receive()
    │
    ├──▶ pgmq.read(vt=30s)              ← Message becomes invisible (VT lock)
    │
    ├──▶ command_repo.get()             ← Auto-commit
    │
    ├──▶ command_repo.increment_attempts() ← Auto-commit
    │
    ├──▶ audit.log(RECEIVED)            ← Auto-commit
    │
    └──▶ command_repo.update_status(IN_PROGRESS) ← Auto-commit
```

**Why no transaction here?**
- PGMQ uses **visibility timeout** as the "lock" mechanism, not database transactions
- Message automatically reappears if worker crashes (at-least-once delivery)
- Long transaction during receive would hold locks unnecessarily
- Operations are idempotent - retry fixes any partial state

#### Phase 2: Process + Complete (Single Transaction)

```
Worker._process_command()
    │
    ▼
async with pool.connection() as conn, conn.transaction():
    │
    ├──▶ context.conn = conn
    │
    ├──▶ handler(command, context)
    │         │
    │         ▼
    │    service.debit(..., conn=ctx.conn)
    │         │
    │         ▼
    │    repo.update(..., conn=conn)  ◀── Same transaction
    │
    ├──▶ pgmq.delete(msg_id, conn)    ◀── Same transaction
    │
    ├──▶ command_repo.update_status(COMPLETED) ◀── Same transaction
    │
    └──▶ audit.log(COMPLETED, conn)   ◀── Same transaction
```

**Why transaction here?**
- Handler business logic + completion must be atomic
- If handler succeeds but delete fails → duplicate processing
- If delete succeeds but status update fails → inconsistent state
- All-or-nothing: either everything commits or everything rolls back

#### Failure Scenarios

| Failure Point | What Happens |
|--------------|--------------|
| Crash during receive phase | Message reappears after VT, retry fixes state |
| Handler raises exception | Transaction rolls back, message reappears after VT |
| Crash after handler, before commit | Transaction rolls back, message reappears |
| Commit succeeds | All changes persisted atomically |

### Concurrency Safety

Services are singletons shared across concurrent asyncio tasks:

```
┌─────────────────────────────────────────────────────────────────┐
│              Single Thread - Event Loop                         │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  Shared Singletons                       │   │
│  │  PaymentService, AccountRepository, LedgerRepository     │   │
│  └──────────────────────────────────────────────────────────┘   │
│         ▲              ▲              ▲              ▲          │
│         │              │              │              │          │
│    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐    ┌────┴────┐     │
│    │ Task 1  │    │ Task 2  │    │ Task 3  │    │ Task 4  │     │
│    │ conn_1  │    │ conn_2  │    │ conn_3  │    │ conn_4  │     │
│    └─────────┘    └─────────┘    └─────────┘    └─────────┘     │
│                                                                 │
│  Safe: Each task has own conn, services are stateless           │
└─────────────────────────────────────────────────────────────────┘
```

**Safety rules:**
- Services hold only immutable references to dependencies
- No mutable instance state (no `self._cache = {}`)
- All request data passed via method parameters
- Each task gets its own `conn` from worker

### Dependencies

- No external DI framework required
- Uses existing psycopg3 connection pool
- Backwards compatible with function handlers

### API Changes

#### New: @handler decorator

```python
def handler(domain: str, command_type: str) -> Callable[[Callable], Callable]:
    """Decorator to mark a method as a command handler."""
```

#### New: HandlerRegistry.register_instance()

```python
def register_instance(self, instance: object) -> list[tuple[str, str]]:
    """Scan instance for @handler decorated methods and register them."""
```

#### Modified: HandlerContext

```python
@dataclass
class HandlerContext:
    command: Command
    attempt: int
    max_attempts: int
    msg_id: int
    visibility_extender: VisibilityExtender | None = None
    conn: AsyncConnection | None = None  # NEW: For transaction participation
```

#### Modified: Worker._process_command()

```python
async def _process_command(self, received: ReceivedCommand, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        async with self._pool.connection() as conn, conn.transaction():
            # Inject connection into context
            received.context.conn = conn

            result = await self._registry.dispatch(received.command, received.context)

            # Complete in same transaction
            await self._complete_in_txn(received, result, conn)
```

## Out of Scope

- DI container/framework (manual wiring is sufficient)
- Automatic dependency resolution
- Scoped/transient lifetimes (all singletons)
- Multi-threaded worker (asyncio only)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Mutable service state | High - race conditions | Document stateless pattern, code review |
| Long transactions | Medium - lock contention | Visibility timeout extension |
| Breaking existing handlers | High | Maintain backwards compatibility |
| Connection leak | High | Use context managers consistently |

## Implementation Milestones

- [ ] Milestone 1: @handler decorator and HandlerMeta
- [ ] Milestone 2: register_instance() discovery
- [ ] Milestone 3: HandlerContext.conn addition
- [ ] Milestone 4: Worker transaction wrapping
- [ ] Milestone 5: Update tests and documentation

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/handler.py` - HandlerRegistry, @handler decorator
- `src/commandbus/models.py` - HandlerContext
- `src/commandbus/worker.py` - Worker._process_command()
- `tests/unit/test_handler.py` - Handler tests
- `tests/integration/test_worker.py` - Worker integration tests

**Patterns to Follow:**
- Stateless services with constructor injection
- Optional `conn` parameter on all repository methods
- Composition root pattern for wiring

**Constraints:**
- Must remain backwards compatible with function handlers
- No external DI library dependencies
- All operations must use asyncio (single thread)
- Services must be stateless for concurrency safety

**Verification Steps:**
1. `make test-unit` - Unit tests pass
2. `make test-integration` - Integration tests pass
3. `make typecheck` - No type errors
4. `make ready` - Full verification
