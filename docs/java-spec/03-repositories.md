# Repositories Specification

## Overview

This specification defines the repository interfaces and JdbcTemplate implementations for the Java Command Bus library. The repositories provide data access for commands, batches, and audit events.

## Package Structure

```
com.commandbus.repository/
├── CommandRepository.java      # Interface
├── BatchRepository.java        # Interface
├── AuditRepository.java        # Interface
└── impl/
    ├── JdbcCommandRepository.java
    ├── JdbcBatchRepository.java
    └── JdbcAuditRepository.java
```

---

## 1. Command Repository

### 1.1 Interface

```java
package com.commandbus.repository;

import com.commandbus.model.CommandMetadata;
import com.commandbus.model.CommandStatus;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * Repository for command metadata.
 */
public interface CommandRepository {

    /**
     * Save command metadata.
     *
     * @param metadata The command metadata to save
     * @param queueName The queue name for this command
     */
    void save(CommandMetadata metadata, String queueName);

    /**
     * Save multiple command metadata records.
     *
     * @param metadataList List of metadata to save
     * @param queueName The queue name for these commands
     */
    void saveBatch(List<CommandMetadata> metadataList, String queueName);

    /**
     * Get command by domain and command ID.
     *
     * @param domain The domain
     * @param commandId The command ID
     * @return Optional containing metadata if found
     */
    Optional<CommandMetadata> get(String domain, UUID commandId);

    /**
     * Check if command exists.
     *
     * @param domain The domain
     * @param commandId The command ID
     * @return true if command exists
     */
    boolean exists(String domain, UUID commandId);

    /**
     * Check which command IDs exist from a list.
     *
     * @param domain The domain
     * @param commandIds List of command IDs to check
     * @return Set of command IDs that exist
     */
    Set<UUID> existsBatch(String domain, List<UUID> commandIds);

    /**
     * Update command status.
     *
     * @param domain The domain
     * @param commandId The command ID
     * @param status New status
     */
    void updateStatus(String domain, UUID commandId, CommandStatus status);

    /**
     * Query commands with filters.
     *
     * @param status Filter by status (nullable)
     * @param domain Filter by domain (nullable)
     * @param commandType Filter by command type (nullable)
     * @param createdAfter Filter by created_at >= (nullable)
     * @param createdBefore Filter by created_at <= (nullable)
     * @param limit Maximum results
     * @param offset Results to skip
     * @return List of matching commands
     */
    List<CommandMetadata> query(
        CommandStatus status,
        String domain,
        String commandType,
        Instant createdAfter,
        Instant createdBefore,
        int limit,
        int offset
    );

    /**
     * List commands in a batch.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @param status Filter by status (nullable)
     * @param limit Maximum results
     * @param offset Results to skip
     * @return List of commands in the batch
     */
    List<CommandMetadata> listByBatch(
        String domain,
        UUID batchId,
        CommandStatus status,
        int limit,
        int offset
    );

    // --- Stored Procedure Wrappers ---

    /**
     * Atomically receive a command (stored procedure wrapper).
     *
     * <p>Combines: get metadata + increment attempts + update status + insert audit
     *
     * @param domain The domain
     * @param commandId The command ID
     * @param msgId The PGMQ message ID (nullable)
     * @param maxAttempts Max attempts override (nullable)
     * @return Optional containing updated metadata if found and receivable
     */
    Optional<CommandMetadata> spReceiveCommand(
        String domain,
        UUID commandId,
        Long msgId,
        Integer maxAttempts
    );

    /**
     * Atomically finish a command (stored procedure wrapper).
     *
     * <p>Combines: update status/error + insert audit + update batch counters
     *
     * @param domain The domain
     * @param commandId The command ID
     * @param status Target status
     * @param eventType Audit event type
     * @param errorType Error type (nullable)
     * @param errorCode Error code (nullable)
     * @param errorMessage Error message (nullable)
     * @param details Audit details (nullable)
     * @param batchId Batch ID (nullable)
     * @return true if batch is now complete
     */
    boolean spFinishCommand(
        String domain,
        UUID commandId,
        CommandStatus status,
        String eventType,
        String errorType,
        String errorCode,
        String errorMessage,
        String details,
        UUID batchId
    );

    /**
     * Record a transient failure (stored procedure wrapper).
     *
     * @param domain The domain
     * @param commandId The command ID
     * @param errorType Error type
     * @param errorCode Error code
     * @param errorMessage Error message
     * @param attempt Current attempt number
     * @param maxAttempts Max attempts
     * @param msgId PGMQ message ID
     * @return true if recorded
     */
    boolean spFailCommand(
        String domain,
        UUID commandId,
        String errorType,
        String errorCode,
        String errorMessage,
        int attempt,
        int maxAttempts,
        long msgId
    );
}
```

