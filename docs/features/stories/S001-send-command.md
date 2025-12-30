# S001: Send a Command

## Parent Feature

[F001 - Command Sending](../F001-command-sending.md)

## User Story

**As a** application developer
**I want** to send a command to a domain queue
**So that** it can be processed asynchronously by a worker

## Context

This is the primary entry point for the Command Bus. Applications create commands with a unique ID, type, and payload, then send them to a domain-specific queue. The command is stored atomically with its metadata and queued for processing.

## Acceptance Criteria (Given-When-Then)

### Scenario: Send a valid command

**Given** the Command Bus is connected to PostgreSQL with PGMQ
**And** the domain queue "payments__commands" exists
**When** I send a command with:
  - domain: "payments"
  - command_type: "DebitAccount"
  - command_id: a new UUID
  - data: {"account_id": "123", "amount": 100}
**Then** the command_id is returned
**And** a row is inserted into `command_bus_command` with status "PENDING"
**And** a message is sent to the PGMQ queue "payments__commands"
**And** an audit event "SENT" is recorded

### Scenario: Send command with reply queue

**Given** the Command Bus is connected
**When** I send a command with reply_to: "payments__replies"
**Then** the reply_queue is stored in command metadata
**And** the reply_to field is included in the message payload

### Scenario: Send command with correlation ID

**Given** the Command Bus is connected
**When** I send a command with correlation_id: a specific UUID
**Then** the correlation_id is stored in command metadata
**And** the correlation_id is included in the message payload

### Scenario: Queue does not exist

**Given** the Command Bus is connected
**And** the queue "newdomain__commands" does not exist
**When** I send a command to domain "newdomain"
**Then** the queue is created automatically (or an error is raised - TBD)

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Valid command stored | Unit | `tests/unit/test_api.py::test_send_command_stores_metadata` |
| Message sent to PGMQ | Unit | `tests/unit/test_api.py::test_send_command_enqueues_message` |
| Audit event recorded | Unit | `tests/unit/test_api.py::test_send_command_records_audit` |
| Full send flow | Integration | `tests/integration/test_send.py::test_send_and_verify` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- PostgreSQL with PGMQ extension running
- Database schema created (`scripts/init-db.sql`)

## Technical Notes

- Use `async with conn.transaction()` to ensure atomicity
- Message payload format defined in spec section 7.1
- Queue naming: domain dots replaced with double underscore

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/api.py` - CommandBus.send() method
- `src/commandbus/pgmq/client.py` - PgmqClient.send()
- `src/commandbus/repositories/postgres.py` - CommandRepository.save()
- `docs/command-bus-python-spec.md` - Section 9.1

**Constraints:**
- All operations in single transaction
- Use parameterized queries
- Return command_id on success

**Verification Steps:**
1. Run `pytest tests/unit/test_api.py::test_send -v`
2. Run `pytest tests/integration/test_send.py -v`
3. Run `make typecheck`

## Definition of Done

- [x] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
