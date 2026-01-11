# 10. Process Manager Module

This specification covers the process orchestration module for implementing long-running, multi-step workflows with typed state management and saga-style compensation.

## Overview

The process manager pattern enables:
- Multi-step workflow orchestration across multiple commands
- Typed state management with JSON serialization
- Saga-style compensation for failure recovery
- Integration with Troubleshooting Queue (TSQ) for human intervention
- Full audit trail of all steps and responses

## Domain Models

### ProcessStatus Enum

```java
package com.commandbus.process;

public enum ProcessStatus {
    /** Process created but not yet started */
    PENDING,

    /** Currently executing a step */
    IN_PROGRESS,

    /** Waiting for command reply */
    WAITING_FOR_REPLY,

    /** Command failed and is in TSQ awaiting operator action */
    WAITING_FOR_TSQ,

    /** Running compensation steps after failure */
    COMPENSATING,

    /** Process completed successfully */
    COMPLETED,

    /** All compensation steps completed */
    COMPENSATED,

    /** Process failed permanently (no compensation or compensation failed) */
    FAILED,

    /** Process was canceled by operator */
    CANCELED
}
```

### ProcessState Interface

```java
package com.commandbus.process;

import java.util.Map;

/**
 * Protocol for typed process state.
 *
 * Process state classes must implement toMap() and fromMap() for
 * JSON serialization to/from database storage.
 */
public interface ProcessState {

    /**
     * Serialize state to JSON-compatible map.
     */
    Map<String, Object> toMap();

    /**
     * Deserialize state from JSON-compatible map.
     * Implementations should provide a static factory method.
     */
    // static T fromMap(Map<String, Object> data);
}
```

### ProcessMetadata Record

```java
package com.commandbus.process;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Metadata for a process instance.
 *
 * @param <TState> The typed process state class
 * @param <TStep> The step enum type (must extend Enum)
 */
public record ProcessMetadata<TState extends ProcessState, TStep extends Enum<TStep>>(
    String domain,
    UUID processId,
    String processType,
    TState state,
    ProcessStatus status,
    TStep currentStep,
    Instant createdAt,
    Instant updatedAt,
    Instant completedAt,
    String errorCode,
    String errorMessage
) {
    /**
     * Create a new process in PENDING status.
     */
    public static <TState extends ProcessState, TStep extends Enum<TStep>>
    ProcessMetadata<TState, TStep> create(
            String domain,
            UUID processId,
            String processType,
            TState state) {
        Instant now = Instant.now();
        return new ProcessMetadata<>(
            domain,
            processId,
            processType,
            state,
            ProcessStatus.PENDING,
            null,           // currentStep
            now,            // createdAt
            now,            // updatedAt
            null,           // completedAt
            null,           // errorCode
            null            // errorMessage
        );
    }

    /**
     * Create updated copy with new status.
     */
    public ProcessMetadata<TState, TStep> withStatus(ProcessStatus newStatus) {
        return new ProcessMetadata<>(
            domain, processId, processType, state, newStatus, currentStep,
            createdAt, Instant.now(), completedAt, errorCode, errorMessage
        );
    }

    /**
     * Create updated copy with current step.
     */
    public ProcessMetadata<TState, TStep> withCurrentStep(TStep step) {
        return new ProcessMetadata<>(
            domain, processId, processType, state, status, step,
            createdAt, Instant.now(), completedAt, errorCode, errorMessage
        );
    }

    /**
     * Create updated copy with error information.
     */
    public ProcessMetadata<TState, TStep> withError(String code, String message) {
        return new ProcessMetadata<>(
            domain, processId, processType, state, status, currentStep,
            createdAt, Instant.now(), completedAt, code, message
        );
    }

    /**
     * Create updated copy marking completion.
     */
    public ProcessMetadata<TState, TStep> withCompletion(ProcessStatus finalStatus) {
        return new ProcessMetadata<>(
            domain, processId, processType, state, finalStatus, currentStep,
            createdAt, Instant.now(), Instant.now(), errorCode, errorMessage
        );
    }
}
```

### ProcessAuditEntry Record

```java
package com.commandbus.process;

import com.commandbus.domain.ReplyOutcome;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Audit trail entry for process step execution.
 */
public record ProcessAuditEntry(
    String stepName,
    UUID commandId,
    String commandType,
    Map<String, Object> commandData,
    Instant sentAt,
    ReplyOutcome replyOutcome,
    Map<String, Object> replyData,
    Instant receivedAt
) {
    /**
     * Create entry for command being sent.
     */
    public static ProcessAuditEntry forCommand(
            String stepName,
            UUID commandId,
            String commandType,
            Map<String, Object> commandData) {
        return new ProcessAuditEntry(
            stepName, commandId, commandType, commandData,
            Instant.now(), null, null, null
        );
    }

    /**
     * Create updated entry with reply information.
     */
    public ProcessAuditEntry withReply(ReplyOutcome outcome, Map<String, Object> data) {
        return new ProcessAuditEntry(
            stepName, commandId, commandType, commandData,
            sentAt, outcome, data, Instant.now()
        );
    }
}
```

### ProcessCommand Record

```java
package com.commandbus.process;

import java.util.Map;

/**
 * Typed wrapper for process command data.
 *
 * @param <TData> The command data type
 */
public record ProcessCommand<TData>(
    String commandType,
    TData data
) {
    /**
     * Convert to map for serialization.
     */
    public Map<String, Object> toMap() {
        Object dataValue = data;
        if (data instanceof ProcessState ps) {
            dataValue = ps.toMap();
        }
        return Map.of(
            "commandType", commandType,
            "data", dataValue
        );
    }
}
```

### ProcessResponse Record

