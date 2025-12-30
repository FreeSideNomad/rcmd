# ADR-003: Separate Command Metadata Table

## Status

Accepted

## Date

2024-12-30

## Context

Commands processed through PGMQ need operational metadata for:
- Status tracking (PENDING, IN_PROGRESS, COMPLETED, IN_TROUBLESHOOTING_QUEUE)
- Retry tracking (attempts, max_attempts, last_error)
- Searchability (by command_id, status, type, domain)
- Audit trail correlation

PGMQ messages have a JSON body field that could store this metadata alongside the command payload. The question is whether to:
1. Store metadata in PGMQ message headers/body (reuse PGMQ tables)
2. Create a separate `command_bus_command` table for metadata

## Decision

We will use a **separate `command_bus_command` table** for command metadata rather than storing it in PGMQ message headers or body.

### Implementation

```sql
CREATE TABLE command_bus_command (
    domain            TEXT NOT NULL,
    command_id        UUID NOT NULL,
    command_type      TEXT NOT NULL,
    status            TEXT NOT NULL,
    msg_id            BIGINT NULL,  -- Reference to current PGMQ message
    attempts          INT NOT NULL DEFAULT 0,
    max_attempts      INT NOT NULL,
    -- ... additional fields
    PRIMARY KEY (domain, command_id)
);

CREATE INDEX ix_command_bus_command_status_type
    ON command_bus_command(status, command_type);
```

The `msg_id` column maintains a loose reference to the PGMQ message but is not a foreign key.

## Alternatives Considered

### Alternative 1: Store Metadata in PGMQ Message Body

- **Description**: Embed all metadata in the JSONB message body alongside command payload
- **Pros**:
  - Single table, no additional infrastructure
  - All data in one place
- **Cons**:
  - JSONB indexing required for queries (e.g., `CREATE INDEX ON pgmq.q_* ((message->>'status'))`)
  - Tight coupling to PGMQ internal table structure
  - PGMQ uses partitioned tables for high-volume queues - indexes must be created on each partition
  - Archive tables have different structure - queries must span both active and archive
  - Updates to metadata require message replacement (delete + insert) rather than UPDATE
  - Breaking change if PGMQ changes internal schema
- **Why rejected**: Tight coupling to PGMQ internals creates maintenance burden and fragility

### Alternative 2: Use PGMQ Message Headers

- **Description**: PGMQ supports a headers field for message metadata
- **Pros**:
  - Designed for metadata use case
  - Doesn't pollute message body
- **Cons**:
  - Same JSONB indexing challenges as Alternative 1
  - Same partitioning and archive table challenges
  - Headers are immutable after send - cannot update status
- **Why rejected**: Immutability of headers makes status tracking impossible

## Consequences

### Positive

- **No tight coupling to PGMQ**: Metadata queries don't depend on PGMQ internal table structure
- **Transactional consistency**: Metadata updates happen in same transaction as PGMQ operations
- **Efficient querying**: Standard B-tree indexes on relational columns
- **Flexibility**: Can add columns, indexes, or change schema without affecting PGMQ
- **Clean separation**: PGMQ handles message delivery, our table handles operational state
- **Portable**: If we ever migrate away from PGMQ, metadata table remains unchanged

### Negative

- **Additional database operation**: Each command operation touches two tables instead of one
- **Slight overhead**: Extra INSERT/UPDATE per command lifecycle
- **Data synchronization**: Must keep `msg_id` in sync when operator retries (new message created)

### Neutral

- **Two sources of truth**: Message exists in PGMQ, metadata in our table - but they serve different purposes
- **msg_id can become stale**: If message is archived or deleted outside our control, msg_id reference is orphaned (acceptable - we use command_id as primary key)

## Compliance

N/A

## Related Decisions

- ADR-002: Use PGMQ for Message Queue

## References

- [PGMQ Partitioned Queues](https://github.com/pgmq/pgmq#partitioned-queues)
- [PostgreSQL JSONB Indexing](https://www.postgresql.org/docs/current/datatype-json.html#JSON-INDEXING)
