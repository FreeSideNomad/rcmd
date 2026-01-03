# S041: Create a Batch with Commands

## Parent Feature

[F009 - Batch Commands](../F009-batch-commands.md)

## User Story

**As a** application developer
**I want** to create a batch containing multiple commands atomically
**So that** I can track their collective progress and completion

## Context

Batches group related commands for coordinated tracking. All commands in a batch are created together in a single transaction, ensuring either all commands are queued or none are. The batch is "closed" immediately - no new commands can be added after creation.

## Acceptance Criteria (Given-When-Then)

### Scenario: Create a batch with multiple commands

**Given** the Command Bus is connected to PostgreSQL with PGMQ
**And** the domain queue "payments__commands" exists
**When** I create a batch with:
  - domain: "payments"
  - name: "Monthly billing run"
  - commands: [
      {command_type: "DebitAccount", command_id: UUID1, data: {...}},
      {command_type: "DebitAccount", command_id: UUID2, data: {...}},
      {command_type: "DebitAccount", command_id: UUID3, data: {...}}
    ]
**Then** a batch_id is returned
**And** a row is inserted into `command_bus_batch` with:
  - status: "PENDING"
  - total_count: 3
  - completed_count: 0
  - failed_count: 0
  - canceled_count: 0
  - in_troubleshooting_count: 0
**And** three rows are inserted into `command_bus_command` with batch_id set
**And** three messages are sent to the PGMQ queue "payments__commands"
**And** audit events "SENT" are recorded for each command (with batch_id in metadata)

### Scenario: Create a batch with custom metadata

**Given** the Command Bus is connected
**When** I create a batch with:
  - name: "Import job 12345"
  - custom_data: {"source": "csv", "file_id": "abc123"}
**Then** the name and custom_data are stored in `command_bus_batch`

### Scenario: Create a batch with completion callback

**Given** the Command Bus is connected
**And** I define an async callback function
**When** I create a batch with on_complete: my_callback
**Then** the callback is registered in memory for this batch
**And** the batch_id is returned

### Scenario: Attempt to create empty batch

**Given** the Command Bus is connected
**When** I create a batch with commands: []
**Then** a ValueError is raised with message "Batch must contain at least one command"

### Scenario: Duplicate command_id in batch

**Given** the Command Bus is connected
**When** I create a batch with two commands having the same command_id
**Then** a DuplicateCommandError is raised
**And** no batch or commands are created (transaction rolled back)

### Scenario: Atomic failure

**Given** the Command Bus is connected
**And** command_id UUID2 already exists in the database
**When** I create a batch with commands including UUID2
**Then** a DuplicateCommandError is raised
**And** no batch is created
**And** no other commands from the batch are created

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Batch created with commands | Unit | `tests/unit/test_batch.py::test_create_batch_stores_batch_and_commands` |
| Total count set correctly | Unit | `tests/unit/test_batch.py::test_create_batch_sets_total_count` |
| Commands have batch_id | Unit | `tests/unit/test_batch.py::test_create_batch_links_commands` |
| Empty batch rejected | Unit | `tests/unit/test_batch.py::test_create_batch_rejects_empty` |
| Callback registered | Unit | `tests/unit/test_batch.py::test_create_batch_registers_callback` |
| Full creation flow | Integration | `tests/integration/test_batch.py::test_create_batch_atomic` |
| Duplicate handling | Integration | `tests/integration/test_batch.py::test_create_batch_duplicate_rollback` |

## Story Size

M (2000-4000 tokens, medium feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- PostgreSQL with PGMQ extension running
- Database schema with `command_bus_batch` table
- Existing CommandBus.send() infrastructure

## Technical Notes

- Use `async with conn.transaction()` to ensure atomicity
- Generate batch_id as UUID if not provided
- All commands inherit the batch's domain
- Callback registry is in-memory only (lost on restart)

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/bus.py` - Add create_batch() method
- `src/commandbus/models.py` - Add BatchCommand, BatchMetadata dataclasses
- `src/commandbus/repositories/batch.py` - New batch repository (create)
- `scripts/init-db.sql` - Add batch table schema

**Constraints:**
- All operations in single transaction
- Use parameterized queries
- Validate commands list is non-empty
- Handle duplicate command_id within batch and against existing commands

**Verification Steps:**
1. Run `pytest tests/unit/test_batch.py -v`
2. Run `pytest tests/integration/test_batch.py -v`
3. Run `make typecheck`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
