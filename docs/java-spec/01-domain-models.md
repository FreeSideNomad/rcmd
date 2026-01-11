# Domain Models Specification

## Overview

This specification defines the domain model classes for the Java Command Bus library. All domain objects are implemented as Java 21 records (immutable) where appropriate, with no persistence annotations to maintain a clean domain model.

## Package Structure

```
com.commandbus.model/
├── Command.java           # Immutable command
├── CommandMetadata.java   # Mutable command state
├── CommandStatus.java     # Status enum
├── HandlerContext.java    # Handler execution context
├── Reply.java             # Reply message
├── ReplyOutcome.java      # Reply outcome enum
├── SendRequest.java       # Single send request
├── SendResult.java        # Send operation result
├── BatchCommand.java      # Command in a batch
├── BatchMetadata.java     # Batch state
├── BatchStatus.java       # Batch status enum
├── BatchSendResult.java   # Batch send result
├── CreateBatchResult.java # Batch creation result
├── TroubleshootingItem.java # TSQ item
├── AuditEvent.java        # Audit trail entry
└── PgmqMessage.java       # Raw PGMQ message

com.commandbus.exception/
├── CommandBusException.java        # Base exception
├── TransientCommandException.java  # Retryable failure
├── PermanentCommandException.java  # Non-retryable failure
├── HandlerNotFoundException.java   # Handler not registered
├── HandlerAlreadyRegisteredException.java
├── DuplicateCommandException.java  # Duplicate command_id
├── CommandNotFoundException.java   # Command not found
├── BatchNotFoundException.java     # Batch not found
└── InvalidOperationException.java  # Invalid state transition
```

---

## 1. Enums

### 1.1 CommandStatus

```java
package com.commandbus.model;

/**
 * Status of a command in its lifecycle.
 */
public enum CommandStatus {
    /** Command queued, awaiting processing */
    PENDING("PENDING"),

    /** Currently being processed by a worker */
    IN_PROGRESS("IN_PROGRESS"),

    /** Successfully completed */
    COMPLETED("COMPLETED"),

    /** Failed (legacy status, use IN_TROUBLESHOOTING_QUEUE) */
    FAILED("FAILED"),

    /** Canceled by operator */
    CANCELED("CANCELED"),

    /** Failed after retries exhausted or permanent error */
    IN_TROUBLESHOOTING_QUEUE("IN_TROUBLESHOOTING_QUEUE");

    private final String value;

    CommandStatus(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static CommandStatus fromValue(String value) {
        for (CommandStatus status : values()) {
            if (status.value.equals(value)) {
                return status;
            }
        }
        throw new IllegalArgumentException("Unknown CommandStatus: " + value);
    }
}
```

### 1.2 ReplyOutcome

```java
package com.commandbus.model;

/**
 * Outcome of command processing.
 */
public enum ReplyOutcome {
    SUCCESS("SUCCESS"),
    FAILED("FAILED"),
    CANCELED("CANCELED");

    private final String value;

    ReplyOutcome(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static ReplyOutcome fromValue(String value) {
        for (ReplyOutcome outcome : values()) {
            if (outcome.value.equals(value)) {
                return outcome;
            }
        }
        throw new IllegalArgumentException("Unknown ReplyOutcome: " + value);
    }
}
```

### 1.3 BatchStatus

```java
package com.commandbus.model;

/**
 * Status of a batch in its lifecycle.
 */
public enum BatchStatus {
    /** Batch created, no commands processed yet */
    PENDING("PENDING"),

    /** At least one command being processed */
    IN_PROGRESS("IN_PROGRESS"),

    /** All commands completed successfully */
    COMPLETED("COMPLETED"),

    /** All commands done, but some failed/canceled */
    COMPLETED_WITH_FAILURES("COMPLETED_WITH_FAILURES");

    private final String value;

    BatchStatus(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static BatchStatus fromValue(String value) {
        for (BatchStatus status : values()) {
            if (status.value.equals(value)) {
                return status;
            }
        }
        throw new IllegalArgumentException("Unknown BatchStatus: " + value);
    }
}
```

