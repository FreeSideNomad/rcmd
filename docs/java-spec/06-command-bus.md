# Command Bus API Specification

## Overview

This specification defines the CommandBus interface and implementation for the Java Command Bus library. The CommandBus is the main entry point for sending commands and managing batches.

## Package Structure

```
com.commandbus.api/
├── CommandBus.java           # Interface
└── impl/
    └── DefaultCommandBus.java # Implementation
```

---

## 1. Interface Definition

### 1.1 CommandBus

```java
package com.commandbus.api;

import com.commandbus.model.*;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Consumer;

/**
 * Command Bus for sending and managing commands.
 *
 * <p>The CommandBus provides the main API for:
 * <ul>
 *   <li>Sending commands to domain queues</li>
 *   <li>Managing command lifecycle</li>
 *   <li>Creating and tracking batches</li>
 *   <li>Querying command history</li>
 * </ul>
 *
 * <p>Example:
 * <pre>
 * {@literal @}Service
 * public class PaymentService {
 *
 *     private final CommandBus commandBus;
 *
 *     public void processPayment(String accountId, int amount) {
 *         var result = commandBus.send(
 *             "payments",
 *             "DebitAccount",
 *             UUID.randomUUID(),
 *             Map.of("account_id", accountId, "amount", amount)
 *         );
 *         log.info("Sent command: {}", result.commandId());
 *     }
 * }
 * </pre>
 */
public interface CommandBus {

    // --- Single Command Operations ---

    /**
     * Send a command to a domain queue.
     *
     * @param domain The domain to send to (e.g., "payments")
     * @param commandType The type of command (e.g., "DebitAccount")
     * @param commandId Unique identifier for this command
     * @param data The command payload
     * @return SendResult with command_id and msg_id
     * @throws com.commandbus.exception.DuplicateCommandException if command_id exists
     */
    SendResult send(String domain, String commandType, UUID commandId, Map<String, Object> data);

    /**
     * Send a command with additional options.
     *
     * @param domain The domain to send to
     * @param commandType The type of command
     * @param commandId Unique identifier for this command
     * @param data The command payload
     * @param correlationId Optional correlation ID for tracing (nullable)
     * @param replyTo Optional reply queue name (nullable)
     * @param maxAttempts Max retry attempts (nullable, uses default if null)
     * @return SendResult with command_id and msg_id
     * @throws com.commandbus.exception.DuplicateCommandException if command_id exists
     */
    SendResult send(
        String domain,
        String commandType,
        UUID commandId,
        Map<String, Object> data,
        UUID correlationId,
        String replyTo,
        Integer maxAttempts
    );

    /**
     * Send a command associated with a batch.
     *
     * @param domain The domain to send to
     * @param commandType The type of command
     * @param commandId Unique identifier for this command
     * @param data The command payload
     * @param batchId The batch to associate with
     * @return SendResult with command_id and msg_id
     * @throws com.commandbus.exception.DuplicateCommandException if command_id exists
     * @throws com.commandbus.exception.BatchNotFoundException if batch doesn't exist
     */
    SendResult sendToBatch(
        String domain,
        String commandType,
        UUID commandId,
        Map<String, Object> data,
        UUID batchId
    );

    // --- Batch Send Operations ---

    /**
     * Send multiple commands efficiently in batched transactions.
     *
     * <p>Each chunk is processed in a single transaction with one NOTIFY at the end.
     * This is significantly faster than calling send() repeatedly.
     *
     * @param requests List of SendRequest objects
     * @return BatchSendResult with all results and stats
     * @throws com.commandbus.exception.DuplicateCommandException if any command_id exists
     */
    BatchSendResult sendBatch(List<SendRequest> requests);

    /**
     * Send multiple commands with custom chunk size.
     *
     * @param requests List of SendRequest objects
     * @param chunkSize Max commands per transaction
     * @return BatchSendResult with all results and stats
     */
    BatchSendResult sendBatch(List<SendRequest> requests, int chunkSize);

    // --- Batch Management ---

    /**
     * Create a batch containing multiple commands atomically.
     *
     * <p>All commands are created in a single transaction - either all succeed or none.
     * The batch is closed immediately after creation (no commands can be added later).
     *
     * @param domain The domain for this batch
     * @param commands List of BatchCommand objects
     * @return CreateBatchResult with batch_id and command results
     * @throws IllegalArgumentException if commands list is empty
     * @throws com.commandbus.exception.DuplicateCommandException if any command_id exists
     */
    CreateBatchResult createBatch(String domain, List<BatchCommand> commands);

    /**
     * Create a batch with additional options.
     *
     * @param domain The domain for this batch
     * @param commands List of BatchCommand objects
     * @param batchId Optional batch ID (auto-generated if null)
     * @param name Optional human-readable name
     * @param customData Optional custom metadata
     * @param onComplete Optional callback when batch completes
     * @return CreateBatchResult with batch_id and command results
     */
    CreateBatchResult createBatch(
        String domain,
        List<BatchCommand> commands,
        UUID batchId,
        String name,
        Map<String, Object> customData,
        Consumer<BatchMetadata> onComplete
    );

    /**
     * Get batch metadata.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @return BatchMetadata or null if not found
     */
    BatchMetadata getBatch(String domain, UUID batchId);

    /**
     * List batches for a domain.
     *
     * @param domain The domain
     * @param status Filter by status (nullable)
     * @param limit Maximum results
     * @param offset Results to skip
     * @return List of BatchMetadata ordered by created_at DESC
     */
    List<BatchMetadata> listBatches(String domain, BatchStatus status, int limit, int offset);

    /**
     * List commands in a batch.
     *
     * @param domain The domain
     * @param batchId The batch ID
     * @param status Filter by status (nullable)
     * @param limit Maximum results
     * @param offset Results to skip
     * @return List of CommandMetadata in the batch
     */
    List<CommandMetadata> listBatchCommands(
        String domain,
        UUID batchId,
        CommandStatus status,
        int limit,
        int offset
    );

    // --- Query Operations ---

    /**
     * Get command metadata.
     *
     * @param domain The domain
     * @param commandId The command ID
     * @return CommandMetadata or null if not found
     */
    CommandMetadata getCommand(String domain, UUID commandId);

    /**
     * Check if a command exists.
     *
     * @param domain The domain
     * @param commandId The command ID
     * @return true if command exists
     */
    boolean commandExists(String domain, UUID commandId);

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
     * @return List of CommandMetadata matching filters
     */
    List<CommandMetadata> queryCommands(
        CommandStatus status,
        String domain,
        String commandType,
        Instant createdAfter,
        Instant createdBefore,
        int limit,
        int offset
    );

    /**
     * Get audit trail for a command.
     *
     * @param commandId The command ID
     * @param domain Optional domain filter (nullable)
     * @return List of AuditEvent in chronological order
     */
    List<AuditEvent> getAuditTrail(UUID commandId, String domain);
}
```

