# F003: Retry & Error Handling

## Summary

Provide automatic retry with backoff for transient failures and immediate escalation for permanent failures.

## Motivation

Command processing can fail for various reasons:
- **Transient failures**: Network timeouts, temporary unavailability, rate limits
- **Permanent failures**: Invalid data, business rule violations, missing dependencies

The system needs to:
- Automatically retry transient failures with backoff
- Immediately escalate permanent failures
- Track attempt counts and error details
- Move exhausted commands to troubleshooting queue

## User Stories

- [S008](stories/S008-transient-retry.md) - Automatic retry on transient failure
- [S009](stories/S009-permanent-failure.md) - Handle permanent failure
- [S010](stories/S010-retry-exhaustion.md) - Handle retry exhaustion

## Acceptance Criteria (Feature-Level)

- [ ] `TransientCommandError` triggers retry via visibility timeout expiry
- [ ] `PermanentCommandError` moves command to troubleshooting immediately
- [ ] Configurable `max_attempts` per command type (default: 3)
- [ ] Configurable backoff schedule (default: 10s, 60s, 300s)
- [ ] Attempt count and last error stored in metadata
- [ ] Exhausted retries move to troubleshooting queue
- [ ] Audit events for each failure and state transition

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Error Classification                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐         ┌──────────────────────┐      │
│  │ TransientCommand │         │  PermanentCommand    │      │
│  │      Error       │         │       Error          │      │
│  └────────┬─────────┘         └──────────┬───────────┘      │
│           │                              │                  │
│           ▼                              ▼                  │
│  ┌──────────────────┐         ┌──────────────────────┐      │
│  │  attempts < max  │         │   Archive message    │      │
│  │  ? let VT expire │         │   Move to trouble-   │      │
│  │  : move to TSQ   │         │   shooting queue     │      │
│  └──────────────────┘         └──────────────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘

VT = Visibility Timeout
TSQ = Troubleshooting Queue
```

### Retry Flow

```
Attempt 1 → Fail (Transient) → Wait 10s → Attempt 2 → Fail → Wait 60s →
Attempt 3 → Fail → Wait 300s → Attempt 4 (if max=4) or → TSQ (if max=3)
```

### Dependencies

- F002: Command Processing (worker infrastructure)

### Data Changes

Updates to `command_bus_command`:
- `attempts` - Incremented on each receive
- `max_attempts` - Set per command type or default
- `last_error_type` - TRANSIENT or PERMANENT
- `last_error_code` - Application-specific code
- `last_error_msg` - Error message

### API Changes

```python
class TransientCommandError(CommandBusError):
    """Raise for retryable failures."""
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...

class PermanentCommandError(CommandBusError):
    """Raise for non-retryable failures."""
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...

@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: tuple[int, ...] = (10, 60, 300)
```

## Out of Scope

- Circuit breaker pattern (future)
- Per-handler timeout (use VT extension)
- Custom exception mapping (treat unknown as transient)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Infinite retry loop | High | Hard cap on max_attempts, exhaustion → TSQ |
| Backoff too aggressive | Medium | Configurable per command type |
| Lost error context | Medium | Store full error details in metadata |

## Implementation Milestones

- [ ] Milestone 1: Exception types and classification
- [ ] Milestone 2: Attempt tracking and VT-based retry
- [ ] Milestone 3: Backoff schedule implementation
- [ ] Milestone 4: Exhaustion handling

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/exceptions.py` - Error types
- `src/commandbus/policies.py` - RetryPolicy
- `src/commandbus/worker.py` - Error handling in worker loop

**Patterns to Follow:**
- Catch specific exceptions, not bare `except:`
- Use `raise ... from e` to preserve exception chain
- Log errors with structured context

**Constraints:**
- Transient retry uses VT expiry, not re-queue
- Must update metadata before releasing message
- Audit every state transition

**Verification Steps:**
1. `make test-unit` - Retry policy tests
2. `make test-e2e` - Transient fail → retry → success scenario
3. `make test-e2e` - Exhaustion → troubleshooting scenario