```java
package com.commandbus.process;

import com.commandbus.domain.Reply;
import com.commandbus.domain.ReplyOutcome;
import java.util.Map;
import java.util.function.Function;

/**
 * Typed wrapper for command response data.
 *
 * @param <TResult> The result data type
 */
public record ProcessResponse<TResult>(
    ReplyOutcome outcome,
    TResult result,
    String errorCode,
    String errorMessage
) {
    /**
     * Create from a Reply object with type conversion.
     */
    public static <TResult> ProcessResponse<TResult> fromReply(
            Reply reply,
            Function<Map<String, Object>, TResult> resultMapper) {
        TResult result = null;
        if (reply.data() != null) {
            result = resultMapper.apply(reply.data());
        }
        return new ProcessResponse<>(
            reply.outcome(),
            result,
            reply.errorCode(),
            reply.errorMessage()
        );
    }

    /**
     * Check if response indicates success.
     */
    public boolean isSuccess() {
        return outcome == ReplyOutcome.SUCCESS;
    }

    /**
     * Check if response indicates failure.
     */
    public boolean isFailed() {
        return outcome == ReplyOutcome.FAILED;
    }
}
```

---

## Process Repository

### ProcessRepository Interface

```java
package com.commandbus.process;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Repository for process persistence.
 */
public interface ProcessRepository {

    /**
     * Save a new process.
     */
    void save(ProcessMetadata<?, ?> process);

    /**
     * Save a new process within an existing transaction.
     */
    void save(ProcessMetadata<?, ?> process, JdbcTemplate jdbcTemplate);

    /**
     * Update existing process.
     */
    void update(ProcessMetadata<?, ?> process);

    /**
     * Update existing process within an existing transaction.
     */
    void update(ProcessMetadata<?, ?> process, JdbcTemplate jdbcTemplate);

    /**
     * Get process by ID.
     */
    Optional<ProcessMetadata<?, ?>> getById(String domain, UUID processId);

    /**
     * Get process by ID within an existing transaction.
     */
    Optional<ProcessMetadata<?, ?>> getById(String domain, UUID processId, JdbcTemplate jdbcTemplate);

    /**
     * Find processes by status.
     */
    List<ProcessMetadata<?, ?>> findByStatus(String domain, List<ProcessStatus> statuses);

    /**
     * Find processes by type.
     */
    List<ProcessMetadata<?, ?>> findByType(String domain, String processType);

    /**
     * Log a step execution to audit trail.
     */
    void logStep(String domain, UUID processId, ProcessAuditEntry entry);

    /**
     * Log a step execution within an existing transaction.
     */
    void logStep(String domain, UUID processId, ProcessAuditEntry entry, JdbcTemplate jdbcTemplate);

    /**
     * Update step with reply information.
     */
    void updateStepReply(String domain, UUID processId, UUID commandId, ProcessAuditEntry entry);

    /**
     * Update step with reply within an existing transaction.
     */
    void updateStepReply(String domain, UUID processId, UUID commandId, ProcessAuditEntry entry,
                         JdbcTemplate jdbcTemplate);

    /**
     * Get full audit trail for a process.
     */
    List<ProcessAuditEntry> getAuditTrail(String domain, UUID processId);

    /**
     * Get list of completed step names (for compensation).
     */
    List<String> getCompletedSteps(String domain, UUID processId);

    /**
     * Get list of completed step names within an existing transaction.
     */
    List<String> getCompletedSteps(String domain, UUID processId, JdbcTemplate jdbcTemplate);
}
```

### JdbcProcessRepository Implementation