---

## 2. Implementation

### 2.1 DefaultCommandBus

```java
package com.commandbus.api.impl;

import com.commandbus.api.CommandBus;
import com.commandbus.exception.BatchNotFoundException;
import com.commandbus.exception.DuplicateCommandException;
import com.commandbus.model.*;
import com.commandbus.pgmq.PgmqClient;
import com.commandbus.repository.AuditRepository;
import com.commandbus.repository.BatchRepository;
import com.commandbus.repository.CommandRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.*;
import java.util.function.Consumer;

/**
 * Default implementation of CommandBus.
 */
@Service
public class DefaultCommandBus implements CommandBus {

    private static final Logger log = LoggerFactory.getLogger(DefaultCommandBus.class);
    private static final int DEFAULT_CHUNK_SIZE = 1000;
    private static final int DEFAULT_MAX_ATTEMPTS = 3;

    private final PgmqClient pgmqClient;
    private final CommandRepository commandRepository;
    private final BatchRepository batchRepository;
    private final AuditRepository auditRepository;
    private final ObjectMapper objectMapper;

    // In-memory batch callbacks (lost on restart)
    private final Map<UUID, Consumer<BatchMetadata>> batchCallbacks = new ConcurrentHashMap<>();

    public DefaultCommandBus(
            PgmqClient pgmqClient,
            CommandRepository commandRepository,
            BatchRepository batchRepository,
            AuditRepository auditRepository,
            ObjectMapper objectMapper) {
        this.pgmqClient = pgmqClient;
        this.commandRepository = commandRepository;
        this.batchRepository = batchRepository;
        this.auditRepository = auditRepository;
        this.objectMapper = objectMapper;
    }

    // --- Single Command Operations ---

    @Override
    public SendResult send(String domain, String commandType, UUID commandId, Map<String, Object> data) {
        return send(domain, commandType, commandId, data, null, null, null);
    }

    @Override
    @Transactional
    public SendResult send(
            String domain,
            String commandType,
            UUID commandId,
            Map<String, Object> data,
            UUID correlationId,
            String replyTo,
            Integer maxAttempts) {

        return sendInternal(domain, commandType, commandId, data,
            correlationId, replyTo, maxAttempts, null);
    }

    @Override
    @Transactional
    public SendResult sendToBatch(
            String domain,
            String commandType,
            UUID commandId,
            Map<String, Object> data,
            UUID batchId) {

        // Validate batch exists
        if (!batchRepository.exists(domain, batchId)) {
            throw new BatchNotFoundException(domain, batchId.toString());
        }

        return sendInternal(domain, commandType, commandId, data,
            null, null, null, batchId);
    }

    private SendResult sendInternal(
            String domain,
            String commandType,
            UUID commandId,
            Map<String, Object> data,
            UUID correlationId,
            String replyTo,
            Integer maxAttempts,
            UUID batchId) {

        String queueName = domain + "__commands";
        int effectiveMaxAttempts = maxAttempts != null ? maxAttempts : DEFAULT_MAX_ATTEMPTS;
        UUID effectiveCorrelationId = correlationId != null ? correlationId : UUID.randomUUID();

        // Check for duplicate
        if (commandRepository.exists(domain, commandId)) {
            throw new DuplicateCommandException(domain, commandId.toString());
        }

        // Build message payload
        Map<String, Object> message = buildMessage(
            domain, commandType, commandId, data, effectiveCorrelationId, replyTo
        );

        // Send to PGMQ
        long msgId = pgmqClient.send(queueName, message);

        // Create metadata
        Instant now = Instant.now();
        CommandMetadata metadata = new CommandMetadata(
            domain, commandId, commandType,
            CommandStatus.PENDING,
            0, effectiveMaxAttempts,
            msgId, effectiveCorrelationId, replyTo,
            null, null, null,
            now, now, batchId
        );

        // Save metadata
        commandRepository.save(metadata, queueName);

        // Log audit event
        auditRepository.log(domain, commandId, AuditEventType.SENT, Map.of(
            "command_type", commandType,
            "correlation_id", effectiveCorrelationId.toString(),
            "msg_id", msgId
        ));

        log.info("Sent command {}.{} (commandId={}, msgId={})",
            domain, commandType, commandId, msgId);

        return new SendResult(commandId, msgId);
    }

    // --- Batch Send Operations ---

    @Override
    public BatchSendResult sendBatch(List<SendRequest> requests) {
        return sendBatch(requests, DEFAULT_CHUNK_SIZE);
    }

    @Override
    public BatchSendResult sendBatch(List<SendRequest> requests, int chunkSize) {
        if (requests.isEmpty()) {
            return new BatchSendResult(List.of(), 0, 0);
        }

        List<SendResult> allResults = new ArrayList<>();
        int chunksProcessed = 0;

        // Process in chunks
        for (int i = 0; i < requests.size(); i += chunkSize) {
            List<SendRequest> chunk = requests.subList(i, Math.min(i + chunkSize, requests.size()));
            List<SendResult> chunkResults = sendBatchChunk(chunk);
            allResults.addAll(chunkResults);
            chunksProcessed++;
        }

        log.info("Sent {} commands in {} chunks", allResults.size(), chunksProcessed);

        return new BatchSendResult(allResults, chunksProcessed, allResults.size());
    }

    @Transactional
    protected List<SendResult> sendBatchChunk(List<SendRequest> requests) {
        List<SendResult> results = new ArrayList<>();

        // Group by domain
        Map<String, List<SendRequest>> byDomain = new HashMap<>();
        for (SendRequest req : requests) {
            byDomain.computeIfAbsent(req.domain(), k -> new ArrayList<>()).add(req);
        }

        Instant now = Instant.now();

        for (var entry : byDomain.entrySet()) {
            String domain = entry.getKey();
            List<SendRequest> domainRequests = entry.getValue();
            String queueName = domain + "__commands";

            // Check for duplicates
            List<UUID> commandIds = domainRequests.stream()
                .map(SendRequest::commandId)
                .toList();
            Set<UUID> existing = commandRepository.existsBatch(domain, commandIds);
            if (!existing.isEmpty()) {
                UUID firstDup = existing.iterator().next();
                throw new DuplicateCommandException(domain, firstDup.toString());
            }

            // Build all messages
            List<Map<String, Object>> messages = new ArrayList<>();
            for (SendRequest req : domainRequests) {
                UUID correlationId = req.correlationId() != null ? req.correlationId() : UUID.randomUUID();
                messages.add(buildMessage(domain, req.commandType(), req.commandId(),
                    req.data(), correlationId, req.replyTo()));
            }

            // Batch send to PGMQ (no NOTIFY yet)
            List<Long> msgIds = pgmqClient.sendBatch(queueName, messages);

            // Build metadata and audit events
            List<CommandMetadata> metadataList = new ArrayList<>();
            List<AuditRepository.AuditEventRecord> auditEvents = new ArrayList<>();

            for (int i = 0; i < domainRequests.size(); i++) {
                SendRequest req = domainRequests.get(i);
                long msgId = msgIds.get(i);
                int maxAttempts = req.maxAttempts() != null ? req.maxAttempts() : DEFAULT_MAX_ATTEMPTS;
                UUID correlationId = req.correlationId() != null ? req.correlationId() : UUID.randomUUID();

                metadataList.add(new CommandMetadata(
                    domain, req.commandId(), req.commandType(),
                    CommandStatus.PENDING,
                    0, maxAttempts,
                    msgId, correlationId, req.replyTo(),
                    null, null, null,
                    now, now, null
                ));

                auditEvents.add(new AuditRepository.AuditEventRecord(
                    domain, req.commandId(), AuditEventType.SENT,
                    Map.of("command_type", req.commandType(), "msg_id", msgId)
                ));

                results.add(new SendResult(req.commandId(), msgId));
            }

            // Batch save
            commandRepository.saveBatch(metadataList, queueName);
            auditRepository.logBatch(auditEvents);

            // Send NOTIFY (once per domain per chunk)
            pgmqClient.notify(queueName);
        }

        return results;
    }

    // --- Batch Management ---

    @Override
    public CreateBatchResult createBatch(String domain, List<BatchCommand> commands) {
        return createBatch(domain, commands, null, null, null, null);
    }

    @Override
    @Transactional
    public CreateBatchResult createBatch(
            String domain,
            List<BatchCommand> commands,
            UUID batchId,
            String name,
            Map<String, Object> customData,
            Consumer<BatchMetadata> onComplete) {

        if (commands.isEmpty()) {
            throw new IllegalArgumentException("Batch must contain at least one command");
        }

        // Check for duplicate command IDs within batch
        Set<UUID> seen = new HashSet<>();
        for (BatchCommand cmd : commands) {
            if (!seen.add(cmd.commandId())) {
                throw new DuplicateCommandException(domain, cmd.commandId().toString());
            }
        }

        UUID effectiveBatchId = batchId != null ? batchId : UUID.randomUUID();
        String queueName = domain + "__commands";
        Instant now = Instant.now();

        // Check for duplicates in database
        List<UUID> commandIds = commands.stream().map(BatchCommand::commandId).toList();
        Set<UUID> existing = commandRepository.existsBatch(domain, commandIds);
        if (!existing.isEmpty()) {
            throw new DuplicateCommandException(domain, existing.iterator().next().toString());
        }

        // Create batch metadata
        BatchMetadata batchMetadata = new BatchMetadata(
            domain, effectiveBatchId, name, customData,
            BatchStatus.PENDING,
            commands.size(), 0, 0, 0,
            now, null, null
        );
        batchRepository.save(batchMetadata);

        // Build messages
        List<Map<String, Object>> messages = new ArrayList<>();
        for (BatchCommand cmd : commands) {
            UUID correlationId = cmd.correlationId() != null ? cmd.correlationId() : UUID.randomUUID();
            messages.add(buildMessage(domain, cmd.commandType(), cmd.commandId(),
                cmd.data(), correlationId, cmd.replyTo()));
        }

        // Batch send to PGMQ
        List<Long> msgIds = pgmqClient.sendBatch(queueName, messages);

        // Build command metadata and audit events
        List<CommandMetadata> metadataList = new ArrayList<>();
        List<AuditRepository.AuditEventRecord> auditEvents = new ArrayList<>();
        List<SendResult> commandResults = new ArrayList<>();

        for (int i = 0; i < commands.size(); i++) {
            BatchCommand cmd = commands.get(i);
            long msgId = msgIds.get(i);
            int maxAttempts = cmd.maxAttempts() != null ? cmd.maxAttempts() : DEFAULT_MAX_ATTEMPTS;
            UUID correlationId = cmd.correlationId() != null ? cmd.correlationId() : UUID.randomUUID();

            metadataList.add(new CommandMetadata(
                domain, cmd.commandId(), cmd.commandType(),
                CommandStatus.PENDING,
                0, maxAttempts,
                msgId, correlationId, cmd.replyTo(),
                null, null, null,
                now, now, effectiveBatchId
            ));

            auditEvents.add(new AuditRepository.AuditEventRecord(
                domain, cmd.commandId(), AuditEventType.SENT,
                Map.of("command_type", cmd.commandType(), "msg_id", msgId, "batch_id", effectiveBatchId.toString())
            ));

            commandResults.add(new SendResult(cmd.commandId(), msgId));
        }

        // Batch save
        commandRepository.saveBatch(metadataList, queueName);
        auditRepository.logBatch(auditEvents);

        // Send NOTIFY
        pgmqClient.notify(queueName);

        // Register callback (if provided)
        if (onComplete != null) {
            batchCallbacks.put(effectiveBatchId, onComplete);
        }

        log.info("Created batch {} in domain {} with {} commands",
            effectiveBatchId, domain, commands.size());

        return new CreateBatchResult(effectiveBatchId, commandResults, commands.size());
    }

    @Override
    public BatchMetadata getBatch(String domain, UUID batchId) {
        return batchRepository.get(domain, batchId).orElse(null);
    }

    @Override
    public List<BatchMetadata> listBatches(String domain, BatchStatus status, int limit, int offset) {
        return batchRepository.listBatches(domain, status, limit, offset);
    }

    @Override
    public List<CommandMetadata> listBatchCommands(
            String domain, UUID batchId, CommandStatus status, int limit, int offset) {
        return commandRepository.listByBatch(domain, batchId, status, limit, offset);
    }

    // --- Query Operations ---

    @Override
    public CommandMetadata getCommand(String domain, UUID commandId) {
        return commandRepository.get(domain, commandId).orElse(null);
    }

    @Override
    public boolean commandExists(String domain, UUID commandId) {
        return commandRepository.exists(domain, commandId);
    }

    @Override
    public List<CommandMetadata> queryCommands(
            CommandStatus status,
            String domain,
            String commandType,
            Instant createdAfter,
            Instant createdBefore,
            int limit,
            int offset) {
        return commandRepository.query(status, domain, commandType,
            createdAfter, createdBefore, limit, offset);
    }

    @Override
    public List<AuditEvent> getAuditTrail(UUID commandId, String domain) {
        return auditRepository.getEvents(commandId, domain);
    }

    // --- Helper Methods ---

    private Map<String, Object> buildMessage(
            String domain,
            String commandType,
            UUID commandId,
            Map<String, Object> data,
            UUID correlationId,
            String replyTo) {

        Map<String, Object> message = new HashMap<>();
        message.put("domain", domain);
        message.put("command_type", commandType);
        message.put("command_id", commandId.toString());
        message.put("correlation_id", correlationId.toString());
        message.put("data", data != null ? data : Map.of());

        if (replyTo != null) {
            message.put("reply_to", replyTo);
        }

        return message;
    }

    /**
     * Invoke batch completion callback (called by Worker).
     */
    public void invokeBatchCallback(UUID batchId, BatchMetadata batch) {
        Consumer<BatchMetadata> callback = batchCallbacks.remove(batchId);
        if (callback != null) {
            try {
                callback.accept(batch);
            } catch (Exception e) {
                log.error("Batch callback failed for batch {}", batchId, e);
            }
        }
    }
}
```

