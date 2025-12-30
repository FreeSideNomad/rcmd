# F001: Command Sending

## Summary

Enable applications to send commands to domain queues with transactional guarantees and idempotency.

## Motivation

Applications need a reliable way to send commands that:
- Are delivered at-least-once to workers
- Support idempotency via client-supplied command IDs
- Are sent atomically with business data in the same transaction
- Include correlation IDs for request tracing

Without this, applications must implement their own queuing logic or risk message loss and duplicate processing.

## User Stories

- [S001](stories/S001-send-command.md) - Send a command to a domain queue
- [S002](stories/S002-idempotent-send.md) - Reject duplicate command IDs
- [S003](stories/S003-send-with-correlation.md) - Send with correlation ID for tracing

## Acceptance Criteria (Feature-Level)

- [ ] Commands are sent to domain-specific queues (e.g., `payments__commands`)
- [ ] Command metadata is stored in `command_bus_command` table
- [ ] PGMQ message and metadata are written in same transaction
- [ ] Duplicate `command_id` within a domain is rejected
- [ ] `pg_notify` is sent to wake workers (optional, configurable)
- [ ] Audit event `SENT` is recorded

## Technical Design

### Architecture

```
┌─────────────┐     ┌─────────────────────────────────────┐
│ Application │────▶│           CommandBus.send()         │
└─────────────┘     └─────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐
              │ Metadata │   │   PGMQ   │   │  Audit   │
              │  Table   │   │  Queue   │   │  Table   │
              └──────────┘   └──────────┘   └──────────┘
                    │               │               │
                    └───────────────┴───────────────┘
                              Same Transaction
```

### Dependencies

- PostgreSQL 15+ with PGMQ extension
- psycopg3 with connection pool

### Data Changes

Uses existing tables from `scripts/init-db.sql`:
- `command_bus_command` - Command metadata
- `command_bus_audit` - Audit trail
- PGMQ queue tables (created via `pgmq.create()`)

### API Changes

```python
class CommandBus:
    async def send(
        self,
        domain: str,
        command_type: str,
        command_id: UUID,
        data: dict[str, Any],
        *,
        reply_to: str | None = None,
        correlation_id: UUID | None = None,
    ) -> UUID:
        """Send a command to the specified domain queue."""
```

## Out of Scope

- Scheduled/delayed sending (future enhancement)
- Batch sending (future enhancement)
- Priority queues
- Cross-domain transactions

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| PGMQ extension not installed | High | Check on startup, clear error message |
| Transaction deadlock | Medium | Use consistent lock ordering |
| Queue doesn't exist | Medium | Auto-create on first send or fail fast |

## Implementation Milestones

- [ ] Milestone 1: Basic send with metadata storage
- [ ] Milestone 2: Idempotency enforcement
- [ ] Milestone 3: pg_notify integration
- [ ] Milestone 4: Audit logging

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/api.py` - Main CommandBus class
- `src/commandbus/pgmq/client.py` - PGMQ wrapper
- `src/commandbus/repositories/postgres.py` - Metadata repository
- `scripts/init-db.sql` - Database schema

**Patterns to Follow:**
- Use `async with conn.transaction()` for atomic operations
- Repository pattern for all database access
- Accept optional `conn` parameter for external transactions

**Constraints:**
- All operations must be in single transaction
- Must use parameterized queries (no SQL injection)
- Must handle `UniqueViolation` for duplicate command_id

**Verification Steps:**
1. `make test-unit` - Unit tests pass
2. `make test-integration` - Integration tests pass
3. `make typecheck` - No type errors