### 1.2 Implementation

```java
package com.commandbus.repository.impl;

import com.commandbus.model.CommandMetadata;
import com.commandbus.model.CommandStatus;
import com.commandbus.repository.CommandRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;

@Repository
public class JdbcCommandRepository implements CommandRepository {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    private static final RowMapper<CommandMetadata> METADATA_MAPPER = (rs, rowNum) -> {
        return new CommandMetadata(
            rs.getString("domain"),
            UUID.fromString(rs.getString("command_id")),
            rs.getString("command_type"),
            CommandStatus.fromValue(rs.getString("status")),
            rs.getInt("attempts"),
            rs.getInt("max_attempts"),
            rs.getObject("msg_id") != null ? rs.getLong("msg_id") : null,
            rs.getString("correlation_id") != null ?
                UUID.fromString(rs.getString("correlation_id")) : null,
            rs.getString("reply_queue"),
            rs.getString("last_error_type"),
            rs.getString("last_error_code"),
            rs.getString("last_error_msg"),
            toInstant(rs.getTimestamp("created_at")),
            toInstant(rs.getTimestamp("updated_at")),
            rs.getString("batch_id") != null ?
                UUID.fromString(rs.getString("batch_id")) : null
        );
    };

    public JdbcCommandRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    public void save(CommandMetadata metadata, String queueName) {
        jdbcTemplate.update("""
            INSERT INTO commandbus.command (
                domain, queue_name, msg_id, command_id, command_type,
                status, attempts, max_attempts, correlation_id, reply_queue,
                batch_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            metadata.domain(),
            queueName,
            metadata.msgId(),
            metadata.commandId(),
            metadata.commandType(),
            metadata.status().getValue(),
            metadata.attempts(),
            metadata.maxAttempts(),
            metadata.correlationId(),
            metadata.replyTo(),
            metadata.batchId(),
            Timestamp.from(metadata.createdAt()),
            Timestamp.from(metadata.updatedAt())
        );
    }

    @Override
    public void saveBatch(List<CommandMetadata> metadataList, String queueName) {
        if (metadataList.isEmpty()) return;

        String sql = """
            INSERT INTO commandbus.command (
                domain, queue_name, msg_id, command_id, command_type,
                status, attempts, max_attempts, correlation_id, reply_queue,
                batch_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """;

        List<Object[]> batchArgs = metadataList.stream()
            .map(m -> new Object[]{
                m.domain(), queueName, m.msgId(), m.commandId(), m.commandType(),
                m.status().getValue(), m.attempts(), m.maxAttempts(),
                m.correlationId(), m.replyTo(), m.batchId(),
                Timestamp.from(m.createdAt()), Timestamp.from(m.updatedAt())
            })
            .toList();

        jdbcTemplate.batchUpdate(sql, batchArgs);
    }

    @Override
    public Optional<CommandMetadata> get(String domain, UUID commandId) {
        List<CommandMetadata> results = jdbcTemplate.query(
            "SELECT * FROM commandbus.command WHERE domain = ? AND command_id = ?",
            METADATA_MAPPER,
            domain, commandId
        );
        return results.isEmpty() ? Optional.empty() : Optional.of(results.get(0));
    }

    @Override
    public boolean exists(String domain, UUID commandId) {
        Integer count = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM commandbus.command WHERE domain = ? AND command_id = ?",
            Integer.class,
            domain, commandId
        );
        return count != null && count > 0;
    }

    @Override
    public Set<UUID> existsBatch(String domain, List<UUID> commandIds) {
        if (commandIds.isEmpty()) return Set.of();

        String placeholders = String.join(",", Collections.nCopies(commandIds.size(), "?"));
        Object[] params = new Object[commandIds.size() + 1];
        params[0] = domain;
        for (int i = 0; i < commandIds.size(); i++) {
            params[i + 1] = commandIds.get(i);
        }

        List<UUID> existing = jdbcTemplate.query(
            "SELECT command_id FROM commandbus.command WHERE domain = ? AND command_id IN (" + placeholders + ")",
            (rs, rowNum) -> UUID.fromString(rs.getString("command_id")),
            params
        );

        return new HashSet<>(existing);
    }

    @Override
    public void updateStatus(String domain, UUID commandId, CommandStatus status) {
        jdbcTemplate.update(
            "UPDATE commandbus.command SET status = ?, updated_at = NOW() WHERE domain = ? AND command_id = ?",
            status.getValue(), domain, commandId
        );
    }

    @Override
    public List<CommandMetadata> query(
            CommandStatus status,
            String domain,
            String commandType,
            Instant createdAfter,
            Instant createdBefore,
            int limit,
            int offset) {

        StringBuilder sql = new StringBuilder("SELECT * FROM commandbus.command WHERE 1=1");
        List<Object> params = new ArrayList<>();

        if (status != null) {
            sql.append(" AND status = ?");
            params.add(status.getValue());
        }
        if (domain != null) {
            sql.append(" AND domain = ?");
            params.add(domain);
        }
        if (commandType != null) {
            sql.append(" AND command_type = ?");
            params.add(commandType);
        }
        if (createdAfter != null) {
            sql.append(" AND created_at >= ?");
            params.add(Timestamp.from(createdAfter));
        }
        if (createdBefore != null) {
            sql.append(" AND created_at <= ?");
            params.add(Timestamp.from(createdBefore));
        }

        sql.append(" ORDER BY created_at DESC LIMIT ? OFFSET ?");
        params.add(limit);
        params.add(offset);

        return jdbcTemplate.query(sql.toString(), METADATA_MAPPER, params.toArray());
    }

    @Override
    public List<CommandMetadata> listByBatch(
            String domain,
            UUID batchId,
            CommandStatus status,
            int limit,
            int offset) {

        StringBuilder sql = new StringBuilder(
            "SELECT * FROM commandbus.command WHERE domain = ? AND batch_id = ?"
        );
        List<Object> params = new ArrayList<>(List.of(domain, batchId));

        if (status != null) {
            sql.append(" AND status = ?");
            params.add(status.getValue());
        }

        sql.append(" ORDER BY created_at ASC LIMIT ? OFFSET ?");
        params.add(limit);
        params.add(offset);

        return jdbcTemplate.query(sql.toString(), METADATA_MAPPER, params.toArray());
    }

    @Override
    public Optional<CommandMetadata> spReceiveCommand(
            String domain,
            UUID commandId,
            Long msgId,
            Integer maxAttempts) {

        List<CommandMetadata> results = jdbcTemplate.query(
            "SELECT * FROM commandbus.sp_receive_command(?, ?, 'IN_PROGRESS', ?, ?)",
            METADATA_MAPPER,
            domain, commandId, msgId, maxAttempts
        );

        return results.isEmpty() ? Optional.empty() : Optional.of(results.get(0));
    }

    @Override
    public boolean spFinishCommand(
            String domain,
            UUID commandId,
            CommandStatus status,
            String eventType,
            String errorType,
            String errorCode,
            String errorMessage,
            String details,
            UUID batchId) {

        Boolean result = jdbcTemplate.queryForObject(
            "SELECT commandbus.sp_finish_command(?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?)",
            Boolean.class,
            domain, commandId, status.getValue(), eventType,
            errorType, errorCode, errorMessage, details, batchId
        );

        return Boolean.TRUE.equals(result);
    }

    @Override
    public boolean spFailCommand(
            String domain,
            UUID commandId,
            String errorType,
            String errorCode,
            String errorMessage,
            int attempt,
            int maxAttempts,
            long msgId) {

        Boolean result = jdbcTemplate.queryForObject(
            "SELECT commandbus.sp_fail_command(?, ?, ?, ?, ?, ?, ?, ?)",
            Boolean.class,
            domain, commandId, errorType, errorCode, errorMessage,
            attempt, maxAttempts, msgId
        );

        return Boolean.TRUE.equals(result);
    }

    private static Instant toInstant(Timestamp ts) {
        return ts != null ? ts.toInstant() : null;
    }
}
```