```java
package com.commandbus.process;

import com.commandbus.domain.ReplyOutcome;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

@Repository
public class JdbcProcessRepository implements ProcessRepository {

    private static final Logger log = LoggerFactory.getLogger(JdbcProcessRepository.class);

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public JdbcProcessRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    @Transactional
    public void save(ProcessMetadata<?, ?> process) {
        save(process, jdbcTemplate);
    }

    @Override
    public void save(ProcessMetadata<?, ?> process, JdbcTemplate jdbc) {
        String sql = """
            INSERT INTO commandbus.process (
                domain, process_id, process_type, status, current_step,
                state, error_code, error_message,
                created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?)
            """;

        jdbc.update(sql,
            process.domain(),
            process.processId(),
            process.processType(),
            process.status().name(),
            process.currentStep() != null ? process.currentStep().name() : null,
            serializeState(process.state()),
            process.errorCode(),
            process.errorMessage(),
            Timestamp.from(process.createdAt()),
            Timestamp.from(process.updatedAt()),
            process.completedAt() != null ? Timestamp.from(process.completedAt()) : null
        );

        log.debug("Saved process {}.{}", process.domain(), process.processId());
    }

    @Override
    @Transactional
    public void update(ProcessMetadata<?, ?> process) {
        update(process, jdbcTemplate);
    }

    @Override
    public void update(ProcessMetadata<?, ?> process, JdbcTemplate jdbc) {
        String sql = """
            UPDATE commandbus.process SET
                status = ?,
                current_step = ?,
                state = ?::jsonb,
                error_code = ?,
                error_message = ?,
                updated_at = NOW(),
                completed_at = ?
            WHERE domain = ? AND process_id = ?
            """;

        jdbc.update(sql,
            process.status().name(),
            process.currentStep() != null ? process.currentStep().name() : null,
            serializeState(process.state()),
            process.errorCode(),
            process.errorMessage(),
            process.completedAt() != null ? Timestamp.from(process.completedAt()) : null,
            process.domain(),
            process.processId()
        );
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<ProcessMetadata<?, ?>> getById(String domain, UUID processId) {
        return getById(domain, processId, jdbcTemplate);
    }

    @Override
    public Optional<ProcessMetadata<?, ?>> getById(String domain, UUID processId, JdbcTemplate jdbc) {
        String sql = """
            SELECT domain, process_id, process_type, status, current_step,
                   state, error_code, error_message,
                   created_at, updated_at, completed_at
            FROM commandbus.process
            WHERE domain = ? AND process_id = ?
            """;

        List<ProcessMetadata<?, ?>> results = jdbc.query(sql, new ProcessMetadataRowMapper(), domain, processId);
        return results.isEmpty() ? Optional.empty() : Optional.of(results.get(0));
    }

    @Override
    @Transactional(readOnly = true)
    public List<ProcessMetadata<?, ?>> findByStatus(String domain, List<ProcessStatus> statuses) {
        String placeholders = String.join(",", statuses.stream().map(s -> "?").toList());
        String sql = """
            SELECT domain, process_id, process_type, status, current_step,
                   state, error_code, error_message,
                   created_at, updated_at, completed_at
            FROM commandbus.process
            WHERE domain = ? AND status IN (%s)
            ORDER BY created_at DESC
            """.formatted(placeholders);

        Object[] params = new Object[statuses.size() + 1];
        params[0] = domain;
        for (int i = 0; i < statuses.size(); i++) {
            params[i + 1] = statuses.get(i).name();
        }

        return jdbcTemplate.query(sql, new ProcessMetadataRowMapper(), params);
    }

    @Override
    @Transactional(readOnly = true)
    public List<ProcessMetadata<?, ?>> findByType(String domain, String processType) {
        String sql = """
            SELECT domain, process_id, process_type, status, current_step,
                   state, error_code, error_message,
                   created_at, updated_at, completed_at
            FROM commandbus.process
            WHERE domain = ? AND process_type = ?
            ORDER BY created_at DESC
            """;

        return jdbcTemplate.query(sql, new ProcessMetadataRowMapper(), domain, processType);
    }

    @Override
    @Transactional
    public void logStep(String domain, UUID processId, ProcessAuditEntry entry) {
        logStep(domain, processId, entry, jdbcTemplate);
    }

    @Override
    public void logStep(String domain, UUID processId, ProcessAuditEntry entry, JdbcTemplate jdbc) {
        String sql = """
            INSERT INTO commandbus.process_audit (
                domain, process_id, step_name, command_id, command_type,
                command_data, sent_at, reply_outcome, reply_data, received_at
            ) VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?::jsonb, ?)
            """;

        jdbc.update(sql,
            domain,
            processId,
            entry.stepName(),
            entry.commandId(),
            entry.commandType(),
            serializeMap(entry.commandData()),
            Timestamp.from(entry.sentAt()),
            entry.replyOutcome() != null ? entry.replyOutcome().name() : null,
            serializeMap(entry.replyData()),
            entry.receivedAt() != null ? Timestamp.from(entry.receivedAt()) : null
        );
    }

    @Override
    @Transactional
    public void updateStepReply(String domain, UUID processId, UUID commandId, ProcessAuditEntry entry) {
        updateStepReply(domain, processId, commandId, entry, jdbcTemplate);
    }

    @Override
    public void updateStepReply(String domain, UUID processId, UUID commandId,
                                ProcessAuditEntry entry, JdbcTemplate jdbc) {
        String sql = """
            UPDATE commandbus.process_audit SET
                reply_outcome = ?,
                reply_data = ?::jsonb,
                received_at = ?
            WHERE domain = ? AND process_id = ? AND command_id = ?
            """;

        jdbc.update(sql,
            entry.replyOutcome() != null ? entry.replyOutcome().name() : null,
            serializeMap(entry.replyData()),
            entry.receivedAt() != null ? Timestamp.from(entry.receivedAt()) : null,
            domain,
            processId,
            commandId
        );
    }

    @Override
    @Transactional(readOnly = true)
    public List<ProcessAuditEntry> getAuditTrail(String domain, UUID processId) {
        String sql = """
            SELECT step_name, command_id, command_type, command_data,
                   sent_at, reply_outcome, reply_data, received_at
            FROM commandbus.process_audit
            WHERE domain = ? AND process_id = ?
            ORDER BY sent_at ASC
            """;

        return jdbcTemplate.query(sql, new ProcessAuditEntryRowMapper(), domain, processId);
    }

    @Override
    @Transactional(readOnly = true)
    public List<String> getCompletedSteps(String domain, UUID processId) {
        return getCompletedSteps(domain, processId, jdbcTemplate);
    }

    @Override
    public List<String> getCompletedSteps(String domain, UUID processId, JdbcTemplate jdbc) {
        String sql = """
            SELECT step_name
            FROM commandbus.process_audit
            WHERE domain = ? AND process_id = ? AND reply_outcome = 'SUCCESS'
            ORDER BY sent_at ASC
            """;

        return jdbc.queryForList(sql, String.class, domain, processId);
    }

    private String serializeState(ProcessState state) {
        if (state == null) return "{}";
        try {
            return objectMapper.writeValueAsString(state.toMap());
        } catch (Exception e) {
            throw new RuntimeException("Failed to serialize process state", e);
        }
    }

    private String serializeMap(Map<String, Object> map) {
        if (map == null) return null;
        try {
            return objectMapper.writeValueAsString(map);
        } catch (Exception e) {
            throw new RuntimeException("Failed to serialize map", e);
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> deserializeJson(String json) {
        if (json == null) return null;
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            throw new RuntimeException("Failed to deserialize JSON", e);
        }
    }

    private class ProcessMetadataRowMapper implements RowMapper<ProcessMetadata<?, ?>> {
        @Override
        @SuppressWarnings("unchecked")
        public ProcessMetadata<?, ?> mapRow(ResultSet rs, int rowNum) throws SQLException {
            // Note: State is returned as Map, needs to be converted by caller
            Map<String, Object> stateMap = deserializeJson(rs.getString("state"));

            // Create a simple ProcessState wrapper for the raw map
            ProcessState state = new MapProcessState(stateMap);

            Timestamp completedAt = rs.getTimestamp("completed_at");

            return new ProcessMetadata<>(
                rs.getString("domain"),
                UUID.fromString(rs.getString("process_id")),
                rs.getString("process_type"),
                state,
                ProcessStatus.valueOf(rs.getString("status")),
                null,  // currentStep - needs to be cast by caller using step enum
                rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("updated_at").toInstant(),
                completedAt != null ? completedAt.toInstant() : null,
                rs.getString("error_code"),
                rs.getString("error_message")
            );
        }
    }

    private class ProcessAuditEntryRowMapper implements RowMapper<ProcessAuditEntry> {
        @Override
        public ProcessAuditEntry mapRow(ResultSet rs, int rowNum) throws SQLException {
            String outcomeStr = rs.getString("reply_outcome");
            Timestamp receivedAt = rs.getTimestamp("received_at");

            return new ProcessAuditEntry(
                rs.getString("step_name"),
                UUID.fromString(rs.getString("command_id")),
                rs.getString("command_type"),
                deserializeJson(rs.getString("command_data")),
                rs.getTimestamp("sent_at").toInstant(),
                outcomeStr != null ? ReplyOutcome.valueOf(outcomeStr) : null,
                deserializeJson(rs.getString("reply_data")),
                receivedAt != null ? receivedAt.toInstant() : null
            );
        }
    }

    /**
     * Simple ProcessState wrapper for deserialized map data.
     */
    private record MapProcessState(Map<String, Object> data) implements ProcessState {
        @Override
        public Map<String, Object> toMap() {
            return data;
        }
    }
}
```

