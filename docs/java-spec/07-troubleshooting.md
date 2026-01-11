# Troubleshooting Queue Specification

## Overview

This specification defines the TroubleshootingQueue component for the Java Command Bus library. The TSQ provides operator APIs for managing commands that have failed permanently or exhausted retries.

## Package Structure

```
com.commandbus.ops/
├── TroubleshootingQueue.java      # Interface
└── impl/
    └── DefaultTroubleshootingQueue.java # Implementation
```

---

## 1. Interface Definition

### 1.1 TroubleshootingQueue

```java
package com.commandbus.ops;

import com.commandbus.model.TroubleshootingItem;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Operations for managing commands in the troubleshooting queue.
 *
 * <p>The troubleshooting queue contains commands that:
 * <ul>
 *   <li>Failed with a permanent error</li>
 *   <li>Exhausted all retry attempts</li>
 * </ul>
 *
 * <p>Operators can:
 * <ul>
 *   <li>List failed commands</li>
 *   <li>Retry commands (re-enqueue with reset attempts)</li>
 *   <li>Cancel commands (mark as canceled, send reply)</li>
 *   <li>Complete commands manually (mark as completed, send success reply)</li>
 * </ul>
 *
 * <p>Example:
 * <pre>
 * // List failed commands
 * List<TroubleshootingItem> items = tsq.listTroubleshooting("payments", null, 50, 0);
 *
 * // Retry a command
 * long newMsgId = tsq.operatorRetry("payments", commandId, "admin@example.com");
 *
 * // Cancel with reason
 * tsq.operatorCancel("payments", commandId, "Invalid account", "admin@example.com");
 *
 * // Manually complete
 * tsq.operatorComplete("payments", commandId, Map.of("manual", true), "admin@example.com");
 * </pre>
 */
public interface TroubleshootingQueue {

    /**
     * List commands in the troubleshooting queue for a domain.
     *
     * @param domain The domain to list troubleshooting items for
     * @param commandType Optional filter by command type (nullable)
     * @param limit Maximum number of items to return
     * @param offset Number of items to skip for pagination
     * @return List of TroubleshootingItem objects ordered by updated_at DESC
     */
    List<TroubleshootingItem> listTroubleshooting(
        String domain,
        String commandType,
        int limit,
        int offset
    );

    /**
     * Count commands in the troubleshooting queue for a domain.
     *
     * @param domain The domain
     * @param commandType Optional filter by command type (nullable)
     * @return Number of commands in troubleshooting queue
     */
    int countTroubleshooting(String domain, String commandType);

    /**
     * List domains that have commands in the troubleshooting queue.
     *
     * @return List of domain names
     */
    List<String> listDomains();

    /**
     * List all TSQ entries across domains with pagination.
     *
     * @param limit Maximum items to return
     * @param offset Items to skip
     * @param domain Optional domain filter (nullable)
     * @return TroubleshootingListResult with items, total count, and command IDs
     */
    TroubleshootingListResult listAllTroubleshooting(int limit, int offset, String domain);

    /**
     * Get the domain for a command ID.
     *
     * @param commandId The command ID
     * @return Domain name
     * @throws com.commandbus.exception.CommandNotFoundException if not found
     */
    String getCommandDomain(UUID commandId);

    /**
     * Retry a command from the troubleshooting queue.
     *
     * <p>Retrieves the original payload from archive, re-enqueues to PGMQ,
     * resets attempts to 0, sets status to PENDING.
     *
     * @param domain The domain of the command
     * @param commandId The command ID to retry
     * @param operator Optional operator identity for audit trail (nullable)
     * @return New PGMQ message ID
     * @throws com.commandbus.exception.CommandNotFoundException if command not found
     * @throws com.commandbus.exception.InvalidOperationException if not in TSQ
     */
    long operatorRetry(String domain, UUID commandId, String operator);

    /**
     * Cancel a command in the troubleshooting queue.
     *
     * <p>Sets status to CANCELED, sends CANCELED reply if reply_to configured.
     *
     * @param domain The domain of the command
     * @param commandId The command ID to cancel
     * @param reason Reason for cancellation (required)
     * @param operator Optional operator identity for audit trail (nullable)
     * @throws com.commandbus.exception.CommandNotFoundException if command not found
     * @throws com.commandbus.exception.InvalidOperationException if not in TSQ
     */
    void operatorCancel(String domain, UUID commandId, String reason, String operator);

    /**
     * Manually complete a command in the troubleshooting queue.
     *
     * <p>Sets status to COMPLETED, sends SUCCESS reply if reply_to configured.
     *
     * @param domain The domain of the command
     * @param commandId The command ID to complete
     * @param resultData Optional result data to include in reply (nullable)
     * @param operator Optional operator identity for audit trail (nullable)
     * @throws com.commandbus.exception.CommandNotFoundException if command not found
     * @throws com.commandbus.exception.InvalidOperationException if not in TSQ
     */
    void operatorComplete(String domain, UUID commandId, Map<String, Object> resultData, String operator);

    /**
     * Result of listing troubleshooting items across domains.
     *
     * @param items List of troubleshooting items
     * @param totalCount Total count across all domains
     * @param commandIds All command IDs in TSQ
     */
    record TroubleshootingListResult(
        List<TroubleshootingItem> items,
        int totalCount,
        List<UUID> commandIds
    ) {}
}
```

