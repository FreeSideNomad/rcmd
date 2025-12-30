# F004: Troubleshooting Queue

## Summary

Provide operator APIs to manage failed commands that require human intervention.

## Motivation

Some commands cannot be processed automatically:
- Permanent failures (invalid data, business rule violations)
- Exhausted retry attempts
- Edge cases requiring investigation

Operators need to:
- View failed commands with full context
- Retry commands after fixing underlying issues
- Cancel commands that should not be processed
- Manually complete commands when appropriate

The troubleshooting queue is not a separate PGMQ queue but a status-based view backed by archived messages.

## User Stories

- [S011](stories/S011-list-troubleshooting.md) - List commands in troubleshooting
- [S012](stories/S012-operator-retry.md) - Operator retry command
- [S013](stories/S013-operator-cancel.md) - Operator cancel command
- [S014](stories/S014-operator-complete.md) - Operator complete command

## Acceptance Criteria (Feature-Level)

- [ ] Commands with status `IN_TROUBLESHOOTING_QUEUE` are queryable
- [ ] Operator can list by domain, command type, date range
- [ ] Operator retry reinserts payload to queue (new msg_id)
- [ ] Operator cancel marks as CANCELED and sends reply
- [ ] Operator complete marks as COMPLETED and sends reply
- [ ] All operator actions are audited with operator identity
- [ ] Archived payload is retrievable for inspection

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Troubleshooting Queue                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │     command_bus_command WHERE status = 'IN_TSQ'      │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                │
│            ┌───────────────┼───────────────┐                │
│            ▼               ▼               ▼                │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐            │
│     │  Retry   │    │  Cancel  │    │ Complete │            │
│     └────┬─────┘    └────┬─────┘    └────┬─────┘            │
│          │               │               │                  │
│          ▼               ▼               ▼                  │
│     ┌──────────┐    ┌──────────┐    ┌──────────┐            │
│     │ PENDING  │    │ CANCELED │    │COMPLETED │            │
│     │ (resend) │    │ (reply)  │    │ (reply)  │            │
│     └──────────┘    └──────────┘    └──────────┘            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Dependencies

- F001: Command Sending (for retry resend)
- F002: Command Processing (reply sending)
- F003: Retry & Error Handling (IN_TROUBLESHOOTING_QUEUE status)

### Data Changes

- `command_bus_command.status` = 'IN_TROUBLESHOOTING_QUEUE' for failed commands
- Payload archived via `pgmq.archive()` for retrieval
- Audit events: OPERATOR_RETRY, OPERATOR_CANCEL, OPERATOR_COMPLETE

### API Changes

```python
class CommandBus:
    async def list_troubleshooting(
        self,
        domain: str,
        *,
        command_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TroubleshootingItem]:
        """List commands in troubleshooting queue."""

    async def operator_retry(
        self,
        domain: str,
        command_id: UUID,
        *,
        operator: str | None = None,
    ) -> UUID:
        """Retry a command from troubleshooting queue."""

    async def operator_cancel(
        self,
        domain: str,
        command_id: UUID,
        reason: str,
        *,
        operator: str | None = None,
    ) -> None:
        """Cancel a command in troubleshooting queue."""

    async def operator_complete(
        self,
        domain: str,
        command_id: UUID,
        *,
        result_data: dict[str, Any] | None = None,
        operator: str | None = None,
    ) -> None:
        """Manually complete a command in troubleshooting queue."""

@dataclass
class TroubleshootingItem:
    domain: str
    command_id: UUID
    command_type: str
    attempts: int
    last_error_code: str | None
    last_error_msg: str | None
    created_at: datetime
    updated_at: datetime
    payload: dict[str, Any] | None  # From archive
```

## Out of Scope

- Bulk operations (retry all, cancel all)
- Automatic escalation (email, Slack)
- TTL-based auto-cancel
- UI for troubleshooting (API only)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Payload not in archive | Medium | Use pgmq.archive() consistently, optional payload_archive table |
| Operator without permission | Medium | Document: wrap with authz layer |
| Retry creates duplicates | Low | Same command_id, uniqueness enforced |

## Implementation Milestones

- [ ] Milestone 1: List troubleshooting commands
- [ ] Milestone 2: Operator retry
- [ ] Milestone 3: Operator cancel with reply
- [ ] Milestone 4: Operator complete with reply

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/ops/troubleshooting.py` - Operator APIs
- `src/commandbus/repositories/postgres.py` - Query methods

**Patterns to Follow:**
- Include operator identity in audit records
- Transactional state changes with reply sending
- Validate command is in correct status before action

**Constraints:**
- Can only operate on commands with status IN_TROUBLESHOOTING_QUEUE
- Retry resets attempts to 0 (configurable)
- Must retrieve payload from PGMQ archive table

**Verification Steps:**
1. `make test-unit` - Operator API tests
2. `make test-e2e` - Full troubleshooting workflow
3. Verify audit trail includes operator identity
