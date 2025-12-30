# S012: Operator Retry Command

## Parent Feature

[F004 - Troubleshooting Queue](../F004-troubleshooting-queue.md)

## User Story

**As an** operator
**I want** to retry a command from troubleshooting
**So that** I can reprocess it after fixing the underlying issue

## Context

After investigating a failed command (fixing data, deploying a fix), operators need to retry it. This re-enqueues the original payload for processing, resets the attempt counter, and returns the command to normal processing flow.

## Acceptance Criteria (Given-When-Then)

### Scenario: Retry a command

**Given** a command is in troubleshooting with command_id "abc-123"
**When** I call operator_retry(domain="payments", command_id="abc-123")
**Then** the original payload is retrieved from archive
**And** a new PGMQ message is sent with the payload
**And** command metadata msg_id is updated to new message ID
**And** command status is set to "PENDING"
**And** attempts is reset to 0
**And** an audit event "OPERATOR_RETRY" is recorded

### Scenario: Retry includes operator identity

**Given** a command is in troubleshooting
**When** I call operator_retry with operator="jane@example.com"
**Then** the audit event includes operator="jane@example.com"

### Scenario: Retry non-troubleshooting command fails

**Given** a command has status "COMPLETED"
**When** I call operator_retry for that command
**Then** an `InvalidOperationError` is raised
**And** the error message indicates the command is not in troubleshooting

### Scenario: Retry command not found

**Given** no command exists with command_id "xyz-999"
**When** I call operator_retry for that command
**Then** a `CommandNotFoundError` is raised

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Payload re-enqueued | Unit | `tests/unit/test_ops.py::test_retry_enqueues_payload` |
| Status reset | Unit | `tests/unit/test_ops.py::test_retry_resets_status` |
| Operator in audit | Unit | `tests/unit/test_ops.py::test_retry_records_operator` |
| Invalid status rejected | Unit | `tests/unit/test_ops.py::test_retry_invalid_status` |
| Full flow | Integration | `tests/integration/test_ops.py::test_operator_retry_flow` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S011: List commands in troubleshooting

## Technical Notes

- Retrieve payload from PGMQ archive table
- Use same `pgmq.send()` as original send
- New msg_id, same command_id (idempotency preserved)
- Consider: reset attempts to 0 or keep history?

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/ops/troubleshooting.py` - operator_retry()
- `docs/command-bus-python-spec.md` - Section 9.5

**Constraints:**
- Only retry commands in IN_TROUBLESHOOTING_QUEUE status
- Must retrieve payload from archive
- Same transaction: send + status update + audit

**Verification Steps:**
1. Run `pytest tests/unit/test_ops.py::test_retry -v`
2. Run `pytest tests/integration/test_ops.py::test_retry -v`
3. Verify command is processed by worker after retry

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
