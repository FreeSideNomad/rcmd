# S010: Handle Retry Exhaustion

## Parent Feature

[F003 - Retry & Error Handling](../F003-retry-error-handling.md)

## User Story

**As a** operations engineer
**I want** exhausted retries to move to troubleshooting
**So that** failing commands don't retry forever

## Context

When a command has failed its maximum number of retry attempts, it should be moved to the troubleshooting queue for operator intervention. This prevents infinite retry loops and surfaces persistent issues.

## Acceptance Criteria (Given-When-Then)

### Scenario: Max attempts exceeded

**Given** a command has max_attempts=3
**And** the command has already failed 2 times (attempts=2)
**When** the handler raises TransientCommandError for the 3rd time
**Then** the PGMQ message is archived
**And** command status is set to "IN_TROUBLESHOOTING_QUEUE"
**And** an audit event "MOVED_TO_TROUBLESHOOTING_QUEUE" with reason "EXHAUSTED" is recorded
**And** no further retries occur

### Scenario: Custom max_attempts per command type

**Given** a handler is registered with RetryPolicy(max_attempts=5)
**When** a command of that type fails 4 times
**Then** it is still retried (attempt 5)
**When** it fails the 5th time
**Then** it moves to troubleshooting

### Scenario: Exhaustion does not send reply

**Given** a command has exhausted its retries
**When** it moves to troubleshooting
**Then** no automatic reply is sent
**And** reply is sent only when operator resolves

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Exhaustion detection | Unit | `tests/unit/test_worker.py::test_exhaustion_detected` |
| Move to TSQ | Unit | `tests/unit/test_worker.py::test_exhaustion_moves_to_tsq` |
| Custom max_attempts | Unit | `tests/unit/test_policies.py::test_custom_max_attempts` |
| Full flow | E2E | `tests/e2e/test_scenarios.py::test_exhaustion_scenario` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S008: Automatic retry on transient failure

## Technical Notes

- Check `attempts >= max_attempts` after incrementing
- Same archive + status flow as permanent failure
- Audit should distinguish "EXHAUSTED" from "PERMANENT"

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/worker.py` - Exhaustion check
- `src/commandbus/policies.py` - RetryPolicy.is_exhausted()
- `docs/command-bus-python-spec.md` - Section 4.3

**Constraints:**
- Check exhaustion after incrementing attempts
- Use same TSQ flow as permanent failure
- Include "EXHAUSTED" in audit details

**Verification Steps:**
1. Run `pytest tests/unit/test_worker.py::test_exhaustion -v`
2. Run `pytest tests/e2e/test_scenarios.py::test_exhaustion -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