---

## 2. Core Records

### 2.1 Command (Immutable)

```java
package com.commandbus.model;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * A command to be processed by a handler.
 *
 * <p>Commands are immutable value objects representing work to be done.
 * They contain the command payload and metadata needed for routing and tracing.
 *
 * @param domain The domain this command belongs to (e.g., "payments")
 * @param commandType The type of command (e.g., "DebitAccount")
 * @param commandId Unique identifier for this command
 * @param data The command payload as a map
 * @param correlationId ID for tracing related commands (nullable)
 * @param replyTo Queue to send reply to (nullable)
 * @param createdAt When the command was created
 */
public record Command(
    String domain,
    String commandType,
    UUID commandId,
    Map<String, Object> data,
    UUID correlationId,
    String replyTo,
    Instant createdAt
) {
    /**
     * Creates a command with validation.
     */
    public Command {
        if (domain == null || domain.isBlank()) {
            throw new IllegalArgumentException("domain is required");
        }
        if (commandType == null || commandType.isBlank()) {
            throw new IllegalArgumentException("commandType is required");
        }
        if (commandId == null) {
            throw new IllegalArgumentException("commandId is required");
        }
        if (data == null) {
            data = Map.of();
        }
        if (createdAt == null) {
            createdAt = Instant.now();
        }
        // Make data immutable
        data = Map.copyOf(data);
    }
}
```

### 2.2 HandlerContext

```java
package com.commandbus.model;

import java.util.concurrent.CompletableFuture;
import java.util.function.IntConsumer;

/**
 * Context provided to command handlers during execution.
 *
 * <p>Provides access to command metadata and utilities like visibility
 * timeout extension for long-running handlers.
 *
 * @param command The command being processed
 * @param attempt Current attempt number (1-based)
 * @param maxAttempts Maximum attempts before exhaustion
 * @param msgId PGMQ message ID
 * @param visibilityExtender Function to extend visibility timeout (nullable)
 */
public record HandlerContext(
    Command command,
    int attempt,
    int maxAttempts,
    long msgId,
    VisibilityExtender visibilityExtender
) {
    /**
     * Extend the visibility timeout for long-running operations.
     *
     * @param seconds Additional seconds to extend visibility
     * @throws IllegalStateException if visibility extender is not available
     */
    public void extendVisibility(int seconds) {
        if (visibilityExtender == null) {
            throw new IllegalStateException("Visibility extender not available");
        }
        visibilityExtender.extend(seconds);
    }

    /**
     * Check if this is the last retry attempt.
     *
     * @return true if no more retries after this attempt
     */
    public boolean isLastAttempt() {
        return attempt >= maxAttempts;
    }

    /**
     * Functional interface for extending message visibility.
     */
    @FunctionalInterface
    public interface VisibilityExtender {
        void extend(int seconds);
    }
}
```

### 2.3 CommandMetadata