---

## 3. Usage Examples

### 3.1 Basic Command Send

```java
@Service
public class OrderService {

    private final CommandBus commandBus;

    public void createOrder(String customerId, List<Item> items) {
        var result = commandBus.send(
            "orders",
            "CreateOrder",
            UUID.randomUUID(),
            Map.of(
                "customer_id", customerId,
                "items", items
            )
        );

        log.info("Order command sent: {}", result.commandId());
    }
}
```

### 3.2 Command with Reply Queue

```java
public void requestPayment(String orderId, int amount, String callbackQueue) {
    commandBus.send(
        "payments",
        "ProcessPayment",
        UUID.randomUUID(),
        Map.of("order_id", orderId, "amount", amount),
        UUID.randomUUID(),  // correlationId
        callbackQueue,      // replyTo
        5                   // maxAttempts
    );
}
```

### 3.3 Batch Operations

```java
public void processBulkOrders(List<OrderRequest> orders) {
    var requests = orders.stream()
        .map(order -> SendRequest.of(
            "orders",
            "CreateOrder",
            UUID.randomUUID(),
            Map.of("customer_id", order.customerId(), "items", order.items())
        ))
        .toList();

    var result = commandBus.sendBatch(requests);

    log.info("Sent {} orders in {} chunks",
        result.totalCommands(), result.chunksProcessed());
}
```

