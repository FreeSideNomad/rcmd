# PGMQ Client Specification

## Overview

This specification defines the PGMQ client interface and JdbcTemplate implementation for the Java Command Bus library. The client wraps PGMQ SQL functions for queue operations.

## Package Structure

```
com.commandbus.pgmq/
├── PgmqClient.java           # Interface
└── impl/
    └── JdbcPgmqClient.java   # JdbcTemplate implementation
```

---

## 1. Interface Definition

### 1.1 PgmqClient Interface

```java
package com.commandbus.pgmq;

import com.commandbus.model.PgmqMessage;
import java.util.List;
import java.util.Map;

/**
 * Client for interacting with PGMQ queues.
 *
 * <p>Wraps PGMQ SQL functions for queue operations. All methods support
 * both standalone execution and participation in existing transactions.
 */
public interface PgmqClient {

    /**
     * Create a queue if it doesn't exist.
     *
     * @param queueName Name of the queue to create
     */
    void createQueue(String queueName);

    /**
     * Send a message to a queue.
     *
     * @param queueName Name of the queue
     * @param message Message payload (will be JSON serialized)
     * @return Message ID assigned by PGMQ
     */
    long send(String queueName, Map<String, Object> message);

    /**
     * Send a message to a queue with delay.
     *
     * @param queueName Name of the queue
     * @param message Message payload (will be JSON serialized)
     * @param delaySeconds Delay in seconds before message becomes visible
     * @return Message ID assigned by PGMQ
     */
    long send(String queueName, Map<String, Object> message, int delaySeconds);

    /**
     * Send multiple messages to a queue in a single operation.
     *
     * <p>Uses PGMQ's native send_batch() for optimal performance.
     * Does NOT send NOTIFY - caller is responsible for notification.
     *
     * @param queueName Name of the queue
     * @param messages List of message payloads
     * @return List of message IDs assigned by PGMQ
     */
    List<Long> sendBatch(String queueName, List<Map<String, Object>> messages);

    /**
     * Send multiple messages with delay.
     *
     * @param queueName Name of the queue
     * @param messages List of message payloads
     * @param delaySeconds Delay in seconds
     * @return List of message IDs
     */
    List<Long> sendBatch(String queueName, List<Map<String, Object>> messages, int delaySeconds);

    /**
     * Send a NOTIFY signal for a queue.
     *
     * <p>Used after batch operations to wake up workers.
     *
     * @param queueName Name of the queue
     */
    void notify(String queueName);

    /**
     * Read messages from a queue.
     *
     * @param queueName Name of the queue
     * @param visibilityTimeoutSeconds Seconds before message becomes visible again
     * @param batchSize Maximum number of messages to read
     * @return List of messages (may be empty)
     */
    List<PgmqMessage> read(String queueName, int visibilityTimeoutSeconds, int batchSize);

    /**
     * Read a single message from a queue.
     *
     * @param queueName Name of the queue
     * @param visibilityTimeoutSeconds Visibility timeout in seconds
     * @return Optional message (empty if queue is empty)
     */
    default java.util.Optional<PgmqMessage> readOne(String queueName, int visibilityTimeoutSeconds) {
        var messages = read(queueName, visibilityTimeoutSeconds, 1);
        return messages.isEmpty() ? java.util.Optional.empty() : java.util.Optional.of(messages.get(0));
    }

    /**
     * Delete a message from a queue.
     *
     * @param queueName Name of the queue
     * @param msgId Message ID to delete
     * @return true if message was deleted, false if not found
     */
    boolean delete(String queueName, long msgId);

    /**
     * Archive a message (move to archive table).
     *
     * @param queueName Name of the queue
     * @param msgId Message ID to archive
     * @return true if message was archived
     */
    boolean archive(String queueName, long msgId);

    /**
     * Set visibility timeout for a message.
     *
     * <p>Used for extending visibility timeout for long-running handlers
     * or implementing backoff delays.
     *
     * @param queueName Name of the queue
     * @param msgId Message ID
     * @param visibilityTimeoutSeconds New visibility timeout in seconds from now
     * @return true if timeout was set
     */
    boolean setVisibilityTimeout(String queueName, long msgId, int visibilityTimeoutSeconds);

    /**
     * Get message from archive by command ID.
     *
     * @param queueName Name of the queue
     * @param commandId Command ID to search for
     * @return Optional archived message
     */
    java.util.Optional<PgmqMessage> getFromArchive(String queueName, String commandId);
}
```

