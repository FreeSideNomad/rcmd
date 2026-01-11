# Worker Specification

## Overview

This specification defines the Worker component for the Java Command Bus library. The worker reads commands from PGMQ queues, dispatches them to handlers, and manages the command lifecycle including retries and error handling.

## Package Structure

```
com.commandbus.worker/
├── Worker.java                # Interface
├── WorkerProperties.java      # Configuration
├── ReceivedCommand.java       # Internal command wrapper
└── impl/
    └── DefaultWorker.java     # Implementation
```

---

## 1. Worker Interface

### 1.1 Worker

```java
package com.commandbus.worker;

import java.time.Duration;
import java.util.concurrent.CompletableFuture;

/**
 * Worker for processing commands from a domain queue.
 *
 * <p>The worker reads messages from PGMQ, dispatches them to registered handlers,
 * and manages the command lifecycle including retries and error handling.
 *
 * <p>Example:
 * <pre>
 * Worker worker = Worker.builder()
 *     .jdbcTemplate(jdbcTemplate)
 *     .domain("payments")
 *     .handlerRegistry(registry)
 *     .concurrency(4)
 *     .build();
 *
 * worker.start();
 * // ... later
 * worker.stop(Duration.ofSeconds(30));
 * </pre>
 */
public interface Worker {

    /**
     * Start the worker.
     *
     * <p>The worker begins reading messages from the queue and dispatching
     * them to handlers. Processing continues until stop() is called.
     */
    void start();

    /**
     * Stop the worker gracefully.
     *
     * <p>Stops accepting new messages and waits for in-flight commands
     * to complete within the specified timeout.
     *
     * @param timeout Maximum time to wait for in-flight commands
     * @return Future that completes when worker has stopped
     */
    CompletableFuture<Void> stop(Duration timeout);

    /**
     * Stop the worker immediately without waiting.
     */
    void stopNow();

    /**
     * Check if the worker is running.
     *
     * @return true if worker is accepting and processing commands
     */
    boolean isRunning();

    /**
     * Get the number of commands currently being processed.
     *
     * @return count of in-flight commands
     */
    int inFlightCount();

    /**
     * Get the domain this worker processes.
     *
     * @return domain name
     */
    String domain();

    /**
     * Create a new worker builder.
     *
     * @return new builder instance
     */
    static WorkerBuilder builder() {
        return new WorkerBuilder();
    }
}
```

### 1.2 WorkerBuilder

```java
package com.commandbus.worker;

import com.commandbus.handler.HandlerRegistry;
import com.commandbus.policy.RetryPolicy;
import com.commandbus.worker.impl.DefaultWorker;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Builder for creating Worker instances.
 */
public class WorkerBuilder {

    private JdbcTemplate jdbcTemplate;
    private String domain;
    private HandlerRegistry handlerRegistry;
    private int visibilityTimeout = 30;
    private int pollIntervalMs = 1000;
    private int concurrency = 1;
    private boolean useNotify = true;
    private RetryPolicy retryPolicy;

    /**
     * Set the JdbcTemplate for database operations.
     */
    public WorkerBuilder jdbcTemplate(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
        return this;
    }

    /**
     * Set the domain to process commands for.
     */
    public WorkerBuilder domain(String domain) {
        this.domain = domain;
        return this;
    }

    /**
     * Set the handler registry.
     */
    public WorkerBuilder handlerRegistry(HandlerRegistry handlerRegistry) {
        this.handlerRegistry = handlerRegistry;
        return this;
    }

    /**
     * Set the visibility timeout in seconds (default: 30).
     */
    public WorkerBuilder visibilityTimeout(int seconds) {
        this.visibilityTimeout = seconds;
        return this;
    }

    /**
     * Set the poll interval in milliseconds (default: 1000).
     */
    public WorkerBuilder pollIntervalMs(int ms) {
        this.pollIntervalMs = ms;
        return this;
    }

    /**
     * Set the concurrency level (default: 1).
     */
    public WorkerBuilder concurrency(int concurrency) {
        this.concurrency = concurrency;
        return this;
    }

    /**
     * Enable/disable PostgreSQL NOTIFY for instant wake-up (default: true).
     */
    public WorkerBuilder useNotify(boolean useNotify) {
        this.useNotify = useNotify;
        return this;
    }

    /**
     * Set the retry policy (default: 3 attempts with backoff [10, 60, 300]).
     */
    public WorkerBuilder retryPolicy(RetryPolicy retryPolicy) {
        this.retryPolicy = retryPolicy;
        return this;
    }

    /**
     * Build the worker instance.
     *
     * @return configured Worker
     * @throws IllegalStateException if required properties not set
     */
    public Worker build() {
        if (jdbcTemplate == null) throw new IllegalStateException("jdbcTemplate is required");
        if (domain == null) throw new IllegalStateException("domain is required");
        if (handlerRegistry == null) throw new IllegalStateException("handlerRegistry is required");

        if (retryPolicy == null) {
            retryPolicy = RetryPolicy.defaultPolicy();
        }

        return new DefaultWorker(
            jdbcTemplate,
            domain,
            handlerRegistry,
            visibilityTimeout,
            pollIntervalMs,
            concurrency,
            useNotify,
            retryPolicy
        );
    }
}
```