---

## 2. Implementation

### 2.1 DefaultTroubleshootingQueue

```java
package com.commandbus.ops.impl;

import com.commandbus.exception.CommandNotFoundException;
import com.commandbus.exception.InvalidOperationException;
import com.commandbus.model.*;
import com.commandbus.ops.TroubleshootingQueue;
import com.commandbus.pgmq.PgmqClient;
import com.commandbus.repository.AuditRepository;
import com.commandbus.repository.BatchRepository;
import com.commandbus.repository.CommandRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;

@Service
public class DefaultTroubleshootingQueue implements TroubleshootingQueue {

    private static final Logger log = LoggerFactory.getLogger(DefaultTroubleshootingQueue.class);
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final JdbcTemplate jdbcTemplate;
    private final PgmqClient pgmqClient;
    private final CommandRepository commandRepository;
    private final BatchRepository batchRepository;
    private final AuditRepository auditRepository;
    private final ObjectMapper objectMapper;

    public DefaultTroubleshootingQueue(
            JdbcTemplate jdbcTemplate,
            PgmqClient pgmqClient,
            CommandRepository commandRepository,
            BatchRepository batchRepository,
            AuditRepository auditRepository,
            ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.pgmqClient = pgmqClient;
        this.commandRepository = commandRepository;
        this.batchRepository = batchRepository;
        this.auditRepository = auditRepository;
        this.objectMapper = objectMapper;
    }

    @Override
    public List<TroubleshootingItem> listTroubleshooting(
            String domain,
            String commandType,
            int limit,
            int offset) {

        String queueName = domain + "__commands";
        String archiveTable = "pgmq.a_" + queueName;

        StringBuilder sql = new StringBuilder("""
            SELECT * FROM (
                SELECT DISTINCT ON (c.command_id)
                    c.domain,
                    c.command_id,
                    c.command_type,
                    c.attempts,
                    c.max_attempts,
                    c.last_error_type,
                    c.last_error_code,
                    c.last_error_msg,
                    c.correlation_id,
                    c.reply_queue,
                    a.message,
                    c.created_at,
                    c.updated_at
                FROM commandbus.command c
                LEFT JOIN %s a ON a.message->>'command_id' = c.command_id::text
                WHERE c.domain = ?
                  AND c.status = ?
            """.formatted(archiveTable));

        List<Object> params = new ArrayList<>();
        params.add(domain);
        params.add(CommandStatus.IN_TROUBLESHOOTING_QUEUE.getValue());

        if (commandType != null) {
            sql.append(" AND c.command_type = ?");
            params.add(commandType);
        }

        sql.append("""
                ORDER BY c.command_id, a.archived_at DESC NULLS LAST
            ) sub
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """);
        params.add(limit);
        params.add(offset);

        return jdbcTemplate.query(sql.toString(), (rs, rowNum) -> {
            Map<String, Object> payload = null;
            String messageJson = rs.getString("message");
            if (messageJson != null) {
                try {
                    payload = objectMapper.readValue(messageJson, MAP_TYPE);
                } catch (Exception e) {
                    // Ignore parse errors
                }
            }

            return new TroubleshootingItem(
                rs.getString("domain"),
                UUID.fromString(rs.getString("command_id")),
                rs.getString("command_type"),
                rs.getInt("attempts"),
                rs.getInt("max_attempts"),
                rs.getString("last_error_type"),
                rs.getString("last_error_code"),
                rs.getString("last_error_msg"),
                rs.getString("correlation_id") != null ?
                    UUID.fromString(rs.getString("correlation_id")) : null,
                rs.getString("reply_queue"),
                payload,
                rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("updated_at").toInstant()
            );
        }, params.toArray());
    }

    @Override
    public int countTroubleshooting(String domain, String commandType) {
        StringBuilder sql = new StringBuilder("""
            SELECT COUNT(*)
            FROM commandbus.command
            WHERE domain = ? AND status = ?
            """);
        List<Object> params = new ArrayList<>();
        params.add(domain);
        params.add(CommandStatus.IN_TROUBLESHOOTING_QUEUE.getValue());

        if (commandType != null) {
            sql.append(" AND command_type = ?");
            params.add(commandType);
        }

        Integer count = jdbcTemplate.queryForObject(sql.toString(), Integer.class, params.toArray());
        return count != null ? count : 0;
    }

    @Override
    public List<String> listDomains() {
        return jdbcTemplate.queryForList("""
            SELECT DISTINCT domain
            FROM commandbus.command
            WHERE status = ?
            ORDER BY domain
            """,
            String.class,
            CommandStatus.IN_TROUBLESHOOTING_QUEUE.getValue()
        );
    }

    @Override
    public TroubleshootingListResult listAllTroubleshooting(int limit, int offset, String domain) {
        List<String> domains = domain != null ? List.of(domain) : listDomains();
        if (domains.isEmpty()) {
            return new TroubleshootingListResult(List.of(), 0, List.of());
        }

        List<TroubleshootingItem> aggregated = new ArrayList<>();
        int remaining = limit;
        int skip = offset;

        for (String dom : domains) {
            int domTotal = countTroubleshooting(dom, null);
            if (domTotal == 0) continue;

            if (skip >= domTotal) {
                skip -= domTotal;
                continue;
            }

            if (remaining <= 0) continue;

            int chunk = Math.min(remaining, domTotal - skip);
            List<TroubleshootingItem> entries = listTroubleshooting(dom, null, chunk, skip);
            aggregated.addAll(entries);
            remaining -= entries.size();
            skip = 0;
        }

        List<UUID> commandIds = listCommandIds(domain);
        int totalCount = commandIds.size();

        // Sort by updated_at DESC
        aggregated.sort((a, b) -> b.updatedAt().compareTo(a.updatedAt()));

        return new TroubleshootingListResult(aggregated, totalCount, commandIds);
    }

    private List<UUID> listCommandIds(String domain) {
        StringBuilder sql = new StringBuilder("""
            SELECT command_id
            FROM commandbus.command
            WHERE status = ?
            """);
        List<Object> params = new ArrayList<>();
        params.add(CommandStatus.IN_TROUBLESHOOTING_QUEUE.getValue());

        if (domain != null) {
            sql.append(" AND domain = ?");
            params.add(domain);
        }

        sql.append(" ORDER BY created_at DESC");

        return jdbcTemplate.query(sql.toString(),
            (rs, rowNum) -> UUID.fromString(rs.getString("command_id")),
            params.toArray()
        );
    }

    @Override
    public String getCommandDomain(UUID commandId) {
        String domain = jdbcTemplate.queryForObject(
            "SELECT domain FROM commandbus.command WHERE command_id = ?",
            String.class,
            commandId
        );

        if (domain == null) {
            throw new CommandNotFoundException("unknown", commandId.toString());
        }

        return domain;
    }

    @Override
    @Transactional
    public long operatorRetry(String domain, UUID commandId, String operator) {
        String queueName = domain + "__commands";

        // Get command metadata
        CommandMetadata metadata = commandRepository.get(domain, commandId)
            .orElseThrow(() -> new CommandNotFoundException(domain, commandId.toString()));

        // Verify in TSQ
        if (metadata.status() != CommandStatus.IN_TROUBLESHOOTING_QUEUE) {
            throw new InvalidOperationException(
                "Command " + commandId + " is not in troubleshooting queue (status: " + metadata.status() + ")"
            );
        }

        // Get payload from archive
        PgmqMessage archived = pgmqClient.getFromArchive(queueName, commandId.toString())
            .orElseThrow(() -> new InvalidOperationException(
                "Payload not found in archive for command " + commandId
            ));

        Map<String, Object> payload = archived.message();

        // Re-enqueue to PGMQ
        long newMsgId = pgmqClient.send(queueName, payload);

        // Reset command: status=PENDING, attempts=0, clear errors
        jdbcTemplate.update("""
            UPDATE commandbus.command
            SET status = ?, attempts = 0, msg_id = ?,
                last_error_type = NULL, last_error_code = NULL,
                last_error_msg = NULL, updated_at = NOW()
            WHERE domain = ? AND command_id = ?
            """,
            CommandStatus.PENDING.getValue(), newMsgId, domain, commandId
        );

        // Record audit event
        auditRepository.log(domain, commandId, AuditEventType.OPERATOR_RETRY, Map.of(
            "operator", operator != null ? operator : "unknown",
            "new_msg_id", newMsgId
        ));

        // Update batch counters
        if (metadata.batchId() != null) {
            batchRepository.tsqRetry(domain, metadata.batchId());
        }

        log.info("Operator retry for {}.{}: newMsgId={}, operator={}",
            domain, commandId, newMsgId, operator);

        return newMsgId;
    }

    @Override
    @Transactional
    public void operatorCancel(String domain, UUID commandId, String reason, String operator) {
        // Get command metadata
        CommandMetadata metadata = commandRepository.get(domain, commandId)
            .orElseThrow(() -> new CommandNotFoundException(domain, commandId.toString()));

        // Verify in TSQ
        if (metadata.status() != CommandStatus.IN_TROUBLESHOOTING_QUEUE) {
            throw new InvalidOperationException(
                "Command " + commandId + " is not in troubleshooting queue (status: " + metadata.status() + ")"
            );
        }

        // Update status to CANCELED
        jdbcTemplate.update("""
            UPDATE commandbus.command
            SET status = ?, updated_at = NOW()
            WHERE domain = ? AND command_id = ?
            """,
            CommandStatus.CANCELED.getValue(), domain, commandId
        );

        // Send reply if configured
        if (metadata.replyTo() != null && !metadata.replyTo().isBlank()) {
            Map<String, Object> reply = new HashMap<>();
            reply.put("command_id", commandId.toString());
            if (metadata.correlationId() != null) {
                reply.put("correlation_id", metadata.correlationId().toString());
            }
            reply.put("outcome", ReplyOutcome.CANCELED.getValue());
            reply.put("reason", reason);

            pgmqClient.send(metadata.replyTo(), reply);
        }

        // Record audit event
        auditRepository.log(domain, commandId, AuditEventType.OPERATOR_CANCEL, Map.of(
            "operator", operator != null ? operator : "unknown",
            "reason", reason,
            "reply_to", metadata.replyTo() != null ? metadata.replyTo() : ""
        ));

        // Update batch counters
        boolean isBatchComplete = false;
        if (metadata.batchId() != null) {
            isBatchComplete = batchRepository.tsqCancel(domain, metadata.batchId());
        }

        log.info("Operator cancel for {}.{}: reason={}, operator={}",
            domain, commandId, reason, operator);

        // Invoke batch callback if complete
        if (isBatchComplete && metadata.batchId() != null) {
            invokeBatchCallback(domain, metadata.batchId());
        }
    }

    @Override
    @Transactional
    public void operatorComplete(String domain, UUID commandId, Map<String, Object> resultData, String operator) {
        // Get command metadata
        CommandMetadata metadata = commandRepository.get(domain, commandId)
            .orElseThrow(() -> new CommandNotFoundException(domain, commandId.toString()));

        // Verify in TSQ
        if (metadata.status() != CommandStatus.IN_TROUBLESHOOTING_QUEUE) {
            throw new InvalidOperationException(
                "Command " + commandId + " is not in troubleshooting queue (status: " + metadata.status() + ")"
            );
        }

        // Update status to COMPLETED
        jdbcTemplate.update("""
            UPDATE commandbus.command
            SET status = ?, updated_at = NOW()
            WHERE domain = ? AND command_id = ?
            """,
            CommandStatus.COMPLETED.getValue(), domain, commandId
        );

        // Send reply if configured
        if (metadata.replyTo() != null && !metadata.replyTo().isBlank()) {
            Map<String, Object> reply = new HashMap<>();
            reply.put("command_id", commandId.toString());
            if (metadata.correlationId() != null) {
                reply.put("correlation_id", metadata.correlationId().toString());
            }
            reply.put("outcome", ReplyOutcome.SUCCESS.getValue());
            if (resultData != null) {
                reply.put("result", resultData);
            }

            pgmqClient.send(metadata.replyTo(), reply);
        }

        // Record audit event
        auditRepository.log(domain, commandId, AuditEventType.OPERATOR_COMPLETE, Map.of(
            "operator", operator != null ? operator : "unknown",
            "has_result_data", resultData != null,
            "reply_to", metadata.replyTo() != null ? metadata.replyTo() : ""
        ));

        // Update batch counters
        boolean isBatchComplete = false;
        if (metadata.batchId() != null) {
            isBatchComplete = batchRepository.tsqComplete(domain, metadata.batchId());
        }

        log.info("Operator complete for {}.{}: operator={}", domain, commandId, operator);

        // Invoke batch callback if complete
        if (isBatchComplete && metadata.batchId() != null) {
            invokeBatchCallback(domain, metadata.batchId());
        }
    }

    private void invokeBatchCallback(String domain, UUID batchId) {
        // Batch completion callback is handled by CommandBus
        log.debug("Batch {} in domain {} completed via TSQ operation", batchId, domain);
    }
}
```