---

## 2. Implementation

### 2.1 JdbcPgmqClient

```java
package com.commandbus.pgmq.impl;

import com.commandbus.model.PgmqMessage;
import com.commandbus.pgmq.PgmqClient;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * JdbcTemplate-based implementation of PgmqClient.
 */
@Component
public class JdbcPgmqClient implements PgmqClient {

    private static final Logger log = LoggerFactory.getLogger(JdbcPgmqClient.class);
    private static final String NOTIFY_CHANNEL_PREFIX = "pgmq_notify";
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public JdbcPgmqClient(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    public void createQueue(String queueName) {
        jdbcTemplate.execute("SELECT pgmq.create('" + escapeIdentifier(queueName) + "')");
        log.debug("Created queue: {}", queueName);
    }

    @Override
    public long send(String queueName, Map<String, Object> message) {
        return send(queueName, message, 0);
    }

    @Override
    public long send(String queueName, Map<String, Object> message, int delaySeconds) {
        String json = toJson(message);

        Long msgId = jdbcTemplate.queryForObject(
            "SELECT pgmq.send(?, ?::jsonb, ?)",
            Long.class,
            queueName, json, delaySeconds
        );

        if (msgId == null) {
            throw new RuntimeException("Failed to send message to queue " + queueName);
        }

        // Send NOTIFY to wake up listeners
        String channel = NOTIFY_CHANNEL_PREFIX + "_" + queueName;
        jdbcTemplate.execute("NOTIFY " + escapeIdentifier(channel));

        log.debug("Sent message to {}: msgId={}", queueName, msgId);
        return msgId;
    }

    @Override
    public List<Long> sendBatch(String queueName, List<Map<String, Object>> messages) {
        return sendBatch(queueName, messages, 0);
    }

    @Override
    public List<Long> sendBatch(String queueName, List<Map<String, Object>> messages, int delaySeconds) {
        if (messages.isEmpty()) {
            return List.of();
        }

        // Convert messages to JSON array
        String[] jsonArray = messages.stream()
            .map(this::toJson)
            .toArray(String[]::new);

        // Use ARRAY constructor for PostgreSQL array
        StringBuilder sql = new StringBuilder("SELECT * FROM pgmq.send_batch(?, ARRAY[");
        for (int i = 0; i < jsonArray.length; i++) {
            if (i > 0) sql.append(",");
            sql.append("?::jsonb");
        }
        sql.append("], ?)");

        Object[] params = new Object[jsonArray.length + 2];
        params[0] = queueName;
        System.arraycopy(jsonArray, 0, params, 1, jsonArray.length);
        params[params.length - 1] = delaySeconds;

        List<Long> msgIds = jdbcTemplate.query(sql.toString(), (rs, rowNum) -> rs.getLong(1), params);

        log.debug("Sent {} messages to {}", msgIds.size(), queueName);
        return msgIds;
    }

    @Override
    public void notify(String queueName) {
        String channel = NOTIFY_CHANNEL_PREFIX + "_" + queueName;
        jdbcTemplate.execute("NOTIFY " + escapeIdentifier(channel));
        log.debug("Notified channel {}", channel);
    }

    @Override
    public List<PgmqMessage> read(String queueName, int visibilityTimeoutSeconds, int batchSize) {
        return jdbcTemplate.query(
            "SELECT * FROM pgmq.read(?, ?, ?)",
            this::mapToPgmqMessage,
            queueName, visibilityTimeoutSeconds, batchSize
        );
    }

    @Override
    public boolean delete(String queueName, long msgId) {
        Boolean result = jdbcTemplate.queryForObject(
            "SELECT pgmq.delete(?, ?)",
            Boolean.class,
            queueName, msgId
        );
        return Boolean.TRUE.equals(result);
    }

    @Override
    public boolean archive(String queueName, long msgId) {
        Boolean result = jdbcTemplate.queryForObject(
            "SELECT pgmq.archive(?, ?)",
            Boolean.class,
            queueName, msgId
        );
        return Boolean.TRUE.equals(result);
    }

    @Override
    public boolean setVisibilityTimeout(String queueName, long msgId, int visibilityTimeoutSeconds) {
        // pgmq.set_vt returns the updated message row if successful
        List<PgmqMessage> result = jdbcTemplate.query(
            "SELECT * FROM pgmq.set_vt(?, ?, ?)",
            this::mapToPgmqMessage,
            queueName, msgId, visibilityTimeoutSeconds
        );
        return !result.isEmpty();
    }

    @Override
    public Optional<PgmqMessage> getFromArchive(String queueName, String commandId) {
        String archiveTable = "pgmq.a_" + queueName;

        List<PgmqMessage> results = jdbcTemplate.query(
            "SELECT * FROM " + archiveTable +
            " WHERE message->>'command_id' = ?" +
            " ORDER BY msg_id DESC LIMIT 1",
            this::mapToPgmqMessage,
            commandId
        );

        return results.isEmpty() ? Optional.empty() : Optional.of(results.get(0));
    }

    // --- Helper Methods ---

    private PgmqMessage mapToPgmqMessage(ResultSet rs, int rowNum) throws SQLException {
        long msgId = rs.getLong("msg_id");
        int readCount = rs.getInt("read_ct");

        Timestamp enqueuedAt = rs.getTimestamp("enqueued_at");
        Timestamp vt = rs.getTimestamp("vt");

        String messageJson = rs.getString("message");
        Map<String, Object> message = fromJson(messageJson);

        return new PgmqMessage(
            msgId,
            readCount,
            enqueuedAt != null ? enqueuedAt.toInstant() : null,
            vt != null ? vt.toInstant() : null,
            message
        );
    }

    private String toJson(Map<String, Object> map) {
        try {
            return objectMapper.writeValueAsString(map);
        } catch (JsonProcessingException e) {
            throw new RuntimeException("Failed to serialize message to JSON", e);
        }
    }

    private Map<String, Object> fromJson(String json) {
        if (json == null || json.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(json, MAP_TYPE);
        } catch (JsonProcessingException e) {
            throw new RuntimeException("Failed to deserialize message from JSON", e);
        }
    }

    private String escapeIdentifier(String identifier) {
        // Simple escape - in production, use proper SQL identifier escaping
        return identifier.replaceAll("[^a-zA-Z0-9_]", "_");
    }
}
```