---

## Base Process Manager

### BaseProcessManager Abstract Class

```java
package com.commandbus.process;

import com.commandbus.CommandBus;
import com.commandbus.domain.Reply;
import com.commandbus.domain.ReplyOutcome;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Base class for implementing process managers with typed state and steps.
 *
 * @param <TState> The typed process state class
 * @param <TStep> The step enum type
 */
public abstract class BaseProcessManager<TState extends ProcessState, TStep extends Enum<TStep>> {

    private static final Logger log = LoggerFactory.getLogger(BaseProcessManager.class);

    protected final CommandBus commandBus;
    protected final ProcessRepository processRepo;
    protected final String replyQueue;
    protected final JdbcTemplate jdbcTemplate;
    protected final TransactionTemplate transactionTemplate;

    protected BaseProcessManager(
            CommandBus commandBus,
            ProcessRepository processRepo,
            String replyQueue,
            JdbcTemplate jdbcTemplate,
            TransactionTemplate transactionTemplate) {
        this.commandBus = commandBus;
        this.processRepo = processRepo;
        this.replyQueue = replyQueue;
        this.jdbcTemplate = jdbcTemplate;
        this.transactionTemplate = transactionTemplate;
    }

    // ========== Abstract Methods (Template Pattern) ==========

    /**
     * Return unique process type identifier.
     */
    public abstract String getProcessType();

    /**
     * Return the domain this process operates in.
     */
    public abstract String getDomain();

    /**
     * Return the class used for state to enable deserialization.
     */
    public abstract Class<TState> getStateClass();

    /**
     * Return the step enum class for deserialization.
     */
    public abstract Class<TStep> getStepClass();

    /**
     * Create typed state from initial input data.
     */
    public abstract TState createInitialState(Map<String, Object> initialData);

    /**
     * Determine the first step based on initial state.
     */
    public abstract TStep getFirstStep(TState state);

    /**
     * Build typed command for a step.
     */
    public abstract ProcessCommand<?> buildCommand(TStep step, TState state);

    /**
     * Update state with data from reply.
     * Should mutate the state object directly or return new state.
     */
    public abstract TState updateState(TState state, TStep step, Reply reply);

    /**
     * Determine next step based on reply and state.
     *
     * @return Next step to execute, or null if process is complete
     */
    public abstract TStep getNextStep(TStep currentStep, Reply reply, TState state);

    // ========== Optional Override Methods ==========

    /**
     * Get compensation step for a given step.
     * Override to provide compensation mapping for saga pattern.
     *
     * @return Compensation step, or null if no compensation needed
     */
    public TStep getCompensationStep(TStep step) {
        return null;
    }

    /**
     * Hook called before sending command.
     * Override to perform side effects or state mutations.
     */
    protected void beforeSendCommand(
            ProcessMetadata<TState, TStep> process,
            TStep step,
            UUID commandId,
            Map<String, Object> commandPayload,
            JdbcTemplate jdbc) {
        // Default: no-op
    }

    // ========== Public API ==========

    /**
     * Start a new process instance.
     *
     * @param initialData Initial state data for the process
     * @return The process_id (UUID) of the new process
     */
    public UUID start(Map<String, Object> initialData) {
        return transactionTemplate.execute(status -> {
            UUID processId = UUID.randomUUID();
            TState state = createInitialState(initialData);

            ProcessMetadata<TState, TStep> process = ProcessMetadata.create(
                getDomain(),
                processId,
                getProcessType(),
                state
            );

            processRepo.save(process, jdbcTemplate);

            TStep firstStep = getFirstStep(state);
            executeStep(process, firstStep, jdbcTemplate);

            return processId;
        });
    }

    /**
     * Handle incoming reply and advance process.
     */
    public void handleReply(Reply reply, ProcessMetadata<?, ?> rawProcess) {
        transactionTemplate.executeWithoutResult(status -> {
            handleReplyInternal(reply, rawProcess, jdbcTemplate);
        });
    }

    /**
     * Handle incoming reply within an existing transaction.
     */
    public void handleReply(Reply reply, ProcessMetadata<?, ?> rawProcess, JdbcTemplate jdbc) {
        handleReplyInternal(reply, rawProcess, jdbc);
    }

    // ========== Internal Implementation ==========

    @SuppressWarnings("unchecked")
    private void handleReplyInternal(Reply reply, ProcessMetadata<?, ?> rawProcess, JdbcTemplate jdbc) {
        // Deserialize state if needed
        TState state;
        if (rawProcess.state() instanceof Map) {
            state = deserializeState((Map<String, Object>) rawProcess.state());
        } else {
            state = (TState) rawProcess.state();
        }

        // Deserialize current step
        TStep currentStep = rawProcess.currentStep() != null
            ? Enum.valueOf(getStepClass(), rawProcess.currentStep().toString())
            : null;

        ProcessMetadata<TState, TStep> process = new ProcessMetadata<>(
            rawProcess.domain(),
            rawProcess.processId(),
            rawProcess.processType(),
            state,
            rawProcess.status(),
            currentStep,
            rawProcess.createdAt(),
            rawProcess.updatedAt(),
            rawProcess.completedAt(),
            rawProcess.errorCode(),
            rawProcess.errorMessage()
        );

        // Record reply in audit log
        recordReply(process, reply, jdbc);

        // Handle cancellation from TSQ - trigger compensation
        if (reply.outcome() == ReplyOutcome.CANCELED) {
            log.info("Process {} command canceled in TSQ, running compensations", process.processId());
            runCompensations(process, jdbc);
            return;
        }

        if (currentStep == null) {
            log.error("Received reply for process {} with no current step", process.processId());
            return;
        }

        // Update state
        TState updatedState = updateState(state, currentStep, reply);
        ProcessMetadata<TState, TStep> updatedProcess = new ProcessMetadata<>(
            process.domain(),
            process.processId(),
            process.processType(),
            updatedState,
            process.status(),
            currentStep,
            process.createdAt(),
            Instant.now(),
            process.completedAt(),
            process.errorCode(),
            process.errorMessage()
        );

        // Handle failure (goes to TSQ, wait for operator)
        if (reply.outcome() == ReplyOutcome.FAILED) {
            handleFailure(updatedProcess, reply, jdbc);
            return;
        }

        // Determine next step
        TStep nextStep = getNextStep(currentStep, reply, updatedState);

        if (nextStep == null) {
            completeProcess(updatedProcess, jdbc);
        } else {
            executeStep(updatedProcess, nextStep, jdbc);
        }
    }

    private void executeStep(ProcessMetadata<TState, TStep> process, TStep step, JdbcTemplate jdbc) {
        ProcessCommand<?> command = buildCommand(step, process.state());
        UUID commandId = UUID.randomUUID();

        Map<String, Object> commandPayload = convertToMap(command.data());

        beforeSendCommand(process, step, commandId, commandPayload, jdbc);

        commandBus.send(
            getDomain(),
            command.commandType(),
            commandId,
            commandPayload,
            process.processId(),  // correlationId
            replyQueue,
            jdbc
        );

        ProcessMetadata<TState, TStep> updated = new ProcessMetadata<>(
            process.domain(),
            process.processId(),
            process.processType(),
            process.state(),
            ProcessStatus.WAITING_FOR_REPLY,
            step,
            process.createdAt(),
            Instant.now(),
            process.completedAt(),
            process.errorCode(),
            process.errorMessage()
        );

        // Record in audit log
        recordCommand(process, step, commandId, command.commandType(), commandPayload, jdbc);
        processRepo.update(updated, jdbc);

        log.debug("Process {} executing step {} with command {}",
            process.processId(), step, commandId);
    }

    private void runCompensations(ProcessMetadata<TState, TStep> process, JdbcTemplate jdbc) {
        List<String> completedSteps = processRepo.getCompletedSteps(
            process.domain(), process.processId(), jdbc);

        // Run compensations in reverse order
        for (int i = completedSteps.size() - 1; i >= 0; i--) {
            String stepName = completedSteps.get(i);
            TStep step = Enum.valueOf(getStepClass(), stepName);
            TStep compStep = getCompensationStep(step);

            if (compStep != null) {
                ProcessMetadata<TState, TStep> updated = new ProcessMetadata<>(
                    process.domain(),
                    process.processId(),
                    process.processType(),
                    process.state(),
                    ProcessStatus.COMPENSATING,
                    compStep,
                    process.createdAt(),
                    Instant.now(),
                    process.completedAt(),
                    process.errorCode(),
                    process.errorMessage()
                );
                processRepo.update(updated, jdbc);

                executeStep(updated, compStep, jdbc);
                // Note: Reply router will call handleReply for compensation replies
            }
        }

        // Mark as compensated
        ProcessMetadata<TState, TStep> compensated = process.withCompletion(ProcessStatus.COMPENSATED);
        processRepo.update(compensated, jdbc);

        log.info("Process {} compensation completed", process.processId());
    }

    private void completeProcess(ProcessMetadata<TState, TStep> process, JdbcTemplate jdbc) {
        ProcessMetadata<TState, TStep> completed = process.withCompletion(ProcessStatus.COMPLETED);
        processRepo.update(completed, jdbc);
        log.info("Process {} completed successfully", process.processId());
    }

    private void handleFailure(ProcessMetadata<TState, TStep> process, Reply reply, JdbcTemplate jdbc) {
        ProcessMetadata<TState, TStep> failed = new ProcessMetadata<>(
            process.domain(),
            process.processId(),
            process.processType(),
            process.state(),
            ProcessStatus.WAITING_FOR_TSQ,
            process.currentStep(),
            process.createdAt(),
            Instant.now(),
            process.completedAt(),
            reply.errorCode(),
            reply.errorMessage()
        );
        processRepo.update(failed, jdbc);
        log.warn("Process {} step {} failed, waiting for TSQ intervention",
            process.processId(), process.currentStep());
    }

    private void recordCommand(
            ProcessMetadata<TState, TStep> process,
            TStep step,
            UUID commandId,
            String commandType,
            Map<String, Object> commandData,
            JdbcTemplate jdbc) {
        ProcessAuditEntry entry = ProcessAuditEntry.forCommand(
            step.name(), commandId, commandType, commandData);
        processRepo.logStep(process.domain(), process.processId(), entry, jdbc);
    }

    private void recordReply(ProcessMetadata<TState, TStep> process, Reply reply, JdbcTemplate jdbc) {
        ProcessAuditEntry entry = new ProcessAuditEntry(
            process.currentStep() != null ? process.currentStep().name() : "",
            reply.commandId(),
            "",  // Will be looked up
            null,
            Instant.now(),  // Will be preserved
            reply.outcome(),
            reply.data(),
            Instant.now()
        );
        processRepo.updateStepReply(process.domain(), process.processId(), reply.commandId(), entry, jdbc);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> convertToMap(Object data) {
        if (data instanceof ProcessState ps) {
            return ps.toMap();
        }
        if (data instanceof Map) {
            return (Map<String, Object>) data;
        }
        throw new IllegalArgumentException("Cannot convert data to map: " + data.getClass());
    }

    private TState deserializeState(Map<String, Object> data) {
        // Use reflection to call static fromMap method
        try {
            var method = getStateClass().getMethod("fromMap", Map.class);
            return getStateClass().cast(method.invoke(null, data));
        } catch (Exception e) {
            throw new RuntimeException("Failed to deserialize state", e);
        }
    }
}
```