---

## 2. Batch Repository

### 2.1 Interface

```java
package com.commandbus.repository;

import com.commandbus.model.BatchMetadata;
import com.commandbus.model.BatchStatus;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * Repository for batch metadata.
 */
public interface BatchRepository {

    /**
     * Save batch metadata.
     *
     * @param metadata The batch metadata to save
     */
    void save(BatchMetadata metadata);

    /**
     * Get batch by domain and batch ID.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @return Optional containing metadata if found
     */
    Optional<BatchMetadata> get(String domain, UUID batchId);

    /**
     * Check if batch exists.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @return true if batch exists
     */
    boolean exists(String domain, UUID batchId);

    /**
     * List batches for a domain.
     *
     * @param domain The domain
     * @param status Filter by status (nullable)
     * @param limit Maximum results
     * @param offset Results to skip
     * @return List of batches ordered by created_at DESC
     */
    List<BatchMetadata> listBatches(String domain, BatchStatus status, int limit, int offset);

    /**
     * Update batch counters when command moves to TSQ and operator retries.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @return false (retry never completes a batch)
     */
    boolean tsqRetry(String domain, UUID batchId);

    /**
     * Update batch counters when operator cancels from TSQ.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @return true if batch is now complete
     */
    boolean tsqCancel(String domain, UUID batchId);

    /**
     * Update batch counters when operator completes from TSQ.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @return true if batch is now complete
     */
    boolean tsqComplete(String domain, UUID batchId);
}
```