---

## 3. Transactional Support

### 3.1 Transaction Participation

The `JdbcPgmqClient` automatically participates in Spring transactions because it uses `JdbcTemplate`. When called within a `@Transactional` method, all operations share the same connection.

```java
@Service
public class CommandService {

    private final PgmqClient pgmqClient;
    private final CommandRepository commandRepository;

    @Transactional
    public SendResult send(Command command) {
        // All operations in same transaction
        long msgId = pgmqClient.send(queueName, payload);
        commandRepository.save(metadata);
        auditLogger.log(event);
        // NOTIFY sent after transaction commits
        return new SendResult(command.commandId(), msgId);
    }
}
```

### 3.2 NOTIFY Timing

**Important**: `NOTIFY` is sent within the transaction but only visible to listeners after commit. This is the correct behavior - workers should only see messages after they're fully persisted.

---

## 4. Connection Pooling Considerations

### 4.1 Read Operations

For high-throughput workers, consider using a shared connection for batch reads:

```java
/**
 * Read multiple messages efficiently using a shared connection.
 * Use this in workers to reduce connection pool pressure.
 */
public List<PgmqMessage> readWithSharedConnection(String queueName, int vt, int batchSize) {
    // JdbcTemplate automatically uses pooled connections
    // For truly shared connections, use TransactionTemplate
    return transactionTemplate.execute(status -> {
        List<PgmqMessage> messages = pgmqClient.read(queueName, vt, batchSize);
        // Process all messages in same connection
        return messages;
    });
}
```