```java
package com.commandbus.model;

import java.time.Instant;
import java.util.UUID;

/**
 * Metadata stored for each command.
 *
 * <p>Unlike Command (immutable), CommandMetadata is mutable and tracks
 * the evolving state of command processing.
 *
 * @param domain The domain this command belongs to
 * @param commandId Unique identifier
 * @param commandType Type of command
 * @param status Current status
 * @param attempts Number of processing attempts
 * @param maxAttempts Maximum allowed attempts
 * @param msgId Current PGMQ message ID (nullable)
 * @param correlationId Correlation ID for tracing (nullable)
 * @param replyTo Reply queue (nullable)
 * @param lastErrorType Type of last error (TRANSIENT/PERMANENT, nullable)
 * @param lastErrorCode Application error code (nullable)
 * @param lastErrorMessage Error message (nullable)
 * @param createdAt Creation timestamp
 * @param updatedAt Last update timestamp
 * @param batchId Optional batch ID (nullable)
 */
public record CommandMetadata(
    String domain,
    UUID commandId,
    String commandType,
    CommandStatus status,
    int attempts,
    int maxAttempts,
    Long msgId,
    UUID correlationId,
    String replyTo,
    String lastErrorType,
    String lastErrorCode,
    String lastErrorMessage,
    Instant createdAt,
    Instant updatedAt,
    UUID batchId
) {
    /**
     * Creates a new command metadata with default values.
     */
    public static CommandMetadata create(
            String domain,
            UUID commandId,
            String commandType,
            int maxAttempts) {
        var now = Instant.now();
        return new CommandMetadata(
            domain, commandId, commandType,
            CommandStatus.PENDING,
            0, maxAttempts,
            null, null, null,
            null, null, null,
            now, now, null
        );
    }

    /**
     * Returns a copy with updated status.
     */
    public CommandMetadata withStatus(CommandStatus newStatus) {
        return new CommandMetadata(
            domain, commandId, commandType,
            newStatus,
            attempts, maxAttempts,
            msgId, correlationId, replyTo,
            lastErrorType, lastErrorCode, lastErrorMessage,
            createdAt, Instant.now(), batchId
        );
    }

    /**
     * Returns a copy with error information.
     */
    public CommandMetadata withError(String errorType, String errorCode, String errorMessage) {
        return new CommandMetadata(
            domain, commandId, commandType,
            status,
            attempts, maxAttempts,
            msgId, correlationId, replyTo,
            errorType, errorCode, errorMessage,
            createdAt, Instant.now(), batchId
        );
    }
}
```

### 2.4 Reply

```java
package com.commandbus.model;

import java.util.Map;
import java.util.UUID;

/**
 * Reply message sent after command processing.
 *
 * @param commandId ID of the command this is a reply to
 * @param correlationId Correlation ID from the command (nullable)
 * @param outcome Result of processing
 * @param data Optional result data (nullable)
 * @param errorCode Error code if failed (nullable)
 * @param errorMessage Error message if failed (nullable)
 */
public record Reply(
    UUID commandId,
    UUID correlationId,
    ReplyOutcome outcome,
    Map<String, Object> data,
    String errorCode,
    String errorMessage
) {
    /**
     * Creates a success reply.
     */
    public static Reply success(UUID commandId, UUID correlationId, Map<String, Object> data) {
        return new Reply(commandId, correlationId, ReplyOutcome.SUCCESS, data, null, null);
    }

    /**
     * Creates a failed reply.
     */
    public static Reply failed(UUID commandId, UUID correlationId, String errorCode, String errorMessage) {
        return new Reply(commandId, correlationId, ReplyOutcome.FAILED, null, errorCode, errorMessage);
    }

    /**
     * Creates a canceled reply.
     */
    public static Reply canceled(UUID commandId, UUID correlationId) {
        return new Reply(commandId, correlationId, ReplyOutcome.CANCELED, null, null, null);
    }
}
```

---

## 3. Send/Receive Records

### 3.1 SendRequest

```java
package com.commandbus.model;

import java.util.Map;
import java.util.UUID;

/**
 * Request to send a single command (used in batch operations).
 *
 * @param domain The domain to send to
 * @param commandType The type of command
 * @param commandId Unique identifier for this command
 * @param data The command payload
 * @param correlationId Optional correlation ID (nullable)
 * @param replyTo Optional reply queue name (nullable)
 * @param maxAttempts Max retry attempts (nullable, uses default if null)
 */
public record SendRequest(
    String domain,
    String commandType,
    UUID commandId,
    Map<String, Object> data,
    UUID correlationId,
    String replyTo,
    Integer maxAttempts
) {
    /**
     * Creates a simple send request.
     */
    public static SendRequest of(String domain, String commandType, UUID commandId, Map<String, Object> data) {
        return new SendRequest(domain, commandType, commandId, data, null, null, null);
    }
}
```

### 3.2 SendResult

