# F005: Observability & Audit

## Summary

Provide audit trail and query capabilities for operational visibility into command processing.

## Motivation

Operators and developers need to:
- Trace command lifecycle from send to completion
- Debug issues by viewing state transitions
- Query commands by status, type, and time range
- Monitor queue health and processing metrics

The library provides searchable metadata and append-only audit logs to support these needs.

## User Stories

- [S015](stories/S015-audit-trail.md) - Audit trail for commands
- [S016](stories/S016-query-commands.md) - Query commands by status

## Acceptance Criteria (Feature-Level)

- [ ] All state transitions recorded in `command_bus_audit` table
- [ ] Audit includes: event_type, timestamp, command_id, details
- [ ] Commands queryable by: status, domain, command_type, date range
- [ ] Metadata table has appropriate indexes for common queries
- [ ] Structured logging with correlation_id context

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Observability Layer                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                  Audit Trail                        │    │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐  │    │
│  │  │  SENT   │─▶│RECEIVED │─▶│COMPLETED│  │ FAILED │  │    │
│  │  └─────────┘  └─────────┘  └─────────┘  └────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                  Query Interface                    │    │
│  │  • By status (PENDING, IN_PROGRESS, COMPLETED, ...) │    │
│  │  • By domain and command_type                       │    │
│  │  • By date range                                    │    │
│  │  • By command_id (point lookup)                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Audit Events

| Event Type | When | Details |
|------------|------|---------|
| SENT | Command enqueued | correlation_id, reply_to |
| RECEIVED | Worker leases message | attempt number |
| COMPLETED | Handler succeeds | result summary |
| FAILED | Handler throws | error code, message, type |
| MOVED_TO_TROUBLESHOOTING_QUEUE | Exhausted or permanent | final error |
| OPERATOR_RETRY | Operator action | operator identity |
| OPERATOR_CANCEL | Operator action | operator, reason |
| OPERATOR_COMPLETE | Operator action | operator, result |

### Dependencies

- All other features (audit is cross-cutting)

### Data Changes

Uses existing `command_bus_audit` table:
```sql
CREATE TABLE command_bus_audit (
    audit_id      BIGSERIAL PRIMARY KEY,
    domain        TEXT NOT NULL,
    command_id    UUID NOT NULL,
    event_type    TEXT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details_json  JSONB NULL
);
```

### API Changes

```python
class CommandBus:
    async def get_command(
        self,
        domain: str,
        command_id: UUID,
    ) -> CommandMetadata | None:
        """Get command metadata by ID."""

    async def get_audit_trail(
        self,
        command_id: UUID,
    ) -> list[AuditEvent]:
        """Get audit trail for a command."""

    async def query_commands(
        self,
        *,
        domain: str | None = None,
        status: CommandStatus | None = None,
        command_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CommandMetadata]:
        """Query commands with filters."""

@dataclass
class AuditEvent:
    event_type: str
    timestamp: datetime
    details: dict[str, Any] | None
```

## Out of Scope

- Metrics export (Prometheus, StatsD)
- Distributed tracing integration (OpenTelemetry)
- Log aggregation
- Real-time dashboards

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Audit table grows unbounded | Medium | Document retention policy, partition by date |
| Query performance degrades | Medium | Appropriate indexes, pagination required |
| Missing audit events | Low | Audit in same transaction as state change |

## Implementation Milestones

- [ ] Milestone 1: Audit event recording
- [ ] Milestone 2: Get command and audit trail
- [ ] Milestone 3: Query with filters
- [ ] Milestone 4: Structured logging integration

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/repositories/postgres.py` - Audit and query methods
- `scripts/init-db.sql` - Table definitions and indexes

**Patterns to Follow:**
- Record audit in same transaction as state change
- Use structured logging with `extra` dict
- Paginate all list queries

**Constraints:**
- Audit table is append-only (no updates or deletes)
- details_json is optional, use for additional context
- Limit query results to prevent memory issues

**Verification Steps:**
1. `make test-unit` - Audit recording tests
2. `make test-integration` - Query with filters
3. Verify indexes used via EXPLAIN ANALYZE