---

## Process Reply Router

### ProcessReplyRouter Class

```java
package com.commandbus.process;

import com.commandbus.domain.Reply;
import com.commandbus.domain.ReplyOutcome;
import com.commandbus.pgmq.PgmqClient;
import com.commandbus.pgmq.PgmqMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Routes replies from process queue to appropriate process managers.
 *
 * Implements a high-concurrency worker pattern using virtual threads,
 * semaphores and pg_notify for efficient throughput.
 */
public class ProcessReplyRouter {

    private static final Logger log = LoggerFactory.getLogger(ProcessReplyRouter.class);
    private static final String PGMQ_NOTIFY_CHANNEL = "pgmq_new_message";

    private final DataSource dataSource;
    private final JdbcTemplate jdbcTemplate;
    private final TransactionTemplate transactionTemplate;
    private final ProcessRepository processRepo;
    private final Map<String, BaseProcessManager<?, ?>> managers;
    private final PgmqClient pgmqClient;
    private final String replyQueue;
    private final String domain;
    private final int visibilityTimeout;

    private final AtomicBoolean running = new AtomicBoolean(false);
    private ExecutorService executor;
    private final CopyOnWriteArrayList<Future<?>> inFlight = new CopyOnWriteArrayList<>();

    public ProcessReplyRouter(
            DataSource dataSource,
            JdbcTemplate jdbcTemplate,
            TransactionTemplate transactionTemplate,
            ProcessRepository processRepo,
            Map<String, BaseProcessManager<?, ?>> managers,
            PgmqClient pgmqClient,
            String replyQueue,
            String domain,
            int visibilityTimeout) {
        this.dataSource = dataSource;
        this.jdbcTemplate = jdbcTemplate;
        this.transactionTemplate = transactionTemplate;
        this.processRepo = processRepo;
        this.managers = managers;
        this.pgmqClient = pgmqClient;
        this.replyQueue = replyQueue;
        this.domain = domain;
        this.visibilityTimeout = visibilityTimeout;
    }

    public boolean isRunning() {
        return running.get();
    }

    public String getReplyQueue() {
        return replyQueue;
    }

    public String getDomain() {
        return domain;
    }

    /**
     * Start the router with specified concurrency.
     */
    public void start(int concurrency, long pollIntervalMs, boolean useNotify) {
        if (!running.compareAndSet(false, true)) {
            throw new IllegalStateException("Router already running");
        }

        executor = Executors.newVirtualThreadPerTaskExecutor();
        Semaphore semaphore = new Semaphore(concurrency);

        log.info("Starting process reply router on {} (concurrency={})", replyQueue, concurrency);

        executor.submit(() -> {
            try {
                if (useNotify) {
                    runWithNotify(semaphore, pollIntervalMs);
                } else {
                    runWithPolling(semaphore, pollIntervalMs);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                log.info("Reply router interrupted");
            } catch (Exception e) {
                log.error("Reply router crashed", e);
                throw new RuntimeException(e);
            } finally {
                running.set(false);
                log.info("Reply router stopped");
            }
        });
    }

    /**
     * Stop the router gracefully.
     */
    public void stop(long timeoutMs) throws InterruptedException {
        if (!running.compareAndSet(true, false)) {
            return;
        }

        log.info("Stopping reply router...");

        if (!inFlight.isEmpty()) {
            log.info("Waiting for {} in-flight replies...", inFlight.size());

            long deadline = System.currentTimeMillis() + timeoutMs;
            for (Future<?> future : inFlight) {
                long remaining = deadline - System.currentTimeMillis();
                if (remaining <= 0) {
                    log.warn("Timeout waiting for in-flight replies");
                    break;
                }
                try {
                    future.get(remaining, TimeUnit.MILLISECONDS);
                } catch (TimeoutException | ExecutionException e) {
                    // Ignore
                }
            }
        }

        if (executor != null) {
            executor.shutdownNow();
            executor.awaitTermination(5, TimeUnit.SECONDS);
        }
    }

    private void runWithNotify(Semaphore semaphore, long pollIntervalMs)
            throws SQLException, InterruptedException {
        try (Connection listenConn = dataSource.getConnection()) {
            listenConn.setAutoCommit(true);
            String channel = PGMQ_NOTIFY_CHANNEL + "_" + replyQueue;

            try (var stmt = listenConn.createStatement()) {
                stmt.execute("LISTEN " + channel);
            }
            log.debug("Listening on channel {}", channel);

            var pgConn = listenConn.unwrap(org.postgresql.PGConnection.class);

            while (running.get()) {
                drainQueue(semaphore);
                if (!running.get()) return;

                // Wait for notification or timeout
                var notifications = pgConn.getNotifications((int) pollIntervalMs);
                // Process continues on notification or timeout
            }
        }
    }

    private void runWithPolling(Semaphore semaphore, long pollIntervalMs)
            throws InterruptedException {
        while (running.get()) {
            drainQueue(semaphore);
            if (!running.get()) return;

            Thread.sleep(pollIntervalMs);
        }
    }

    private void drainQueue(Semaphore semaphore) {
        while (running.get()) {
            int availableSlots = semaphore.availablePermits();
            if (availableSlots == 0) {
                waitForSlot();
                continue;
            }

            // Read messages
            List<PgmqMessage> messages = pgmqClient.read(
                replyQueue,
                visibilityTimeout,
                availableSlots
            );

            if (messages.isEmpty()) {
                return;
            }

            for (PgmqMessage msg : messages) {
                Future<?> future = executor.submit(() -> {
                    try {
                        semaphore.acquire();
                        try {
                            processMessage(msg);
                        } finally {
                            semaphore.release();
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    } catch (Exception e) {
                        log.error("Error processing reply message {}", msg.msgId(), e);
                    }
                });
                inFlight.add(future);
                future.whenComplete((result, error) -> inFlight.remove(future));
            }
        }
    }

    private void waitForSlot() {
        if (inFlight.isEmpty()) return;

        try {
            // Wait for any task to complete
            CompletableFuture.anyOf(
                inFlight.stream()
                    .map(f -> CompletableFuture.supplyAsync(() -> {
                        try {
                            f.get();
                        } catch (Exception e) {
                            // Ignore
                        }
                        return null;
                    }))
                    .toArray(CompletableFuture[]::new)
            ).get(1, TimeUnit.SECONDS);
        } catch (Exception e) {
            // Timeout or error, continue
        }
    }

    @SuppressWarnings("unchecked")
    private void processMessage(PgmqMessage msg) {
        transactionTemplate.executeWithoutResult(status -> {
            dispatchReply(msg);
        });
    }

    @SuppressWarnings("unchecked")
    private void dispatchReply(PgmqMessage msg) {
        long msgId = msg.msgId();
        Map<String, Object> message = msg.message();

        Reply reply = new Reply(
            UUID.fromString((String) message.get("command_id")),
            message.get("correlation_id") != null
                ? UUID.fromString((String) message.get("correlation_id"))
                : null,
            ReplyOutcome.valueOf((String) message.get("outcome")),
            (Map<String, Object>) message.get("result"),
            (String) message.get("error_code"),
            (String) message.get("error_message")
        );

        if (reply.correlationId() == null) {
            log.warn("Reply {} has no correlation_id, discarding", msgId);
            pgmqClient.delete(replyQueue, msgId, jdbcTemplate);
            return;
        }

        // Look up process by correlation_id (which is process_id)
        Optional<ProcessMetadata<?, ?>> processOpt = processRepo.getById(
            domain,
            reply.correlationId(),
            jdbcTemplate
        );

        if (processOpt.isEmpty()) {
            log.warn("Reply for unknown process {}, discarding", reply.correlationId());
            pgmqClient.delete(replyQueue, msgId, jdbcTemplate);
            return;
        }

        ProcessMetadata<?, ?> process = processOpt.get();
        BaseProcessManager<?, ?> manager = managers.get(process.processType());

        if (manager == null) {
            log.error("No manager for process type {}, discarding", process.processType());
            pgmqClient.delete(replyQueue, msgId, jdbcTemplate);
            return;
        }

        // Dispatch to manager
        manager.handleReply(reply, process, jdbcTemplate);

        // Delete message (atomically with process update)
        pgmqClient.delete(replyQueue, msgId, jdbcTemplate);

        log.debug("Processed reply for process {} step {}",
            process.processId(), process.currentStep());
    }
}
```