```java
package com.commandbus.model;

import java.util.UUID;

/**
 * Result of sending a command.
 *
 * @param commandId The unique ID of the sent command
 * @param msgId The PGMQ message ID assigned
 */
public record SendResult(
    UUID commandId,
    long msgId
) {}
```

### 3.3 BatchSendResult

```java
package com.commandbus.model;

import java.util.List;

/**
 * Result of a batch send operation.
 *
 * @param results Individual results for each command sent
 * @param chunksProcessed Number of transaction chunks processed
 * @param totalCommands Total number of commands sent
 */
public record BatchSendResult(
    List<SendResult> results,
    int chunksProcessed,
    int totalCommands
) {
    public BatchSendResult {
        results = List.copyOf(results);
    }
}
```

---

## 4. Batch Records

### 4.1 BatchCommand

```java
package com.commandbus.model;

import java.util.Map;
import java.util.UUID;

/**
 * A command to be included in a batch.
 *
 * @param commandType The type of command
 * @param commandId Unique identifier for this command
 * @param data The command payload
 * @param correlationId Optional correlation ID (nullable)
 * @param replyTo Optional reply queue name (nullable)
 * @param maxAttempts Max retry attempts (nullable, uses default if null)
 */
public record BatchCommand(
    String commandType,
    UUID commandId,
    Map<String, Object> data,
    UUID correlationId,
    String replyTo,
    Integer maxAttempts
) {
    public BatchCommand {
        if (commandType == null || commandType.isBlank()) {
            throw new IllegalArgumentException("commandType is required");
        }
        if (commandId == null) {
            throw new IllegalArgumentException("commandId is required");
        }
        if (data == null) {
            data = Map.of();
        }
    }

    /**
     * Creates a simple batch command.
     */
    public static BatchCommand of(String commandType, UUID commandId, Map<String, Object> data) {
        return new BatchCommand(commandType, commandId, data, null, null, null);
    }
}
```

### 4.2 BatchMetadata

```java
package com.commandbus.model;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Metadata stored for a batch of commands.
 *
 * @param domain The domain this batch belongs to
 * @param batchId Unique identifier
 * @param name Optional human-readable name (nullable)
 * @param customData Optional custom metadata (nullable)
 * @param status Current batch status
 * @param totalCount Total number of commands in the batch
 * @param completedCount Number of successfully completed commands
 * @param canceledCount Number of canceled commands
 * @param inTroubleshootingCount Number of commands currently in TSQ
 * @param createdAt Batch creation timestamp
 * @param startedAt When first command was processed (nullable)
 * @param completedAt When all commands reached terminal state (nullable)
 */
public record BatchMetadata(
    String domain,
    UUID batchId,
    String name,
    Map<String, Object> customData,
    BatchStatus status,
    int totalCount,
    int completedCount,
    int canceledCount,
    int inTroubleshootingCount,
    Instant createdAt,
    Instant startedAt,
    Instant completedAt
) {
    /**
     * Checks if the batch is complete (all commands in terminal state).
     */
    public boolean isComplete() {
        return status == BatchStatus.COMPLETED || status == BatchStatus.COMPLETED_WITH_FAILURES;
    }

    /**
     * Checks if all commands finished successfully.
     */
    public boolean isFullySuccessful() {
        return status == BatchStatus.COMPLETED && canceledCount == 0 && inTroubleshootingCount == 0;
    }
}
```

### 4.3 CreateBatchResult

```java
package com.commandbus.model;

import java.util.List;
import java.util.UUID;

/**
 * Result of creating a batch with commands.
 *
 * @param batchId The unique ID of the created batch
 * @param commandResults Individual results for each command sent
 * @param totalCommands Total number of commands in the batch
 */
public record CreateBatchResult(
    UUID batchId,
    List<SendResult> commandResults,
    int totalCommands
) {
    public CreateBatchResult {
        commandResults = List.copyOf(commandResults);
    }
}
```

---

## 5. Operational Records

