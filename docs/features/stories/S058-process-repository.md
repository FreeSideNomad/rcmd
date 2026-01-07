# S058: Process Repository

## User Story

As a developer, I want a repository for process persistence so that process state survives across operations and can be queried.

## Acceptance Criteria

### AC1: ProcessRepository Protocol
- Given repository abstraction is needed
- When I define ProcessRepository protocol
- Then it has: save, update, get_by_id, find_by_status, log_step, update_step_reply, get_audit_trail, get_completed_steps

### AC2: PostgresProcessRepository Save
- Given a new process is created
- When I call save(process)
- Then process is inserted into commandbus.process table with all fields

### AC3: PostgresProcessRepository Update
- Given a process state changes
- When I call update(process)
- Then process row is updated and updated_at is automatically set to NOW()

### AC4: PostgresProcessRepository Get
- Given I need to load a process
- When I call get_by_id(domain, process_id)
- Then I get ProcessMetadata with deserialized state JSONB or None if not found

### AC5: Find By Status
- Given I need to find processes in specific states
- When I call find_by_status(domain, statuses)
- Then I get list of ProcessMetadata matching any of the statuses

### AC6: Audit Trail Logging
- Given a step executes
- When I call log_step(domain, process_id, entry)
- Then entry is inserted into commandbus.process_audit table

### AC7: Update Step Reply
- Given a reply is received
- When I call update_step_reply(domain, process_id, command_id, entry)
- Then the audit entry for that command_id is updated with reply info

### AC8: Audit Trail Query
- Given I need process history
- When I call get_audit_trail(domain, process_id)
- Then I get list of ProcessAuditEntry ordered by sent_at ascending

### AC9: Get Completed Steps
- Given I need to run compensation
- When I call get_completed_steps(domain, process_id)
- Then I get list of step_names with successful replies

## Implementation Notes

- Location: `src/commandbus/process/repository.py`
- Follow patterns from `src/commandbus/repositories/postgres.py`
- Use psycopg3 async with optional connection parameter
- State field stored as JSONB, deserialized on read
- All methods accept optional `conn: AsyncConnection` parameter

## Database Queries

```sql
-- Save process
INSERT INTO commandbus.process (
    domain, process_id, process_type, status, current_step,
    state, error_code, error_message, created_at, updated_at, completed_at
) VALUES (...)

-- Update process
UPDATE commandbus.process SET
    status = %s, current_step = %s, state = %s,
    error_code = %s, error_message = %s,
    updated_at = NOW(), completed_at = %s
WHERE domain = %s AND process_id = %s

-- Get audit trail
SELECT * FROM commandbus.process_audit
WHERE domain = %s AND process_id = %s
ORDER BY sent_at ASC
```

## Verification

- [ ] All protocol methods implemented
- [ ] State JSONB serialization/deserialization works
- [ ] Audit trail maintains correct order
- [ ] Connection parameter properly propagated