---

## Database Schema

The process module requires these tables (from `V003__process_manager_schema.sql`):

```sql
-- Process instance table
CREATE TABLE commandbus.process (
    domain VARCHAR(255) NOT NULL,
    process_id UUID NOT NULL,
    process_type VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    current_step VARCHAR(255),
    state JSONB NOT NULL DEFAULT '{}',
    error_code VARCHAR(255),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    PRIMARY KEY (domain, process_id)
);

CREATE INDEX idx_process_type ON commandbus.process(domain, process_type);
CREATE INDEX idx_process_status ON commandbus.process(domain, status);
CREATE INDEX idx_process_created ON commandbus.process(created_at);

-- Process audit trail table
CREATE TABLE commandbus.process_audit (
    id BIGSERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    process_id UUID NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    command_id UUID NOT NULL,
    command_type VARCHAR(255) NOT NULL,
    command_data JSONB,
    sent_at TIMESTAMPTZ NOT NULL,
    reply_outcome VARCHAR(50),
    reply_data JSONB,
    received_at TIMESTAMPTZ,

    FOREIGN KEY (domain, process_id) REFERENCES commandbus.process(domain, process_id)
);

CREATE INDEX idx_process_audit_process ON commandbus.process_audit(domain, process_id);
CREATE INDEX idx_process_audit_command ON commandbus.process_audit(command_id);
```