### 3.4 Batch with Callback

```java
public void runBillingBatch(List<Invoice> invoices) {
    var commands = invoices.stream()
        .map(inv -> BatchCommand.of(
            "ProcessInvoice",
            UUID.randomUUID(),
            Map.of("invoice_id", inv.id(), "amount", inv.amount())
        ))
        .toList();

    var result = commandBus.createBatch(
        "billing",
        commands,
        UUID.randomUUID(),
        "Monthly billing - " + LocalDate.now(),
        Map.of("month", LocalDate.now().getMonth().name()),
        batch -> {
            log.info("Billing batch {} completed: {} successful, {} failed",
                batch.batchId(),
                batch.completedCount(),
                batch.canceledCount());
            notificationService.sendBillingReport(batch);
        }
    );
}
```

---

## 4. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CB-1 | send() persists command atomically | Integration test |
| CB-2 | send() raises DuplicateCommandException | Unit test |
| CB-3 | sendBatch() processes in chunks | Integration test |
| CB-4 | createBatch() creates all commands atomically | Integration test |
| CB-5 | Batch callback invoked on completion | Integration test |
| CB-6 | queryCommands() filters work correctly | Integration test |
| CB-7 | getAuditTrail() returns chronological events | Integration test |
| CB-8 | Correlation ID auto-generated if not provided | Unit test |
| CB-9 | NOTIFY sent after command creation | Integration test |
