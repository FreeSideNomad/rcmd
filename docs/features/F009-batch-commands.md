# F009: Batch Commands

## Summary

Enable applications to group multiple commands into a batch for coordinated tracking, providing aggregate status, counts, and completion callbacks.

## Motivation

Applications often need to send multiple related commands that logically belong together:
- Bulk data imports processing items individually
- Workflow steps that need coordinated completion tracking
- Operations that require all-or-nothing visibility into success rates

Without batch support, applications must implement their own tracking logic outside the command bus, leading to:
- Duplicated coordination code
- Race conditions in completion detection
- Inconsistent status aggregation

## User Stories

- [S041](stories/S041-create-batch.md) - Create a batch with commands
- [S042](stories/S042-batch-status-tracking.md) - Track batch status and counts
- [S043](stories/S043-batch-completion-callback.md) - Receive callback on batch completion
- [S044](stories/S044-query-batches.md) - Query batches and their commands

## Acceptance Criteria (Feature-Level)

- [ ] Batches are created atomically with all their commands in a single operation
- [ ] Batch metadata is stored in `command_bus_batch` table
- [ ] Commands reference their batch via `batch_id` foreign key
- [ ] Batch counters (total, completed, failed, canceled, in_troubleshooting) are updated in real-time
- [ ] Batch status transitions: PENDING → IN_PROGRESS → COMPLETED/COMPLETED_WITH_FAILURES
- [ ] `started_at` is set when first command begins processing
- [ ] `completed_at` is set when all commands reach terminal state
- [ ] TSQ resolutions (operator complete/cancel) update batch counters
- [ ] Audit events `BATCH_STARTED` and `BATCH_COMPLETED` are recorded
- [ ] Optional async callback is invoked on batch completion
- [ ] Referencing non-existent batch_id returns an error

## Technical Design

### Architecture

```
┌─────────────┐     ┌─────────────────────────────────────┐
│ Application │────▶│    CommandBus.create_batch()        │
└─────────────┘     └─────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐
              │  Batch   │   │ Commands │   │  Audit   │
              │  Table   │   │  (PGMQ)  │   │  Table   │
              └──────────┘   └──────────┘   └──────────┘
                    │               │               │
                    └───────────────┴───────────────┘
                              Same Transaction
```

### Batch Lifecycle

```
                    ┌─────────┐
                    │ PENDING │
                    └────┬────┘
                         │ First command starts (RECEIVED)
                         ▼
                   ┌───────────┐
                   │IN_PROGRESS│
                   └─────┬─────┘
                         │ All commands reach terminal state
           ┌─────────────┴─────────────┐
           ▼                           ▼
    ┌───────────┐            ┌─────────────────────┐
    │ COMPLETED │            │COMPLETED_WITH_FAILURES│
    └───────────┘            └─────────────────────┘
    (all success)            (any failed/canceled)
```

### Dependencies

- PostgreSQL 15+ with PGMQ extension
- psycopg3 with connection pool
- Existing CommandBus infrastructure

### Data Changes

#### New Table: `command_bus_batch`

```sql
CREATE TABLE command_bus_batch (
    batch_id UUID PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    custom_data JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    total_count INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    canceled_count INTEGER NOT NULL DEFAULT 0,
    in_troubleshooting_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT valid_status CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'COMPLETED_WITH_FAILURES'))
);

CREATE INDEX idx_batch_domain ON command_bus_batch(domain);
CREATE INDEX idx_batch_status ON command_bus_batch(status);
CREATE INDEX idx_batch_created_at ON command_bus_batch(created_at DESC);
```

#### Modification: `command_bus_command`

```sql
ALTER TABLE command_bus_command
ADD COLUMN batch_id UUID REFERENCES command_bus_batch(batch_id);

CREATE INDEX idx_command_batch_id ON command_bus_command(batch_id);
```

### API Changes