---

## 2. Configuration

### 2.1 WorkerProperties

```java
package com.commandbus.worker;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

/**
 * Configuration properties for workers.
 */
@ConfigurationProperties(prefix = "commandbus.worker")
public class WorkerProperties {

    /**
     * Visibility timeout in seconds (default: 30).
     */
    private int visibilityTimeout = 30;

    /**
     * Poll interval in milliseconds (default: 1000).
     */
    private int pollIntervalMs = 1000;

    /**
     * Concurrent handlers per worker (default: 4).
     */
    private int concurrency = 4;

    /**
     * Use PostgreSQL NOTIFY for instant wake-up (default: true).
     */
    private boolean useNotify = true;

    // Getters and setters...

    public int getVisibilityTimeout() { return visibilityTimeout; }
    public void setVisibilityTimeout(int visibilityTimeout) { this.visibilityTimeout = visibilityTimeout; }

    public int getPollIntervalMs() { return pollIntervalMs; }
    public void setPollIntervalMs(int pollIntervalMs) { this.pollIntervalMs = pollIntervalMs; }

    public int getConcurrency() { return concurrency; }
    public void setConcurrency(int concurrency) { this.concurrency = concurrency; }

    public boolean isUseNotify() { return useNotify; }
    public void setUseNotify(boolean useNotify) { this.useNotify = useNotify; }
}
```

### 2.2 RetryPolicy

```java
package com.commandbus.policy;

import java.util.List;

/**
 * Policy for handling command retries.
 *
 * @param maxAttempts Maximum number of attempts before giving up
 * @param backoffSchedule List of visibility timeouts in seconds for each retry
 */
public record RetryPolicy(
    int maxAttempts,
    List<Integer> backoffSchedule
) {
    /**
     * Default retry policy: 3 attempts with backoff [10, 60, 300].
     */
    public static RetryPolicy defaultPolicy() {
        return new RetryPolicy(3, List.of(10, 60, 300));
    }

    /**
     * Get the backoff delay for a given attempt number.
     *
     * @param attempt The current attempt number (1-based)
     * @return Visibility timeout in seconds for the next retry
     */
    public int getBackoff(int attempt) {
        if (attempt >= maxAttempts) {
            return 0; // No more retries
        }

        int index = attempt - 1;
        if (index < 0) {
            return backoffSchedule.isEmpty() ? 30 : backoffSchedule.get(0);
        }

        if (index < backoffSchedule.size()) {
            return backoffSchedule.get(index);
        }

        // Use last value for attempts beyond schedule
        return backoffSchedule.isEmpty() ? 30 : backoffSchedule.get(backoffSchedule.size() - 1);
    }

    /**
     * Check if another retry should be attempted.
     *
     * @param attempt The current attempt number (1-based)
     * @return true if more attempts are allowed
     */
    public boolean shouldRetry(int attempt) {
        return attempt < maxAttempts;
    }
}
```

---

## 3. Implementation

### 3.1 DefaultWorker