---

## Usage Example

### Order Fulfillment Process

```java
// Step enum
public enum OrderStep {
    RESERVE_INVENTORY,
    PROCESS_PAYMENT,
    SHIP_ORDER,
    // Compensation steps
    RELEASE_INVENTORY,
    REFUND_PAYMENT
}

// Process state
public record OrderState(
    String orderId,
    String customerId,
    List<OrderItem> items,
    BigDecimal totalAmount,
    String reservationId,
    String paymentId,
    String shipmentId
) implements ProcessState {

    @Override
    public Map<String, Object> toMap() {
        return Map.of(
            "orderId", orderId,
            "customerId", customerId,
            "items", items.stream().map(OrderItem::toMap).toList(),
            "totalAmount", totalAmount.toString(),
            "reservationId", reservationId != null ? reservationId : "",
            "paymentId", paymentId != null ? paymentId : "",
            "shipmentId", shipmentId != null ? shipmentId : ""
        );
    }

    public static OrderState fromMap(Map<String, Object> data) {
        // Deserialization logic
        return new OrderState(...);
    }

    public OrderState withReservationId(String id) {
        return new OrderState(orderId, customerId, items, totalAmount, id, paymentId, shipmentId);
    }

    public OrderState withPaymentId(String id) {
        return new OrderState(orderId, customerId, items, totalAmount, reservationId, id, shipmentId);
    }

    public OrderState withShipmentId(String id) {
        return new OrderState(orderId, customerId, items, totalAmount, reservationId, paymentId, id);
    }
}

// Process manager implementation
@Component
public class OrderFulfillmentProcess extends BaseProcessManager<OrderState, OrderStep> {

    public OrderFulfillmentProcess(
            CommandBus commandBus,
            ProcessRepository processRepo,
            JdbcTemplate jdbcTemplate,
            TransactionTemplate transactionTemplate) {
        super(commandBus, processRepo, "order_replies", jdbcTemplate, transactionTemplate);
    }

    @Override
    public String getProcessType() {
        return "ORDER_FULFILLMENT";
    }

    @Override
    public String getDomain() {
        return "orders";
    }

    @Override
    public Class<OrderState> getStateClass() {
        return OrderState.class;
    }

    @Override
    public Class<OrderStep> getStepClass() {
        return OrderStep.class;
    }

    @Override
    public OrderState createInitialState(Map<String, Object> initialData) {
        return new OrderState(
            (String) initialData.get("orderId"),
            (String) initialData.get("customerId"),
            parseItems(initialData.get("items")),
            new BigDecimal((String) initialData.get("totalAmount")),
            null, null, null
        );
    }

    @Override
    public OrderStep getFirstStep(OrderState state) {
        return OrderStep.RESERVE_INVENTORY;
    }

    @Override
    public ProcessCommand<?> buildCommand(OrderStep step, OrderState state) {
        return switch (step) {
            case RESERVE_INVENTORY -> new ProcessCommand<>(
                "ReserveInventory",
                Map.of("orderId", state.orderId(), "items", state.items())
            );
            case PROCESS_PAYMENT -> new ProcessCommand<>(
                "ProcessPayment",
                Map.of(
                    "orderId", state.orderId(),
                    "customerId", state.customerId(),
                    "amount", state.totalAmount()
                )
            );
            case SHIP_ORDER -> new ProcessCommand<>(
                "ShipOrder",
                Map.of("orderId", state.orderId(), "reservationId", state.reservationId())
            );
            case RELEASE_INVENTORY -> new ProcessCommand<>(
                "ReleaseInventory",
                Map.of("reservationId", state.reservationId())
            );
            case REFUND_PAYMENT -> new ProcessCommand<>(
                "RefundPayment",
                Map.of("paymentId", state.paymentId())
            );
        };
    }

    @Override
    public OrderState updateState(OrderState state, OrderStep step, Reply reply) {
        if (reply.outcome() != ReplyOutcome.SUCCESS) {
            return state;
        }

        return switch (step) {
            case RESERVE_INVENTORY -> state.withReservationId(
                (String) reply.data().get("reservationId")
            );
            case PROCESS_PAYMENT -> state.withPaymentId(
                (String) reply.data().get("paymentId")
            );
            case SHIP_ORDER -> state.withShipmentId(
                (String) reply.data().get("shipmentId")
            );
            default -> state;
        };
    }

    @Override
    public OrderStep getNextStep(OrderStep currentStep, Reply reply, OrderState state) {
        if (reply.outcome() != ReplyOutcome.SUCCESS) {
            return null; // Will trigger TSQ handling
        }

        return switch (currentStep) {
            case RESERVE_INVENTORY -> OrderStep.PROCESS_PAYMENT;
            case PROCESS_PAYMENT -> OrderStep.SHIP_ORDER;
            case SHIP_ORDER -> null; // Complete
            default -> null;
        };
    }

    @Override
    public OrderStep getCompensationStep(OrderStep step) {
        return switch (step) {
            case RESERVE_INVENTORY -> OrderStep.RELEASE_INVENTORY;
            case PROCESS_PAYMENT -> OrderStep.REFUND_PAYMENT;
            default -> null;
        };
    }
}
```

