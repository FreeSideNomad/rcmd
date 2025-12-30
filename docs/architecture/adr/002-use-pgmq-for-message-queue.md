# ADR-002: Use PGMQ for Message Queue

## Status

Accepted

## Date

2024-12-30

## Context

The Command Bus library needs a durable message queue for command delivery. Requirements include:

- **At-least-once delivery** with visibility timeout
- **Transactional guarantees** - commands must be sent atomically with business data
- **Operational simplicity** - minimize infrastructure complexity
- **PostgreSQL as system of record** - already used for business data
- **Replay capability** - ability to retry failed commands

Options range from external message brokers (RabbitMQ, Kafka, SQS) to database-backed queues.

## Decision

We will use [PGMQ](https://github.com/pgmq/pgmq) as the message queue implementation.

### Why PGMQ

1. **Transactional Atomicity**: Commands can be enqueued in the same transaction as business data, eliminating dual-write problems

2. **No Additional Infrastructure**: PGMQ is a PostgreSQL extension - no separate broker to deploy, monitor, or maintain

3. **Familiar Operations**: PostgreSQL operational knowledge transfers directly

4. **SQS-Like API**: Familiar visibility timeout semantics for exactly-once delivery within a time window

5. **Archive Table**: Built-in message archival for troubleshooting and audit

### Implementation

- Use `pgmq.send()` for enqueueing commands
- Use `pgmq.read()` with visibility timeout for consuming
- Use `pgmq.delete()` on success, `pgmq.archive()` on failure
- Combine with `pg_notify` for low-latency wake-up

## Alternatives Considered

### Alternative 1: RabbitMQ

- **Description**: External AMQP message broker
- **Pros**: Feature-rich, widely used, good Python libraries
- **Cons**: Additional infrastructure, dual-write problem (cannot transactionally send with DB writes), operational overhead
- **Why rejected**: Transactional atomicity is a core requirement

### Alternative 2: Amazon SQS

- **Description**: Managed cloud message queue
- **Pros**: Fully managed, highly available, familiar API
- **Cons**: Cloud vendor lock-in, dual-write problem, network latency, cost at scale
- **Why rejected**: Transactional atomicity and on-premise deployment requirements

### Alternative 3: Redis Streams

- **Description**: Redis-based streaming with consumer groups
- **Pros**: Low latency, good Python support
- **Cons**: Additional infrastructure, not transactional with PostgreSQL, different persistence model
- **Why rejected**: Transactional atomicity requirement

### Alternative 4: Custom PostgreSQL Queue Table

- **Description**: Build our own queue using FOR UPDATE SKIP LOCKED
- **Pros**: Full control, no extensions needed
- **Cons**: Complex to build correctly, need to handle edge cases, reinventing the wheel
- **Why rejected**: PGMQ already solves this well

### Alternative 5: Apache Kafka

- **Description**: Distributed event streaming platform
- **Pros**: High throughput, replay capability, ecosystem
- **Cons**: Significant complexity, operational overhead, dual-write problem, overkill for this use case
- **Why rejected**: Complexity far exceeds our needs

## Consequences

### Positive

- Single database for both business data and queue
- Atomic transactions across business data and commands
- Simpler deployment and operations
- No dual-write consistency issues
- Built-in message archival

### Negative

- PostgreSQL becomes a bottleneck for both data and messaging
- Requires PGMQ extension installation
- Less throughput than dedicated message brokers (likely not an issue)
- Fewer advanced messaging features (no topic routing, etc.)

### Neutral

- Queue behavior depends on PostgreSQL performance tuning
- Need to manage PostgreSQL storage for archived messages
- Must use psycopg3 (asyncpg doesn't support PGMQ SQL functions easily)

## Compliance

- Messages are stored in PostgreSQL, subject to same backup/recovery as business data
- Archive tables provide audit trail
- No data leaves the database boundary

## Related Decisions

- ADR-001: Use Architectural Decision Records

## References

- [PGMQ GitHub Repository](https://github.com/pgmq/pgmq)
- [PGMQ Python Client](https://github.com/pgmq/pgmq-py)
- [Transactional Outbox Pattern](https://microservices.io/patterns/data/transactional-outbox.html)
