# F016: Business Rule Exception

## Summary

Introduce a new `BusinessRuleException` type that enables immediate command failure without operator intervention. When thrown by a command handler, the command status changes directly to FAILED (bypassing the Troubleshooting Queue). For process-managed commands, this triggers immediate compensation, ending the process in CANCELED state.

## Motivation

The current exception hierarchy has two types:
- **TransientCommandError**: Retries according to policy, eventually goes to TSQ if exhausted
- **PermanentCommandError**: Goes directly to TSQ for operator intervention

Both paths require operator action before the system can proceed. However, there are business rule violations where:
1. The failure is deterministic (retrying won't help)
2. Operator intervention isn't needed (the violation is clearly understood)
3. The system should automatically recover via compensation

**Examples:**
- Account closed before statement generation
- Invalid date range in report request
- Missing required data that won't appear later
- Business validation rules that cannot be overridden

Without `BusinessRuleException`, these cases require operator intervention even though the appropriate action (compensation) is predetermined.

## Exception Hierarchy (Updated)

```
CommandError (base)
├── TransientCommandError
│   └── Behavior: Retry → (exhausted) → TSQ → Operator
│
├── PermanentCommandError
│   └── Behavior: Immediate → TSQ → Operator
│
└── BusinessRuleException (NEW)
    └── Behavior: Immediate → FAILED → Auto-compensate (for processes)
```

## User Stories

- [S095](stories/S095-business-rule-exception-class.md) - BusinessRuleException class
- [S096](stories/S096-worker-business-rule-handling.md) - Worker BusinessRuleException handling
- [S097](stories/S097-process-auto-compensation.md) - Process Manager auto-compensation
- [S098](stories/S098-audit-event-types.md) - Audit event types for BusinessRuleException
- [S099](stories/S099-e2e-command-behavior-config.md) - E2E behavior configuration - commands
- [S100](stories/S100-e2e-ui-command-batch-config.md) - E2E UI - command batch business rule config
- [S101](stories/S101-e2e-process-behavior-config.md) - E2E behavior configuration - processes
- [S102](stories/S102-e2e-ui-process-batch-config.md) - E2E UI - process batch business rule config
- [S103](stories/S103-unit-tests.md) - Unit tests for BusinessRuleException
- [S104](stories/S104-integration-tests.md) - Integration tests for BusinessRuleException

## Acceptance Criteria (Feature-Level)

- [ ] `BusinessRuleException` class with code, message, details fields
- [ ] Worker bypasses TSQ, sets command status to FAILED
- [ ] Reply sent with `outcome=FAILED` (distinct from `CANCELED`)
- [ ] Process auto-compensates on FAILED reply
- [ ] Process ends in CANCELED status after compensation
- [ ] Audit events distinguish business rule failures
- [ ] E2E UI allows configuring `fail_business_rule_pct` for commands
- [ ] E2E UI allows configuring `fail_business_rule_pct` per process step
- [ ] 80% test coverage on all new code

## Technical Design

### Exception Handling Flow

```
Handler raises BusinessRuleException
              ↓
┌─────────────────────────────────────┐
│           Worker                     │
│  catch BusinessRuleException:        │
│    status = FAILED                   │
│    audit(BUSINESS_RULE_FAILED)       │
│    send_reply(outcome=FAILED)        │
└───────────────┬─────────────────────┘
                ↓
┌─────────────────────────────────────┐
│     ProcessReplyRouter               │
│  receives reply with outcome=FAILED  │
│  dispatches to ProcessManager        │
└───────────────┬─────────────────────┘
                ↓
┌─────────────────────────────────────┐
│       ProcessManager                 │
│  handle_reply(outcome=FAILED):       │
│    status = COMPENSATING             │
│    _run_compensations()              │
│    status = CANCELED                 │
└─────────────────────────────────────┘
```

### Comparison with Existing Exceptions

| Exception | Retry | TSQ | Operator | Auto-Compensate | Final Status |
|-----------|-------|-----|----------|-----------------|--------------|
| TransientCommandError | Yes | Yes (exhausted) | Yes | No | IN_TSQ |
| PermanentCommandError | No | Yes | Yes | No | IN_TSQ |
| BusinessRuleException | No | No | No | Yes | FAILED |

### Command Status Transitions

```
PENDING → IN_PROGRESS → (BusinessRuleException) → FAILED
                                                      ↓
                                               [Process: COMPENSATING → CANCELED]
```

## Dependencies

- F001: Command Sending
- F002: Command Processing
- F003: Retry/Error Handling
- F013: Process Manager

## Out of Scope

- Configurable compensation strategies (always runs all compensations)
- Partial compensation (all or nothing)
- Business rule exception categories/severity levels
- Custom reply outcomes beyond FAILED

## Implementation Milestones

- [ ] Milestone 1: BusinessRuleException class
- [ ] Milestone 2: Worker exception handling (async + sync)
- [ ] Milestone 3: Process auto-compensation on FAILED reply
- [ ] Milestone 4: Audit event types
- [ ] Milestone 5: E2E command behavior config
- [ ] Milestone 6: E2E process behavior config
- [ ] Milestone 7: E2E UI updates
- [ ] Milestone 8: Unit and integration tests

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/exceptions.py` - Existing exception classes
- `src/commandbus/worker.py` - Async worker exception handling
- `src/commandbus/sync/worker.py` - Sync worker exception handling
- `src/commandbus/process/base.py` - BaseProcessManager with `_run_compensations()`
- `tests/e2e/app/api/schemas.py` - CommandBehavior schema
- `tests/e2e/app/handlers/test_command.py` - Probabilistic handler

**Patterns to Follow:**
- Exception structure from `PermanentCommandError`
- Behavior probability evaluation order in handlers
- Process status transitions from existing `handle_reply()` logic

**Key Constraints:**
- BusinessRuleException MUST NOT go to TSQ
- FAILED reply MUST trigger compensation for processes
- Probability evaluation order: permanent → transient → business_rule → timeout
- `fail_business_rule_pct` separate from existing failure percentages

**Testing Strategy:**
- Unit tests: Mock worker/process, verify status transitions
- Integration tests: Real PostgreSQL, verify full flow
- E2E tests: UI configuration, batch processing