### 5.1 TroubleshootingItem

```java
package com.commandbus.model;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * A command in the troubleshooting queue awaiting operator action.
 *
 * @param domain The domain this command belongs to
 * @param commandId Unique identifier
 * @param commandType Type of command
 * @param attempts Number of processing attempts made
 * @param maxAttempts Maximum allowed attempts
 * @param lastErrorType Type of last error (nullable)
 * @param lastErrorCode Application error code (nullable)
 * @param lastErrorMessage Error message (nullable)
 * @param correlationId Correlation ID for tracing (nullable)
 * @param replyTo Reply queue (nullable)
 * @param payload Original command payload from PGMQ archive (nullable)
 * @param createdAt When the command was created
 * @param updatedAt When the command was last updated
 */
public record TroubleshootingItem(
    String domain,
    UUID commandId,
    String commandType,
    int attempts,
    int maxAttempts,
    String lastErrorType,
    String lastErrorCode,
    String lastErrorMessage,
    UUID correlationId,
    String replyTo,
    Map<String, Object> payload,
    Instant createdAt,
    Instant updatedAt
) {}
```

### 5.2 AuditEvent

```java
package com.commandbus.model;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * An audit event in a command's lifecycle.
 *
 * @param auditId Unique identifier for this audit event
 * @param domain The domain of the command
 * @param commandId The command ID
 * @param eventType Type of event (SENT, RECEIVED, FAILED, etc.)
 * @param timestamp When the event occurred
 * @param details Optional additional details (nullable)
 */
public record AuditEvent(
    long auditId,
    String domain,
    UUID commandId,
    String eventType,
    Instant timestamp,
    Map<String, Object> details
) {}
```

### 5.3 AuditEventType (Constants)

```java
package com.commandbus.model;

/**
 * Standard audit event types.
 */
public final class AuditEventType {
    private AuditEventType() {}

    public static final String SENT = "SENT";
    public static final String RECEIVED = "RECEIVED";
    public static final String COMPLETED = "COMPLETED";
    public static final String FAILED = "FAILED";
    public static final String RETRY_SCHEDULED = "RETRY_SCHEDULED";
    public static final String MOVED_TO_TSQ = "MOVED_TO_TSQ";
    public static final String OPERATOR_RETRY = "OPERATOR_RETRY";
    public static final String OPERATOR_CANCEL = "OPERATOR_CANCEL";
    public static final String OPERATOR_COMPLETE = "OPERATOR_COMPLETE";
    public static final String BATCH_STARTED = "BATCH_STARTED";
    public static final String BATCH_COMPLETED = "BATCH_COMPLETED";
}
```

---

## 6. PGMQ Message

### 6.1 PgmqMessage

```java
package com.commandbus.model;

import java.time.Instant;
import java.util.Map;

/**
 * A message from a PGMQ queue.
 *
 * @param msgId Unique message ID
 * @param readCount Number of times message has been read
 * @param enqueuedAt When the message was enqueued
 * @param visibilityTimeout Visibility timeout timestamp
 * @param message The message payload
 */
public record PgmqMessage(
    long msgId,
    int readCount,
    Instant enqueuedAt,
    Instant visibilityTimeout,
    Map<String, Object> message
) {}
```

---

## 7. Exceptions

### 7.1 Base Exception

```java
package com.commandbus.exception;

/**
 * Base exception for all Command Bus errors.
 */
public class CommandBusException extends RuntimeException {

    public CommandBusException(String message) {
        super(message);
    }

    public CommandBusException(String message, Throwable cause) {
        super(message, cause);
    }
}
```

### 7.2 TransientCommandException

