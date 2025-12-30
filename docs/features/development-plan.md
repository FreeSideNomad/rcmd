# Development Plan

## Implementation Sequence

This document defines the logical sequence for implementing user stories based on their dependencies.

### Phase 1: Foundation

| Order | Story | Description | Dependencies | Issue |
|-------|-------|-------------|--------------|-------|
| 1 | S006 | Register Command Handler | None (foundational) | #11 |

### Phase 2: Core Send/Receive

| Order | Story | Description | Dependencies | Issue |
|-------|-------|-------------|--------------|-------|
| 2 | S001 | Send a Command | S006 | #6 |
| 3 | S002 | Idempotent Command Sending | S001 | #7 |
| 4 | S003 | Send with Correlation ID | S001 | #8 |
| 5 | S004 | Receive and Process Command | S001 | #9 |
| 6 | S005 | Complete Command Successfully | S004 | #10 |

### Phase 3: Worker Infrastructure

| Order | Story | Description | Dependencies | Issue |
|-------|-------|-------------|--------------|-------|
| 7 | S007 | Run Worker with Concurrency | S004, S005, S006 | #12 |

### Phase 4: Error Handling

| Order | Story | Description | Dependencies | Issue |
|-------|-------|-------------|--------------|-------|
| 8 | S008 | Automatic Retry on Transient Failure | S004, S006 | #13 |
| 9 | S009 | Handle Permanent Failure | S004, S006 | #14 |
| 10 | S010 | Handle Retry Exhaustion | S008 | #15 |

### Phase 5: Troubleshooting Queue

| Order | Story | Description | Dependencies | Issue |
|-------|-------|-------------|--------------|-------|
| 11 | S011 | List Commands in Troubleshooting | S009, S010 | #16 |
| 12 | S012 | Operator Retry Command | S011 | #17 |
| 13 | S013 | Operator Cancel Command | S011 | #18 |
| 14 | S014 | Operator Complete Command | S011 | #19 |

### Phase 6: Observability

| Order | Story | Description | Dependencies | Issue |
|-------|-------|-------------|--------------|-------|
| 15 | S015 | Audit Trail for Commands | All above (cross-cutting) | #20 |
| 16 | S016 | Query Commands by Status | Commands in metadata table | #21 |

## Dependency Graph

```
S006 (Handler Registry)
  │
  ▼
S001 (Send Command) ──────────────────────────┐
  │                                           │
  ├──▶ S002 (Idempotency)                     │
  │                                           │
  ├──▶ S003 (Correlation ID)                  │
  │                                           │
  ▼                                           │
S004 (Receive Command) ◀──────────────────────┘
  │
  ├──▶ S005 (Complete Command)
  │      │
  │      ▼
  │    S007 (Worker Concurrency)
  │
  ├──▶ S008 (Transient Retry)
  │      │
  │      ▼
  │    S010 (Retry Exhaustion) ───┐
  │                               │
  └──▶ S009 (Permanent Failure) ──┤
                                  │
                                  ▼
                          S011 (List TSQ)
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
        S012 (Retry)       S013 (Cancel)       S014 (Complete)


S015 (Audit Trail) ◀── All features (cross-cutting)
S016 (Query Commands) ◀── Metadata table populated
```

## Milestones

### Milestone 1: MVP Send/Receive
**Stories:** S006, S001, S002, S003, S004, S005

Basic command bus functionality:
- Handler registration
- Send commands with idempotency
- Receive and complete commands
- Correlation ID support

**Exit Criteria:**
- [ ] All Phase 1 & 2 stories complete
- [ ] Integration test: send → receive → complete flow
- [ ] 80% code coverage maintained

### Milestone 2: Production Worker
**Stories:** S007

Concurrent processing infrastructure:
- Configurable concurrency
- pg_notify/LISTEN optimization
- Graceful shutdown

**Exit Criteria:**
- [ ] Worker handles concurrent commands
- [ ] Clean shutdown with in-flight completion
- [ ] 80% code coverage maintained

### Milestone 3: Reliability
**Stories:** S008, S009, S010

Error handling and retry:
- Transient error retry with backoff
- Permanent error escalation
- Retry exhaustion handling

**Exit Criteria:**
- [ ] Transient errors retry automatically
- [ ] Permanent errors go to troubleshooting
- [ ] Exhausted commands escalate properly
- [ ] 80% code coverage maintained

### Milestone 4: Operations
**Stories:** S011, S012, S013, S014

Operator tooling:
- List troubleshooting queue
- Retry, cancel, complete operations
- Operator identity in audit

**Exit Criteria:**
- [ ] Operators can view and manage failed commands
- [ ] All actions are audited
- [ ] 80% code coverage maintained

### Milestone 5: Observability
**Stories:** S015, S016

Query and audit:
- Full audit trail retrieval
- Flexible command queries
- Index optimization

**Exit Criteria:**
- [ ] Complete audit trail for any command
- [ ] Query by status, domain, type, date range
- [ ] 80% code coverage maintained

## Quality Gates

### Coverage Requirements

**MANDATORY: 80% line and branch coverage required for all commits.**

This is enforced via pre-commit hook. Commits will be rejected if coverage falls below 80%.

To check coverage locally:
```bash
make test-coverage
```

### Definition of Done (Per Story)

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] 80% line and branch coverage maintained
- [ ] No regressions in related functionality
- [ ] `make lint` passes
- [ ] `make typecheck` passes

## Feature to Story Mapping

| Feature | Stories | Priority |
|---------|---------|----------|
| F001 - Command Sending | S001, S002, S003 | Must Have |
| F002 - Command Processing | S004, S005, S006, S007 | Must Have |
| F003 - Retry & Error Handling | S008, S009, S010 | Must Have |
| F004 - Troubleshooting Queue | S011, S012, S013, S014 | Must Have |
| F005 - Observability & Audit | S015, S016 | Should Have |