---

## 5. Queue Naming Convention

```java
/**
 * Queue naming utilities.
 */
public final class QueueNames {

    private QueueNames() {}

    public static final String COMMANDS_SUFFIX = "commands";
    public static final String REPLIES_SUFFIX = "replies";
    public static final String NOTIFY_PREFIX = "pgmq_notify";

    /**
     * Create command queue name from domain.
     */
    public static String commandQueue(String domain) {
        return domain + "__" + COMMANDS_SUFFIX;
    }

    /**
     * Create reply queue name from domain.
     */
    public static String replyQueue(String domain) {
        return domain + "__" + REPLIES_SUFFIX;
    }

    /**
     * Create notify channel name from queue name.
     */
    public static String notifyChannel(String queueName) {
        return NOTIFY_PREFIX + "_" + queueName;
    }
}
```

---

## 6. Message Payload Format

### 6.1 Command Message Structure

```json
{
  "domain": "payments",
  "command_type": "DebitAccount",
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "correlation_id": "660e8400-e29b-41d4-a716-446655440001",
  "data": {
    "account_id": "ACC123",
    "amount": 100
  },
  "reply_to": "payments__replies"
}
```

### 6.2 Reply Message Structure

```json
{
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "correlation_id": "660e8400-e29b-41d4-a716-446655440001",
  "outcome": "SUCCESS",
  "result": {
    "status": "debited",
    "balance": 900
  }
}
```

---

## 7. Error Handling

### 7.1 Queue Not Found

PGMQ automatically creates queues on first use when using `pgmq.send()`. However, for explicit queue creation:

```java
try {
    pgmqClient.createQueue(queueName);
} catch (DataAccessException e) {
    // Queue may already exist - this is OK
    log.debug("Queue {} may already exist: {}", queueName, e.getMessage());
}
```

### 7.2 Message Not Found

```java
boolean deleted = pgmqClient.delete(queueName, msgId);
if (!deleted) {
    log.warn("Message {} not found in queue {} - may have been processed already", msgId, queueName);
}
```

---

## 8. Performance Optimization

### 8.1 Batch Operations

Always prefer batch operations for multiple messages:

```java
// Good - single round trip
List<Long> msgIds = pgmqClient.sendBatch(queueName, messages);
pgmqClient.notify(queueName);

// Bad - N+1 round trips
for (var msg : messages) {
    pgmqClient.send(queueName, msg);  // Each sends NOTIFY
}
```

### 8.2 Visibility Timeout Tuning

| Handler Duration | Recommended VT | Notes |
|-----------------|----------------|-------|
| < 5s | 30s (default) | Standard operations |
| 5-30s | 60s | Database operations |
| 30s-2m | 120s | External API calls |
| > 2m | Use extend | Call extendVisibility() |

---

## 9. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| PG-1 | send() returns valid msg_id | Integration test |
| PG-2 | sendBatch() returns correct number of msg_ids | Integration test |
| PG-3 | read() returns messages in FIFO order | Integration test |
| PG-4 | read() respects visibility timeout | Integration test |
| PG-5 | delete() removes message from queue | Integration test |
| PG-6 | archive() moves message to archive table | Integration test |
| PG-7 | setVisibilityTimeout() extends message visibility | Integration test |
| PG-8 | notify() sends PostgreSQL NOTIFY | Integration test |
| PG-9 | Operations participate in Spring transactions | Integration test |
| PG-10 | JSON serialization handles all data types | Unit test |