---

## 3. Usage Examples

### 3.1 List Failed Commands

```java
@RestController
@RequestMapping("/api/troubleshooting")
public class TroubleshootingController {

    private final TroubleshootingQueue tsq;

    @GetMapping("/{domain}")
    public List<TroubleshootingItem> listTroubleshooting(
            @PathVariable String domain,
            @RequestParam(required = false) String commandType,
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset) {
        return tsq.listTroubleshooting(domain, commandType, limit, offset);
    }

    @GetMapping("/{domain}/count")
    public int countTroubleshooting(
            @PathVariable String domain,
            @RequestParam(required = false) String commandType) {
        return tsq.countTroubleshooting(domain, commandType);
    }
}
```

### 3.2 Operator Actions

```java
@PostMapping("/{domain}/{commandId}/retry")
public long retryCommand(
        @PathVariable String domain,
        @PathVariable UUID commandId,
        @RequestHeader("X-Operator") String operator) {
    return tsq.operatorRetry(domain, commandId, operator);
}

@PostMapping("/{domain}/{commandId}/cancel")
public void cancelCommand(
        @PathVariable String domain,
        @PathVariable UUID commandId,
        @RequestBody CancelRequest request,
        @RequestHeader("X-Operator") String operator) {
    tsq.operatorCancel(domain, commandId, request.reason(), operator);
}

@PostMapping("/{domain}/{commandId}/complete")
public void completeCommand(
        @PathVariable String domain,
        @PathVariable UUID commandId,
        @RequestBody(required = false) Map<String, Object> resultData,
        @RequestHeader("X-Operator") String operator) {
    tsq.operatorComplete(domain, commandId, resultData, operator);
}
```

---

## 4. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| TQ-1 | listTroubleshooting returns items with payload | Integration test |
| TQ-2 | countTroubleshooting returns correct count | Integration test |
| TQ-3 | operatorRetry re-enqueues with attempts=0 | Integration test |
| TQ-4 | operatorRetry throws if not in TSQ | Unit test |
| TQ-5 | operatorCancel sends CANCELED reply | Integration test |
| TQ-6 | operatorComplete sends SUCCESS reply | Integration test |
| TQ-7 | TSQ operations update batch counters | Integration test |
| TQ-8 | Batch callback invoked after TSQ resolution | Integration test |
| TQ-9 | Audit events recorded for all operations | Integration test |