```java
package com.commandbus.exception;

import java.util.Map;

/**
 * Raised for retryable failures (network, timeout, temporary unavailability).
 *
 * <p>When a handler throws this exception, the command will be retried
 * according to the retry policy. After max attempts, it moves to TSQ.
 */
public class TransientCommandException extends CommandBusException {

    private final String code;
    private final String errorMessage;
    private final Map<String, Object> details;

    public TransientCommandException(String code, String message) {
        this(code, message, Map.of());
    }

    public TransientCommandException(String code, String message, Map<String, Object> details) {
        super("[" + code + "] " + message);
        this.code = code;
        this.errorMessage = message;
        this.details = details != null ? Map.copyOf(details) : Map.of();
    }

    public String getCode() {
        return code;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public Map<String, Object> getDetails() {
        return details;
    }
}
```

### 7.3 PermanentCommandException

```java
package com.commandbus.exception;

import java.util.Map;

/**
 * Raised for non-retryable failures (validation, business rule violations).
 *
 * <p>When a handler throws this exception, the command immediately moves
 * to the troubleshooting queue without retrying.
 */
public class PermanentCommandException extends CommandBusException {

    private final String code;
    private final String errorMessage;
    private final Map<String, Object> details;

    public PermanentCommandException(String code, String message) {
        this(code, message, Map.of());
    }

    public PermanentCommandException(String code, String message, Map<String, Object> details) {
        super("[" + code + "] " + message);
        this.code = code;
        this.errorMessage = message;
        this.details = details != null ? Map.copyOf(details) : Map.of();
    }

    public String getCode() {
        return code;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public Map<String, Object> getDetails() {
        return details;
    }
}
```

### 7.4 Other Exceptions

```java
package com.commandbus.exception;

public class HandlerNotFoundException extends CommandBusException {
    private final String domain;
    private final String commandType;

    public HandlerNotFoundException(String domain, String commandType) {
        super("No handler registered for " + domain + "." + commandType);
        this.domain = domain;
        this.commandType = commandType;
    }

    public String getDomain() { return domain; }
    public String getCommandType() { return commandType; }
}

public class HandlerAlreadyRegisteredException extends CommandBusException {
    private final String domain;
    private final String commandType;

    public HandlerAlreadyRegisteredException(String domain, String commandType) {
        super("Handler already registered for " + domain + "." + commandType);
        this.domain = domain;
        this.commandType = commandType;
    }

    public String getDomain() { return domain; }
    public String getCommandType() { return commandType; }
}

public class DuplicateCommandException extends CommandBusException {
    private final String domain;
    private final String commandId;

    public DuplicateCommandException(String domain, String commandId) {
        super("Duplicate command_id " + commandId + " in domain " + domain);
        this.domain = domain;
        this.commandId = commandId;
    }

    public String getDomain() { return domain; }
    public String getCommandId() { return commandId; }
}

public class CommandNotFoundException extends CommandBusException {
    private final String domain;
    private final String commandId;

    public CommandNotFoundException(String domain, String commandId) {
        super("Command " + commandId + " not found in domain " + domain);
        this.domain = domain;
        this.commandId = commandId;
    }

    public String getDomain() { return domain; }
    public String getCommandId() { return commandId; }
}

public class BatchNotFoundException extends CommandBusException {
    private final String domain;
    private final String batchId;

    public BatchNotFoundException(String domain, String batchId) {
        super("Batch " + batchId + " not found in domain " + domain);
        this.domain = domain;
        this.batchId = batchId;
    }

    public String getDomain() { return domain; }
    public String getBatchId() { return batchId; }
}

public class InvalidOperationException extends CommandBusException {
    public InvalidOperationException(String message) {
        super(message);
    }
}
```

---

## 8. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| DM-1 | Command record is immutable | Compiler enforces immutability |
| DM-2 | Command validates required fields | Unit test throws on null domain/type/id |
| DM-3 | CommandMetadata can be created with defaults | Unit test |
| DM-4 | Enums serialize/deserialize correctly | JSON round-trip test |
| DM-5 | All records have proper equals/hashCode | Unit tests |
| DM-6 | HandlerContext.extendVisibility works | Unit test |
| DM-7 | Exception codes accessible via getters | Unit test |
| DM-8 | Reply factory methods work correctly | Unit test |
