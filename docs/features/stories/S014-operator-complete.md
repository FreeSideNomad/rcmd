# S014: Operator Complete Command

## Parent Feature

[F004 - Troubleshooting Queue](../F004-troubleshooting-queue.md)

## User Story

**As an** operator
**I want** to manually complete a command in troubleshooting
**So that** I can resolve it when the work was done outside the system

## Context

Sometimes the action a command represents is completed manually or through another system. Operators can mark these commands as complete, sending a SUCCESS reply with optional result data.

## Acceptance Criteria (Given-When-Then)

### Scenario: Complete a command manually

**Given** a command is in troubleshooting with command_id "abc-123"
**When** I call operator_complete(domain="payments", command_id="abc-123")
**Then** command status is set to "COMPLETED"
**And** a reply message is sent with outcome="SUCCESS"
**And** an audit event "OPERATOR_COMPLETE" is recorded

### Scenario: Complete with result data

**Given** a command is in troubleshooting
**When** I call operator_complete with result_data={"order_id": "xyz"}
**Then** the reply message includes data={"order_id": "xyz"}

### Scenario: Complete includes operator identity

**Given** a command is in troubleshooting
**When** I call operator_complete with operator="jane@example.com"
**Then** the audit event includes operator="jane@example.com"

### Scenario: Complete non-troubleshooting command fails

**Given** a command has status "COMPLETED"
**When** I call operator_complete for that command
**Then** an `InvalidOperationError` is raised
**And** the error indicates command is not in troubleshooting

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Status set to COMPLETED | Unit | `tests/unit/test_ops.py::test_complete_sets_status` |
| Reply sent | Unit | `tests/unit/test_ops.py::test_complete_sends_reply` |
| Result data in reply | Unit | `tests/unit/test_ops.py::test_complete_includes_data` |
| Operator in audit | Unit | `tests/unit/test_ops.py::test_complete_records_operator` |
| Full flow | Integration | `tests/integration/test_ops.py::test_operator_complete_flow` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S011: List commands in troubleshooting

## Technical Notes

- Reply format per spec section 7.2 with outcome="SUCCESS"
- result_data is optional
- Status is terminal

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/ops/troubleshooting.py` - operator_complete()
- `docs/command-bus-python-spec.md` - Section 7.2

**Constraints:**
- Only complete commands in IN_TROUBLESHOOTING_QUEUE status
- Must send reply to configured reply_queue
- result_data is optional

**Verification Steps:**
1. Run `pytest tests/unit/test_ops.py::test_complete -v`
2. Run `pytest tests/integration/test_ops.py::test_complete -v`
3. Verify reply is received

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