```python
from typing import Callable, Awaitable
from dataclasses import dataclass

@dataclass
class BatchCommand:
    """A command to be included in a batch."""
    command_type: str
    command_id: UUID
    data: dict[str, Any]
    reply_to: str | None = None
    correlation_id: UUID | None = None

@dataclass
class BatchMetadata:
    """Batch metadata returned from queries."""
    batch_id: UUID
    domain: str
    name: str | None
    custom_data: dict[str, Any] | None
    status: str  # PENDING, IN_PROGRESS, COMPLETED, COMPLETED_WITH_FAILURES
    total_count: int
    completed_count: int
    failed_count: int
    canceled_count: int
    in_troubleshooting_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

# Callback type
BatchCompletionCallback = Callable[[BatchMetadata], Awaitable[None]]

class CommandBus:
    async def create_batch(
        self,
        domain: str,
        commands: list[BatchCommand],
        *,
        name: str | None = None,
        custom_data: dict[str, Any] | None = None,
        on_complete: BatchCompletionCallback | None = None,
    ) -> UUID:
        """Create a batch with all commands atomically.

        Args:
            domain: The domain for all commands in the batch
            commands: List of commands to include (must have at least 1)
            name: Optional human-readable batch name
            custom_data: Optional custom metadata for the batch
            on_complete: Optional async callback invoked when batch completes

        Returns:
            The batch_id

        Raises:
            ValueError: If commands list is empty
        """

    async def get_batch(
        self,
        domain: str,
        batch_id: UUID,
    ) -> BatchMetadata | None:
        """Get batch metadata by ID."""

    async def list_batches(
        self,
        domain: str,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BatchMetadata]:
        """List batches for a domain."""

    async def list_batch_commands(
        self,
        domain: str,
        batch_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CommandMetadata]:
        """List commands in a batch."""
```

### Counter Update Logic

Counters are updated by database triggers or stored procedures when:

1. **Command RECEIVED** (first processing):
   - If batch `status = PENDING`, set `status = IN_PROGRESS`, `started_at = NOW()`
   - Record `BATCH_STARTED` audit event

2. **Command COMPLETED**:
   - Increment `completed_count`
   - Check for batch completion

3. **Command moved to TSQ** (permanent failure or exhaustion):
   - Increment `in_troubleshooting_count`

4. **TSQ Operator Complete**:
   - Decrement `in_troubleshooting_count`
   - Increment `completed_count`
   - Check for batch completion

5. **TSQ Operator Cancel**:
   - Decrement `in_troubleshooting_count`
   - Increment `canceled_count`
   - Check for batch completion

6. **Batch Completion Check**:
   - If `completed_count + failed_count + canceled_count = total_count`:
     - Set `completed_at = NOW()`
     - If `failed_count + canceled_count > 0`: set `status = COMPLETED_WITH_FAILURES`
     - Else: set `status = COMPLETED`
     - Record `BATCH_COMPLETED` audit event
     - Invoke `on_complete` callback (if registered)

### Callback Registry

```python
# In-memory registry for batch completion callbacks
# Key: (domain, batch_id), Value: callback function
_batch_callbacks: dict[tuple[str, UUID], BatchCompletionCallback] = {}
```

Callbacks are registered during `create_batch()` and invoked by the worker when detecting batch completion.

## Out of Scope

- Batch cancellation (cancelling all pending commands)
- Adding commands to existing batch after creation
- Cross-domain batches
- Batch priority
- Batch TTL/expiration

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Counter race conditions | Medium | Use database-level atomic updates (triggers/stored procedures) |
| Callback registry lost on restart | Medium | Callbacks are best-effort; applications should poll for completion |
| Large batches causing transaction timeouts | Medium | Document size limits, consider chunked creation |
| Orphaned batches (never complete) | Low | No auto-cleanup; applications monitor via queries |

## Implementation Milestones

- [ ] Milestone 1: Database schema and batch creation
- [ ] Milestone 2: Counter updates via triggers/stored procedures
- [ ] Milestone 3: Query APIs (get_batch, list_batches, list_batch_commands)
- [ ] Milestone 4: Batch audit events (BATCH_STARTED, BATCH_COMPLETED)
- [ ] Milestone 5: Completion callback mechanism
- [ ] Milestone 6: Integration with TSQ operations

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/bus.py` - CommandBus class (add batch methods)
- `src/commandbus/models.py` - Add BatchMetadata, BatchCommand dataclasses
- `src/commandbus/repositories/` - Add batch repository
- `scripts/init-db.sql` - Add batch table and triggers
- `src/commandbus/worker.py` - Trigger batch events on command state changes

**Patterns to Follow:**
- Use `async with conn.transaction()` for atomic batch creation
- Repository pattern for batch database access
- Existing audit event patterns for BATCH_STARTED/BATCH_COMPLETED
- Command audit events should include batch_id when present

**Constraints:**
- Batch creation must be atomic (all commands or none)
- Counter updates must be atomic (use DB triggers/procedures)
- Callbacks are in-memory only (not persisted)
- All commands in a batch belong to the same domain

**Verification Steps:**
1. `make test-unit` - Unit tests pass
2. `make test-integration` - Integration tests pass
3. `make typecheck` - No type errors
4. Create batch, process commands, verify counters and status transitions