### Starting a Process

```java
@Service
public class OrderService {

    private final OrderFulfillmentProcess orderProcess;

    public UUID submitOrder(OrderRequest request) {
        return orderProcess.start(Map.of(
            "orderId", request.orderId(),
            "customerId", request.customerId(),
            "items", request.items(),
            "totalAmount", request.totalAmount().toString()
        ));
    }
}
```

---

## Spring Auto-Configuration

```java
@Configuration
@ConditionalOnProperty(prefix = "commandbus.process", name = "enabled", havingValue = "true")
public class ProcessAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public ProcessRepository processRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        return new JdbcProcessRepository(jdbcTemplate, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean
    public ProcessReplyRouter processReplyRouter(
            DataSource dataSource,
            JdbcTemplate jdbcTemplate,
            TransactionTemplate transactionTemplate,
            ProcessRepository processRepository,
            List<BaseProcessManager<?, ?>> managers,
            PgmqClient pgmqClient,
            @Value("${commandbus.process.reply-queue}") String replyQueue,
            @Value("${commandbus.domain}") String domain,
            @Value("${commandbus.process.visibility-timeout:30}") int visibilityTimeout) {

        Map<String, BaseProcessManager<?, ?>> managerMap = managers.stream()
            .collect(Collectors.toMap(
                BaseProcessManager::getProcessType,
                Function.identity()
            ));

        return new ProcessReplyRouter(
            dataSource,
            jdbcTemplate,
            transactionTemplate,
            processRepository,
            managerMap,
            pgmqClient,
            replyQueue,
            domain,
            visibilityTimeout
        );
    }
}
```

### Configuration Properties

```yaml
commandbus:
  domain: orders
  process:
    enabled: true
    reply-queue: order_process_replies
    visibility-timeout: 30
    concurrency: 10
    poll-interval-ms: 1000
    use-notify: true
```

---

## Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| AC1 | ProcessStatus enum has all 9 states: PENDING, IN_PROGRESS, WAITING_FOR_REPLY, WAITING_FOR_TSQ, COMPENSATING, COMPLETED, COMPENSATED, FAILED, CANCELED | Unit test verifies enum values |
| AC2 | ProcessState interface has toMap() and static fromMap() contract | Compile-time verification |
| AC3 | ProcessMetadata is immutable record with all fields | Unit test for immutability |
| AC4 | ProcessRepository can save/update/get processes with typed state | Integration test with Testcontainers |
| AC5 | ProcessRepository correctly logs audit entries | Integration test verifies audit trail |
| AC6 | BaseProcessManager executes steps in sequence | Integration test with multi-step process |
| AC7 | Compensation steps execute in reverse order on failure | Integration test with cancellation |
| AC8 | Process waits for TSQ on FAILED reply | Integration test with failing command |
| AC9 | ProcessReplyRouter routes replies to correct manager | Integration test with multiple process types |
| AC10 | ProcessReplyRouter supports pg_notify for efficient polling | Integration test with notifications |
| AC11 | All operations are transactional | Integration test verifies atomicity |
| AC12 | Audit trail captures command data, reply outcome, and timestamps | Query audit trail after process completion |

---

## Cross-References

- [02-pgmq-client.md](02-pgmq-client.md) - PGMQ client used for reply queue
- [03-repositories.md](03-repositories.md) - Repository patterns
- [05-worker.md](05-worker.md) - Similar concurrency patterns
- [06-command-bus.md](06-command-bus.md) - CommandBus used by process manager
- [07-troubleshooting.md](07-troubleshooting.md) - TSQ integration for failed commands