```java
package com.commandbus.worker.impl;

import com.commandbus.exception.PermanentCommandException;
import com.commandbus.exception.TransientCommandException;
import com.commandbus.handler.HandlerRegistry;
import com.commandbus.model.*;
import com.commandbus.pgmq.PgmqClient;
import com.commandbus.pgmq.impl.JdbcPgmqClient;
import com.commandbus.policy.RetryPolicy;
import com.commandbus.repository.AuditRepository;
import com.commandbus.repository.BatchRepository;
import com.commandbus.repository.CommandRepository;
import com.commandbus.repository.impl.JdbcAuditRepository;
import com.commandbus.repository.impl.JdbcBatchRepository;
import com.commandbus.repository.impl.JdbcCommandRepository;
import com.commandbus.worker.Worker;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;

import java.sql.Connection;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Default worker implementation using virtual threads.
 */
public class DefaultWorker implements Worker {

    private static final Logger log = LoggerFactory.getLogger(DefaultWorker.class);
    private static final String NOTIFY_CHANNEL_PREFIX = "pgmq_notify";

    private final JdbcTemplate jdbcTemplate;
    private final String domain;
    private final String queueName;
    private final HandlerRegistry handlerRegistry;
    private final int visibilityTimeout;
    private final int pollIntervalMs;
    private final int concurrency;
    private final boolean useNotify;
    private final RetryPolicy retryPolicy;

    private final PgmqClient pgmqClient;
    private final CommandRepository commandRepository;
    private final BatchRepository batchRepository;
    private final AuditRepository auditRepository;
    private final ObjectMapper objectMapper;

    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean stopping = new AtomicBoolean(false);
    private final AtomicInteger inFlightCount = new AtomicInteger(0);
    private final Semaphore semaphore;
    private final Set<Future<?>> inFlightTasks = ConcurrentHashMap.newKeySet();

    private ExecutorService executor;
    private Future<?> mainLoop;

    public DefaultWorker(
            JdbcTemplate jdbcTemplate,
            String domain,
            HandlerRegistry handlerRegistry,
            int visibilityTimeout,
            int pollIntervalMs,
            int concurrency,
            boolean useNotify,
            RetryPolicy retryPolicy) {

        this.jdbcTemplate = jdbcTemplate;
        this.domain = domain;
        this.queueName = domain + "__commands";
        this.handlerRegistry = handlerRegistry;
        this.visibilityTimeout = visibilityTimeout;
        this.pollIntervalMs = pollIntervalMs;
        this.concurrency = concurrency;
        this.useNotify = useNotify;
        this.retryPolicy = retryPolicy;

        this.objectMapper = new ObjectMapper();
        this.pgmqClient = new JdbcPgmqClient(jdbcTemplate, objectMapper);
        this.commandRepository = new JdbcCommandRepository(jdbcTemplate, objectMapper);
        this.batchRepository = new JdbcBatchRepository(jdbcTemplate, objectMapper);
        this.auditRepository = new JdbcAuditRepository(jdbcTemplate, objectMapper);

        this.semaphore = new Semaphore(concurrency);
    }

    @Override
    public void start() {
        if (running.getAndSet(true)) {
            log.warn("Worker for {} already running", domain);
            return;
        }

        stopping.set(false);
        executor = Executors.newVirtualThreadPerTaskExecutor();

        log.info("Starting worker for domain={}, concurrency={}, useNotify={}",
            domain, concurrency, useNotify);

        mainLoop = executor.submit(this::runLoop);
    }

    @Override
    public CompletableFuture<Void> stop(Duration timeout) {
        if (!running.get()) {
            return CompletableFuture.completedFuture(null);
        }

        stopping.set(true);
        log.info("Stopping worker for {}, waiting for {} in-flight commands",
            domain, inFlightCount.get());

        return CompletableFuture.runAsync(() -> {
            try {
                // Wait for in-flight tasks
                long deadline = System.currentTimeMillis() + timeout.toMillis();
                while (inFlightCount.get() > 0 && System.currentTimeMillis() < deadline) {
                    Thread.sleep(100);
                }

                if (inFlightCount.get() > 0) {
                    log.warn("Timeout waiting for {} in-flight commands", inFlightCount.get());
                }

                running.set(false);
                executor.shutdown();

                if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                    executor.shutdownNow();
                }

                log.info("Worker for {} stopped", domain);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });
    }

    @Override
    public void stopNow() {
        stopping.set(true);
        running.set(false);
        if (executor != null) {
            executor.shutdownNow();
        }
    }

    @Override
    public boolean isRunning() {
        return running.get() && !stopping.get();
    }

    @Override
    public int inFlightCount() {
        return inFlightCount.get();
    }

    @Override
    public String domain() {
        return domain;
    }

    // --- Main Processing Loop ---

    private void runLoop() {
        log.debug("Worker loop started for {}", domain);

        while (running.get() && !stopping.get()) {
            try {
                drainQueue();

                // Wait for new messages or poll interval
                if (!stopping.get()) {
                    waitForMessages();
                }
            } catch (Exception e) {
                if (!stopping.get()) {
                    log.error("Error in worker loop for {}", domain, e);
                    sleep(1000); // Back off on error
                }
            }
        }

        log.debug("Worker loop ended for {}", domain);
    }

    private void drainQueue() {
        while (running.get() && !stopping.get()) {
            int availableSlots = semaphore.availablePermits();
            if (availableSlots == 0) {
                // Wait for a slot to become available
                waitForSlot();
                continue;
            }

            // Read up to available slots messages
            List<PgmqMessage> messages = pgmqClient.read(queueName, visibilityTimeout, availableSlots);

            if (messages.isEmpty()) {
                break; // Queue drained
            }

            for (PgmqMessage message : messages) {
                processMessage(message);
            }

            // Yield to allow fair scheduling
            Thread.yield();
        }
    }

    private void waitForSlot() {
        try {
            semaphore.acquire();
            semaphore.release();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void waitForMessages() {
        if (useNotify) {
            // TODO: Implement PostgreSQL LISTEN/NOTIFY
            // For now, fall back to polling
            sleep(pollIntervalMs);
        } else {
            sleep(pollIntervalMs);
        }
    }

    private void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // --- Message Processing ---

    private void processMessage(PgmqMessage pgmqMessage) {
        try {
            semaphore.acquire();
            inFlightCount.incrementAndGet();

            var future = executor.submit(() -> {
                try {
                    processMessageInternal(pgmqMessage);
                } finally {
                    inFlightCount.decrementAndGet();
                    semaphore.release();
                }
            });

            inFlightTasks.add(future);
            future.whenComplete((v, e) -> inFlightTasks.remove(future));

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void processMessageInternal(PgmqMessage pgmqMessage) {
        Map<String, Object> payload = pgmqMessage.message();

        String commandIdStr = (String) payload.get("command_id");
        UUID commandId = UUID.fromString(commandIdStr);

        log.debug("Processing message msgId={}, commandId={}", pgmqMessage.msgId(), commandId);

        try {
            // Atomically receive the command
            Optional<CommandMetadata> metadataOpt = commandRepository.spReceiveCommand(
                domain, commandId, pgmqMessage.msgId(), null
            );

            if (metadataOpt.isEmpty()) {
                log.debug("Command {} not receivable (terminal state or not found)", commandId);
                return;
            }

            CommandMetadata metadata = metadataOpt.get();

            // Build Command and Context
            Command command = buildCommand(payload, metadata);
            HandlerContext context = buildContext(command, metadata, pgmqMessage.msgId());

            // Dispatch to handler
            Object result = handlerRegistry.dispatch(command, context);

            // Complete successfully
            complete(metadata, pgmqMessage.msgId(), result);

        } catch (TransientCommandException e) {
            handleTransientError(commandId, pgmqMessage.msgId(), e);
        } catch (PermanentCommandException e) {
            handlePermanentError(commandId, pgmqMessage.msgId(), e);
        } catch (Exception e) {
            // Treat unknown exceptions as transient
            handleTransientError(commandId, pgmqMessage.msgId(),
                new TransientCommandException("INTERNAL_ERROR", e.getMessage()));
        }
    }

    private Command buildCommand(Map<String, Object> payload, CommandMetadata metadata) {
        return new Command(
            (String) payload.get("domain"),
            (String) payload.get("command_type"),
            UUID.fromString((String) payload.get("command_id")),
            (Map<String, Object>) payload.getOrDefault("data", Map.of()),
            payload.get("correlation_id") != null ?
                UUID.fromString((String) payload.get("correlation_id")) : null,
            (String) payload.get("reply_to"),
            metadata.createdAt()
        );
    }

    private HandlerContext buildContext(Command command, CommandMetadata metadata, long msgId) {
        return new HandlerContext(
            command,
            metadata.attempts(),
            metadata.maxAttempts(),
            msgId,
            seconds -> pgmqClient.setVisibilityTimeout(queueName, msgId, seconds)
        );
    }

    // --- Completion Handling ---

    private void complete(CommandMetadata metadata, long msgId, Object result) {
        log.debug("Completing command {} with result", metadata.commandId());

        // Delete from queue
        pgmqClient.delete(queueName, msgId);

        // Update status via stored procedure
        String details = result != null ? serializeResult(result) : null;
        boolean isBatchComplete = commandRepository.spFinishCommand(
            domain,
            metadata.commandId(),
            CommandStatus.COMPLETED,
            AuditEventType.COMPLETED,
            null, null, null,
            details,
            metadata.batchId()
        );

        // Send reply if configured
        if (metadata.replyTo() != null && !metadata.replyTo().isBlank()) {
            sendReply(metadata, ReplyOutcome.SUCCESS, result, null, null);
        }

        // Invoke batch callback if complete
        if (isBatchComplete && metadata.batchId() != null) {
            invokeBatchCallback(metadata.batchId());
        }

        log.info("Completed command {}.{} (commandId={})",
            domain, metadata.commandType(), metadata.commandId());
    }

    private void handleTransientError(UUID commandId, long msgId, TransientCommandException e) {
        log.debug("Transient error for command {}: {}", commandId, e.getMessage());

        Optional<CommandMetadata> metadataOpt = commandRepository.get(domain, commandId);
        if (metadataOpt.isEmpty()) return;

        CommandMetadata metadata = metadataOpt.get();

        if (retryPolicy.shouldRetry(metadata.attempts())) {
            // Record failure and schedule retry
            commandRepository.spFailCommand(
                domain, commandId,
                "TRANSIENT", e.getCode(), e.getErrorMessage(),
                metadata.attempts(), metadata.maxAttempts(), msgId
            );

            int backoff = retryPolicy.getBackoff(metadata.attempts());
            pgmqClient.setVisibilityTimeout(queueName, msgId, backoff);

            log.info("Scheduled retry for command {} in {}s (attempt {}/{})",
                commandId, backoff, metadata.attempts(), metadata.maxAttempts());
        } else {
            // Retries exhausted - move to TSQ
            failExhausted(metadata, msgId, e);
        }
    }

    private void handlePermanentError(UUID commandId, long msgId, PermanentCommandException e) {
        log.debug("Permanent error for command {}: {}", commandId, e.getMessage());

        Optional<CommandMetadata> metadataOpt = commandRepository.get(domain, commandId);
        if (metadataOpt.isEmpty()) return;

        CommandMetadata metadata = metadataOpt.get();

        // Archive the message
        pgmqClient.archive(queueName, msgId);

        // Update status
        commandRepository.spFinishCommand(
            domain, commandId,
            CommandStatus.IN_TROUBLESHOOTING_QUEUE,
            AuditEventType.MOVED_TO_TSQ,
            "PERMANENT", e.getCode(), e.getErrorMessage(),
            null,
            metadata.batchId()
        );

        // Send failure reply
        if (metadata.replyTo() != null) {
            sendReply(metadata, ReplyOutcome.FAILED, null, e.getCode(), e.getErrorMessage());
        }

        log.warn("Command {} moved to TSQ (permanent error): {}",
            commandId, e.getMessage());
    }

    private void failExhausted(CommandMetadata metadata, long msgId, TransientCommandException e) {
        // Archive the message
        pgmqClient.archive(queueName, msgId);

        // Update status
        commandRepository.spFinishCommand(
            domain, metadata.commandId(),
            CommandStatus.IN_TROUBLESHOOTING_QUEUE,
            AuditEventType.MOVED_TO_TSQ,
            "TRANSIENT", e.getCode(), e.getErrorMessage(),
            null,
            metadata.batchId()
        );

        // Send failure reply
        if (metadata.replyTo() != null) {
            sendReply(metadata, ReplyOutcome.FAILED, null, e.getCode(), e.getErrorMessage());
        }

        log.warn("Command {} moved to TSQ (retries exhausted): {}",
            metadata.commandId(), e.getMessage());
    }

    private void sendReply(CommandMetadata metadata, ReplyOutcome outcome,
                          Object result, String errorCode, String errorMessage) {
        try {
            Map<String, Object> reply = new HashMap<>();
            reply.put("command_id", metadata.commandId().toString());
            if (metadata.correlationId() != null) {
                reply.put("correlation_id", metadata.correlationId().toString());
            }
            reply.put("outcome", outcome.getValue());

            if (result != null) {
                reply.put("result", result);
            }
            if (errorCode != null) {
                reply.put("error_code", errorCode);
                reply.put("error_message", errorMessage);
            }

            pgmqClient.send(metadata.replyTo(), reply);
        } catch (Exception e) {
            log.error("Failed to send reply for command {}", metadata.commandId(), e);
        }
    }

    private void invokeBatchCallback(UUID batchId) {
        // TODO: Implement batch callback invocation
        log.debug("Batch {} completed", batchId);
    }

    private String serializeResult(Object result) {
        try {
            return objectMapper.writeValueAsString(Map.of("result", result));
        } catch (Exception e) {
            return null;
        }
    }
}
```

