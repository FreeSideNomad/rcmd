# S013: Operator Cancel Command

## Parent Feature

[F004 - Troubleshooting Queue](../F004-troubleshooting-queue.md)

## User Story

**As an** operator
**I want** to cancel a command in troubleshooting
**So that** I can resolve it when the request should not be processed

## Context

Some failed commands should not be retried (invalid request, duplicate, superseded by another action). Operators cancel these commands, which marks them as terminal and sends a CANCELED reply to notify the original sender.

## Acceptance Criteria (Given-When-Then)

### Scenario: Cancel a command

**Given** a command is in troubleshooting with command_id "abc-123"
**When** I call operator_cancel(domain="payments", command_id="abc-123", reason="Invalid account")
**Then** command status is set to "CANCELED"
**And** a reply message is sent with outcome="CANCELED"
**And** the reply includes the cancellation reason
**And** an audit event "OPERATOR_CANCEL" is recorded with the reason

### Scenario: Cancel includes operator identity

**Given** a command is in troubleshooting
**When** I call operator_cancel with operator="jane@example.com"
**Then** the audit event includes operator="jane@example.com"

### Scenario: Cancel non-troubleshooting command fails

**Given** a command has status "PENDING"
**When** I call operator_cancel for that command
**Then** an `InvalidOperationError` is raised

### Scenario: Reply sent to correct queue

**Given** a command was sent with reply_to="payments__replies"
**When** I cancel the command
**Then** the cancel reply is sent to "payments__replies"

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Status set to CANCELED | Unit | `tests/unit/test_ops.py::test_cancel_sets_status` |
| Reply sent | Unit | `tests/unit/test_ops.py::test_cancel_sends_reply` |
| Reason in reply | Unit | `tests/unit/test_ops.py::test_cancel_includes_reason` |
| Operator in audit | Unit | `tests/unit/test_ops.py::test_cancel_records_operator` |
| Full flow | Integration | `tests/integration/test_ops.py::test_operator_cancel_flow` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S011: List commands in troubleshooting

## Technical Notes

- Reply format per spec section 7.2 with outcome="CANCELED"
- Include reason in error field of reply
- Status is terminal (no further transitions except audit)

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/ops/troubleshooting.py` - operator_cancel()
- `docs/command-bus-python-spec.md` - Section 7.2

**Constraints:**
- Only cancel commands in IN_TROUBLESHOOTING_QUEUE status
- Must send reply to configured reply_queue
- Reason is required

**Verification Steps:**
1. Run `pytest tests/unit/test_ops.py::test_cancel -v`
2. Run `pytest tests/integration/test_ops.py::test_cancel -v`
3. Verify reply is received

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
