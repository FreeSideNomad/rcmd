# S061: Process Audit Trail Logging

## User Story

As a system operator, I want a complete audit trail of process execution so that I can debug issues and track progress.

## Acceptance Criteria

### AC1: Command Sent Logging
- Given a process step executes
- When a command is sent
- Then an audit entry is created with: step_name, command_id, command_type, command_data, sent_at

### AC2: Reply Received Logging
- Given a reply is received for a command
- When handle_reply processes it
- Then the audit entry is updated with: reply_outcome, reply_data, received_at

### AC3: Audit Entry Ordering
- Given multiple steps execute
- When I query the audit trail
- Then entries are ordered by sent_at ascending

### AC4: Command Data Sanitization
- Given command_data might contain sensitive info
- When storing audit entry
- Then data is stored as-is (sanitization is application responsibility)

### AC5: Full Trail Query
- Given I need complete process history
- When I call get_audit_trail(domain, process_id)
- Then I get all entries showing command-reply pairs in order

### AC6: Step Duration Calculation
- Given an audit entry has sent_at and received_at
- When I calculate duration
- Then I can determine how long each step took

## Implementation Notes

- Location: Audit methods in `src/commandbus/process/repository.py`
- Uses `commandbus.process_audit` table
- command_id is used to correlate command and reply entries

## Database Schema

```sql
CREATE TABLE commandbus.process_audit (
    id BIGSERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    process_id UUID NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    command_id UUID NOT NULL,
    command_type VARCHAR(255) NOT NULL,
    command_data JSONB,
    sent_at TIMESTAMPTZ NOT NULL,
    reply_outcome VARCHAR(50),      -- NULL until reply received
    reply_data JSONB,               -- NULL until reply received
    received_at TIMESTAMPTZ,        -- NULL until reply received
    FOREIGN KEY (domain, process_id) REFERENCES commandbus.process(domain, process_id)
);
```

## Audit Trail Example

```
Process: abc123
Step: statement_query
  Command: StatementQuery (cmd-001) sent at 10:00:00
  Reply: SUCCESS at 10:00:05 (5s)

Step: statement_data_aggregation
  Command: StatementDataAggregation (cmd-002) sent at 10:00:05
  Reply: SUCCESS at 10:00:08 (3s)

Step: statement_render
  Command: StatementRender (cmd-003) sent at 10:00:08
  Reply: SUCCESS at 10:00:10 (2s)

Process COMPLETED at 10:00:10 (total: 10s)
```

## Verification

- [ ] Commands logged with all required fields
- [ ] Replies update existing entries correctly
- [ ] Query returns entries in sent_at order
- [ ] Duration can be calculated from timestamps