### 2.2 Implementation

```java
package com.commandbus.repository.impl;

import com.commandbus.model.BatchMetadata;
import com.commandbus.model.BatchStatus;
import com.commandbus.repository.BatchRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;

@Repository
public class JdbcBatchRepository implements BatchRepository {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final RowMapper<BatchMetadata> BATCH_MAPPER = (rs, rowNum) -> {
        Map<String, Object> customData = null;
        String customDataJson = rs.getString("custom_data");
        if (customDataJson != null) {
            try {
                customData = objectMapper.readValue(customDataJson, MAP_TYPE);
            } catch (JsonProcessingException e) {
                // Ignore parse errors
            }
        }

        return new BatchMetadata(
            rs.getString("domain"),
            UUID.fromString(rs.getString("batch_id")),
            rs.getString("name"),
            customData,
            BatchStatus.fromValue(rs.getString("status")),
            rs.getInt("total_count"),
            rs.getInt("completed_count"),
            rs.getInt("canceled_count"),
            rs.getInt("in_troubleshooting_count"),
            toInstant(rs.getTimestamp("created_at")),
            toInstant(rs.getTimestamp("started_at")),
            toInstant(rs.getTimestamp("completed_at"))
        );
    };

    public JdbcBatchRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    public void save(BatchMetadata metadata) {
        String customDataJson = null;
        if (metadata.customData() != null) {
            try {
                customDataJson = objectMapper.writeValueAsString(metadata.customData());
            } catch (JsonProcessingException e) {
                throw new RuntimeException("Failed to serialize custom_data", e);
            }
        }

        jdbcTemplate.update("""
            INSERT INTO commandbus.batch (
                domain, batch_id, name, custom_data, status,
                total_count, completed_count, canceled_count, in_troubleshooting_count,
                created_at, started_at, completed_at
            ) VALUES (?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            metadata.domain(),
            metadata.batchId(),
            metadata.name(),
            customDataJson,
            metadata.status().getValue(),
            metadata.totalCount(),
            metadata.completedCount(),
            metadata.canceledCount(),
            metadata.inTroubleshootingCount(),
            Timestamp.from(metadata.createdAt()),
            metadata.startedAt() != null ? Timestamp.from(metadata.startedAt()) : null,
            metadata.completedAt() != null ? Timestamp.from(metadata.completedAt()) : null
        );
    }

    @Override
    public Optional<BatchMetadata> get(String domain, UUID batchId) {
        List<BatchMetadata> results = jdbcTemplate.query(
            "SELECT * FROM commandbus.batch WHERE domain = ? AND batch_id = ?",
            BATCH_MAPPER,
            domain, batchId
        );
        return results.isEmpty() ? Optional.empty() : Optional.of(results.get(0));
    }

    @Override
    public boolean exists(String domain, UUID batchId) {
        Integer count = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM commandbus.batch WHERE domain = ? AND batch_id = ?",
            Integer.class,
            domain, batchId
        );
        return count != null && count > 0;
    }

    @Override
    public List<BatchMetadata> listBatches(String domain, BatchStatus status, int limit, int offset) {
        if (status != null) {
            return jdbcTemplate.query(
                "SELECT * FROM commandbus.batch WHERE domain = ? AND status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                BATCH_MAPPER,
                domain, status.getValue(), limit, offset
            );
        } else {
            return jdbcTemplate.query(
                "SELECT * FROM commandbus.batch WHERE domain = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                BATCH_MAPPER,
                domain, limit, offset
            );
        }
    }

    @Override
    public boolean tsqRetry(String domain, UUID batchId) {
        Boolean result = jdbcTemplate.queryForObject(
            "SELECT commandbus.sp_tsq_retry(?, ?)",
            Boolean.class,
            domain, batchId
        );
        return Boolean.TRUE.equals(result);
    }

    @Override
    public boolean tsqCancel(String domain, UUID batchId) {
        Boolean result = jdbcTemplate.queryForObject(
            "SELECT commandbus.sp_tsq_cancel(?, ?)",
            Boolean.class,
            domain, batchId
        );
        return Boolean.TRUE.equals(result);
    }

    @Override
    public boolean tsqComplete(String domain, UUID batchId) {
        Boolean result = jdbcTemplate.queryForObject(
            "SELECT commandbus.sp_tsq_complete(?, ?)",
            Boolean.class,
            domain, batchId
        );
        return Boolean.TRUE.equals(result);
    }

    private static Instant toInstant(Timestamp ts) {
        return ts != null ? ts.toInstant() : null;
    }
}
```