---

## 4. Concurrency Model

### 4.1 Virtual Threads

Java 21 virtual threads provide lightweight concurrency:

```java
// Virtual thread executor (millions of threads possible)
executor = Executors.newVirtualThreadPerTaskExecutor();

// Each message processed in its own virtual thread
executor.submit(() -> processMessage(message));
```

### 4.2 Semaphore-Based Throttling

```java
// Limit concurrent handlers
private final Semaphore semaphore = new Semaphore(concurrency);

// Acquire before processing
semaphore.acquire();
try {
    processMessage(message);
} finally {
    semaphore.release();
}
```

### 4.3 Queue Draining Strategy

```
┌─────────────────────────────────────────────────────────┐
│  MAIN LOOP                                              │
│                                                         │
│  while (running) {                                      │
│      drainQueue()     ←─── Process all available msgs   │
│      waitForMessages() ←─── NOTIFY or poll timeout      │
│  }                                                      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  DRAIN QUEUE                                            │
│                                                         │
│  while (!empty && !stopping) {                          │
│      availableSlots = semaphore.availablePermits()      │
│      messages = pgmq.read(queue, vt, availableSlots)    │
│      for (msg : messages) {                             │
│          processMessage(msg)  ←─── Async in virtual thr │
│      }                                                  │
│      Thread.yield()  ←─── Fair scheduling               │
│  }                                                      │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Error Handling Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  HANDLER EXECUTION                                                   │
│                                                                      │
│  try {                                                               │
│      result = handler.handle(command, context)                       │
│      complete(metadata, msgId, result)  ←─── SUCCESS                 │
│  }                                                                   │
│  catch (TransientCommandException e) {                               │
│      if (retryPolicy.shouldRetry(attempt)) {                         │
│          recordFailure()                                             │
│          setVisibilityTimeout(backoff)  ←─── RETRY SCHEDULED         │
│      } else {                                                        │
│          archive()                                                   │
│          moveToTSQ()  ←─── RETRIES EXHAUSTED                         │
│      }                                                               │
│  }                                                                   │
│  catch (PermanentCommandException e) {                               │
│      archive()                                                       │
│      moveToTSQ()  ←─── PERMANENT FAILURE                             │
│  }                                                                   │
│  catch (Exception e) {                                               │
│      // Treat as transient  ←─── UNKNOWN ERROR                       │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. Graceful Shutdown

```java
// Graceful shutdown with timeout
worker.stop(Duration.ofSeconds(30))
    .thenRun(() -> log.info("Worker stopped"))
    .exceptionally(e -> {
        log.error("Error stopping worker", e);
        return null;
    });

// Immediate shutdown (for fatal errors)
worker.stopNow();
```

---

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| WK-1 | Worker reads messages from correct queue | Integration test |
| WK-2 | Worker respects concurrency limit | Integration test |
| WK-3 | Handler invoked with correct Command/Context | Integration test |
| WK-4 | Successful completion deletes PGMQ message | Integration test |
| WK-5 | TransientException triggers retry with backoff | Integration test |
| WK-6 | PermanentException moves to TSQ immediately | Integration test |
| WK-7 | Retries exhausted moves to TSQ | Integration test |
| WK-8 | Reply sent if reply_to configured | Integration test |
| WK-9 | Graceful shutdown waits for in-flight | Integration test |
| WK-10 | inFlightCount() returns correct value | Unit test |
| WK-11 | Virtual threads handle high concurrency | Load test |
