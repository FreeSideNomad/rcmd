# ADR-004: Single Queue Per Domain

## Status

Accepted

## Date

2024-12-30

## Context

The Command Bus processes commands across multiple domains (e.g., payments, reports, approvals). Each domain may have 10-20 different command types. We need to decide on the queue topology:

1. **Single queue per domain**: All command types for a domain share one queue
2. **Queue per command type**: Each command type gets its own queue

With 5-10 domains and 50-100 total command types, the choice significantly impacts:
- Operational complexity
- Monitoring and observability
- Latency characteristics
- Infrastructure overhead

## Decision

We will use a **single queue per domain** (e.g., `payments__commands`, `reports__commands`).

### Implementation

```
Domain: payments
  Queue: payments__commands
    - DebitAccount
    - CreditAccount
    - RefundPayment
    - ... (10-15 command types)

Domain: reports
  Queue: reports__commands
    - GenerateReport
    - ScheduleReport
    - ... (5-10 command types)
```

Workers subscribe to a domain queue and dispatch to handlers based on command type.

## Alternatives Considered

### Alternative 1: Queue Per Command Type

- **Description**: Create a separate PGMQ queue for each command type (e.g., `payments__debit_account`, `payments__credit_account`)
- **Pros**:
  - Isolation: Long-running commands don't block others
  - Independent scaling: Can dedicate workers to high-volume commands
  - Precise monitoring: Queue depth per command type
  - Priority: Can process critical command types first
- **Cons**:
  - **50-100 queue tables**: Each PGMQ queue creates tables (`pgmq.q_<name>`, `pgmq.a_<name>`)
  - **Operational burden**: Monitoring, alerting, and maintenance for 100+ queues
  - **Worker complexity**: Must manage connections/subscriptions to many queues
  - **Partition explosion**: If using partitioned queues, multiply by partition count
  - **Database bloat**: More tables, more indexes, more vacuum overhead
- **Why rejected**: Infrastructure overhead outweighs latency benefits for our scale

### Alternative 2: Priority Queues Within Domain

- **Description**: Single queue with priority levels (high/medium/low) per domain
- **Pros**:
  - Fewer queues than per-command-type
  - Critical commands processed first
- **Cons**:
  - PGMQ doesn't natively support priority - would need custom implementation
  - Still doesn't fully isolate long-running commands
  - Adds complexity to send/receive logic
- **Why rejected**: Added complexity without solving the core isolation problem

### Alternative 3: Separate Queue for Long-Running Commands

- **Description**: Two queues per domain: one for fast commands, one for slow
- **Pros**:
  - Isolates known slow commands (e.g., report generation)
  - Manageable number of queues (2 per domain = 10-20 total)
- **Cons**:
  - Must categorize commands upfront
  - Migration complexity when command characteristics change
  - Partial solution
- **Why considered for future**: This is a reasonable optimization if latency becomes a problem

## Consequences

### Positive

- **Simple topology**: 5-10 queues total, easy to monitor and operate
- **Fewer database objects**: Minimal table/index overhead
- **Straightforward workers**: One worker per domain, dispatches by type
- **Easy monitoring**: Queue depth per domain is meaningful metric
- **Lower operational burden**: Less to configure, alert on, and maintain

### Negative

- **Head-of-line blocking**: A slow command (e.g., 5-minute report) blocks faster commands behind it
- **No per-type scaling**: Cannot independently scale workers for specific command types
- **Latency variance**: P99 latency depends on slowest command in queue

### Mitigations

For the latency concern:
1. **Increase concurrency**: Run multiple workers per domain (e.g., `concurrency=10`)
2. **Visibility timeout extension**: Long-running handlers extend VT to avoid redelivery
3. **Future optimization**: If needed, split out known slow commands to a separate queue (Alternative 3)

### Neutral

- Workers need handler registry to dispatch by command type
- Monitoring shows aggregate queue depth, not per-command-type depth

## Compliance

N/A

## Related Decisions

- ADR-002: Use PGMQ for Message Queue
- ADR-003: Separate Command Metadata Table

## References

- [AWS SQS Queue Design Patterns](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-best-practices.html)
- [PGMQ Queue Management](https://github.com/pgmq/pgmq#queue-management)