---

## 3. Audit Repository

### 3.1 Interface

```java
package com.commandbus.repository;

import com.commandbus.model.AuditEvent;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Repository for audit events.
 */
public interface AuditRepository {

    /**
     * Log an audit event.
     *
     * @param domain The domain
     * @param commandId The command ID
     * @param eventType The event type
     * @param details Optional details (nullable)
     */
    void log(String domain, UUID commandId, String eventType, Map<String, Object> details);

    /**
     * Log multiple audit events.
     *
     * @param events List of (domain, commandId, eventType, details) tuples
     */
    void logBatch(List<AuditEventRecord> events);

    /**
     * Get audit events for a command.
     *
     * @param commandId The command ID
     * @param domain Filter by domain (nullable)
     * @return List of events in chronological order
     */
    List<AuditEvent> getEvents(UUID commandId, String domain);

    /**
     * Record for batch audit logging.
     */
    record AuditEventRecord(
        String domain,
        UUID commandId,
        String eventType,
        Map<String, Object> details
    ) {}
}
```

### 3.2 Implementation

```java
package com.commandbus.repository.impl;

import com.commandbus.model.AuditEvent;
import com.commandbus.repository.AuditRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Repository
public class JdbcAuditRepository implements AuditRepository {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final RowMapper<AuditEvent> AUDIT_MAPPER = (rs, rowNum) -> {
        Map<String, Object> details = null;
        String detailsJson = rs.getString("details_json");
        if (detailsJson != null) {
            try {
                details = objectMapper.readValue(detailsJson, MAP_TYPE);
            } catch (JsonProcessingException e) {
                // Ignore parse errors
            }
        }

        return new AuditEvent(
            rs.getLong("audit_id"),
            rs.getString("domain"),
            UUID.fromString(rs.getString("command_id")),
            rs.getString("event_type"),
            rs.getTimestamp("ts").toInstant(),
            details
        );
    };

    public JdbcAuditRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    public void log(String domain, UUID commandId, String eventType, Map<String, Object> details) {
        String detailsJson = serializeDetails(details);

        jdbcTemplate.update(
            "INSERT INTO commandbus.audit (domain, command_id, event_type, details_json) VALUES (?, ?, ?, ?::jsonb)",
            domain, commandId, eventType, detailsJson
        );
    }

    @Override
    public void logBatch(List<AuditEventRecord> events) {
        if (events.isEmpty()) return;

        String sql = "INSERT INTO commandbus.audit (domain, command_id, event_type, details_json) VALUES (?, ?, ?, ?::jsonb)";

        List<Object[]> batchArgs = events.stream()
            .map(e -> new Object[]{
                e.domain(),
                e.commandId(),
                e.eventType(),
                serializeDetails(e.details())
            })
            .toList();

        jdbcTemplate.batchUpdate(sql, batchArgs);
    }

    @Override
    public List<AuditEvent> getEvents(UUID commandId, String domain) {
        if (domain != null) {
            return jdbcTemplate.query(
                "SELECT * FROM commandbus.audit WHERE command_id = ? AND domain = ? ORDER BY ts ASC",
                AUDIT_MAPPER,
                commandId, domain
            );
        } else {
            return jdbcTemplate.query(
                "SELECT * FROM commandbus.audit WHERE command_id = ? ORDER BY ts ASC",
                AUDIT_MAPPER,
                commandId
            );
        }
    }

    private String serializeDetails(Map<String, Object> details) {
        if (details == null || details.isEmpty()) return null;
        try {
            return objectMapper.writeValueAsString(details);
        } catch (JsonProcessingException e) {
            throw new RuntimeException("Failed to serialize audit details", e);
        }
    }
}
```

---

## 4. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CR-1 | CommandRepository.save() persists all fields | Integration test |
| CR-2 | CommandRepository.get() returns correct data | Integration test |
| CR-3 | CommandRepository.exists() returns correct result | Integration test |
| CR-4 | CommandRepository.existsBatch() handles large lists | Integration test |
| CR-5 | CommandRepository.query() filters work correctly | Integration test |
| CR-6 | CommandRepository.spReceiveCommand() increments attempts | Integration test |
| CR-7 | CommandRepository.spFinishCommand() updates batch counters | Integration test |
| BR-1 | BatchRepository.save() persists custom_data as JSON | Integration test |
| BR-2 | BatchRepository.tsqCancel() returns correct batch completion | Integration test |
| AR-1 | AuditRepository.log() records events with timestamps | Integration test |
| AR-2 | AuditRepository.getEvents() returns chronological order | Integration test |
| TX-1 | All repositories participate in Spring transactions | Integration test |
