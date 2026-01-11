# Spring Boot Integration Specification

## Overview

This specification defines the Spring Boot auto-configuration, properties, and health indicators for the Java Command Bus library.

## Package Structure

```
com.commandbus/
├── CommandBusAutoConfiguration.java  # Auto-config
├── CommandBusProperties.java         # Config properties
└── health/
    ├── CommandBusHealthIndicator.java
    └── WorkerHealthIndicator.java
```

---

## 1. Auto-Configuration

### 1.1 CommandBusAutoConfiguration

```java
package com.commandbus;

import com.commandbus.api.CommandBus;
import com.commandbus.api.impl.DefaultCommandBus;
import com.commandbus.handler.HandlerRegistry;
import com.commandbus.handler.impl.DefaultHandlerRegistry;
import com.commandbus.ops.TroubleshootingQueue;
import com.commandbus.ops.impl.DefaultTroubleshootingQueue;
import com.commandbus.pgmq.PgmqClient;
import com.commandbus.pgmq.impl.JdbcPgmqClient;
import com.commandbus.policy.RetryPolicy;
import com.commandbus.repository.AuditRepository;
import com.commandbus.repository.BatchRepository;
import com.commandbus.repository.CommandRepository;
import com.commandbus.repository.impl.JdbcAuditRepository;
import com.commandbus.repository.impl.JdbcBatchRepository;
import com.commandbus.repository.impl.JdbcCommandRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Auto-configuration for Command Bus.
 *
 * <p>Automatically configures:
 * <ul>
 *   <li>PGMQ Client</li>
 *   <li>Repositories (Command, Batch, Audit)</li>
 *   <li>Handler Registry</li>
 *   <li>Command Bus</li>
 *   <li>Troubleshooting Queue</li>
 *   <li>Retry Policy</li>
 * </ul>
 *
 * <p>To disable auto-configuration:
 * <pre>
 * commandbus.enabled=false
 * </pre>
 */
@AutoConfiguration(after = DataSourceAutoConfiguration.class)
@ConditionalOnClass(JdbcTemplate.class)
@ConditionalOnProperty(prefix = "commandbus", name = "enabled", havingValue = "true", matchIfMissing = true)
@EnableConfigurationProperties(CommandBusProperties.class)
public class CommandBusAutoConfiguration {

    // --- Object Mapper ---

    @Bean
    @ConditionalOnMissingBean
    public ObjectMapper commandBusObjectMapper() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.findAndRegisterModules(); // Register JSR310 module
        return mapper;
    }

    // --- PGMQ Client ---

    @Bean
    @ConditionalOnMissingBean
    public PgmqClient pgmqClient(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        return new JdbcPgmqClient(jdbcTemplate, objectMapper);
    }

    // --- Repositories ---

    @Bean
    @ConditionalOnMissingBean
    public CommandRepository commandRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        return new JdbcCommandRepository(jdbcTemplate, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean
    public BatchRepository batchRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        return new JdbcBatchRepository(jdbcTemplate, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean
    public AuditRepository auditRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        return new JdbcAuditRepository(jdbcTemplate, objectMapper);
    }

    // --- Handler Registry ---

    @Bean
    @ConditionalOnMissingBean
    public HandlerRegistry handlerRegistry() {
        return new DefaultHandlerRegistry();
    }

    // --- Retry Policy ---

    @Bean
    @ConditionalOnMissingBean
    public RetryPolicy retryPolicy(CommandBusProperties properties) {
        return new RetryPolicy(
            properties.getDefaultMaxAttempts(),
            properties.getBackoffSchedule()
        );
    }

    // --- Command Bus ---

    @Bean
    @ConditionalOnMissingBean
    public CommandBus commandBus(
            PgmqClient pgmqClient,
            CommandRepository commandRepository,
            BatchRepository batchRepository,
            AuditRepository auditRepository,
            ObjectMapper objectMapper) {
        return new DefaultCommandBus(
            pgmqClient,
            commandRepository,
            batchRepository,
            auditRepository,
            objectMapper
        );
    }

    // --- Troubleshooting Queue ---

    @Bean
    @ConditionalOnMissingBean
    public TroubleshootingQueue troubleshootingQueue(
            JdbcTemplate jdbcTemplate,
            PgmqClient pgmqClient,
            CommandRepository commandRepository,
            BatchRepository batchRepository,
            AuditRepository auditRepository,
            ObjectMapper objectMapper) {
        return new DefaultTroubleshootingQueue(
            jdbcTemplate,
            pgmqClient,
            commandRepository,
            batchRepository,
            auditRepository,
            objectMapper
        );
    }
}
```

### 1.2 Auto-Configuration Registration

Create `src/main/resources/META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`:

```
com.commandbus.CommandBusAutoConfiguration
```

---

## 2. Configuration Properties

### 2.1 CommandBusProperties

```java
package com.commandbus;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

/**
 * Configuration properties for Command Bus.
 *
 * <p>Example configuration:
 * <pre>
 * commandbus:
 *   enabled: true
 *   default-max-attempts: 3
 *   backoff-schedule: [10, 60, 300]
 *   worker:
 *     visibility-timeout: 30
 *     poll-interval-ms: 1000
 *     concurrency: 4
 *     use-notify: true
 *   batch:
 *     default-chunk-size: 1000
 * </pre>
 */
@ConfigurationProperties(prefix = "commandbus")
public class CommandBusProperties {

    /**
     * Enable/disable Command Bus auto-configuration.
     */
    private boolean enabled = true;

    /**
     * Default maximum retry attempts for commands.
     */
    private int defaultMaxAttempts = 3;

    /**
     * Backoff schedule in seconds for each retry.
     */
    private List<Integer> backoffSchedule = List.of(10, 60, 300);

    /**
     * Worker-specific configuration.
     */
    private WorkerProperties worker = new WorkerProperties();

    /**
     * Batch-specific configuration.
     */
    private BatchProperties batch = new BatchProperties();

    // Getters and setters

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public int getDefaultMaxAttempts() {
        return defaultMaxAttempts;
    }

    public void setDefaultMaxAttempts(int defaultMaxAttempts) {
        this.defaultMaxAttempts = defaultMaxAttempts;
    }

    public List<Integer> getBackoffSchedule() {
        return backoffSchedule;
    }

    public void setBackoffSchedule(List<Integer> backoffSchedule) {
        this.backoffSchedule = backoffSchedule;
    }

    public WorkerProperties getWorker() {
        return worker;
    }

    public void setWorker(WorkerProperties worker) {
        this.worker = worker;
    }

    public BatchProperties getBatch() {
        return batch;
    }

    public void setBatch(BatchProperties batch) {
        this.batch = batch;
    }

    /**
     * Worker configuration properties.
     */
    public static class WorkerProperties {

        /**
         * Visibility timeout in seconds.
         */
        private int visibilityTimeout = 30;

        /**
         * Poll interval in milliseconds.
         */
        private int pollIntervalMs = 1000;

        /**
         * Number of concurrent handlers.
         */
        private int concurrency = 4;

        /**
         * Use PostgreSQL NOTIFY for instant wake-up.
         */
        private boolean useNotify = true;

        // Getters and setters

        public int getVisibilityTimeout() {
            return visibilityTimeout;
        }

        public void setVisibilityTimeout(int visibilityTimeout) {
            this.visibilityTimeout = visibilityTimeout;
        }

        public int getPollIntervalMs() {
            return pollIntervalMs;
        }

        public void setPollIntervalMs(int pollIntervalMs) {
            this.pollIntervalMs = pollIntervalMs;
        }

        public int getConcurrency() {
            return concurrency;
        }

        public void setConcurrency(int concurrency) {
            this.concurrency = concurrency;
        }

        public boolean isUseNotify() {
            return useNotify;
        }

        public void setUseNotify(boolean useNotify) {
            this.useNotify = useNotify;
        }
    }

    /**
     * Batch configuration properties.
     */
    public static class BatchProperties {

        /**
         * Default chunk size for batch operations.
         */
        private int defaultChunkSize = 1000;

        public int getDefaultChunkSize() {
            return defaultChunkSize;
        }

        public void setDefaultChunkSize(int defaultChunkSize) {
            this.defaultChunkSize = defaultChunkSize;
        }
    }
}
```

---

## 3. Health Indicators

### 3.1 CommandBusHealthIndicator

```java
package com.commandbus.health;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Health indicator for Command Bus database connectivity.
 */
@Component
public class CommandBusHealthIndicator implements HealthIndicator {

    private final JdbcTemplate jdbcTemplate;

    public CommandBusHealthIndicator(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public Health health() {
        try {
            // Check PGMQ extension is available
            Boolean pgmqAvailable = jdbcTemplate.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgmq')",
                Boolean.class
            );

            if (!Boolean.TRUE.equals(pgmqAvailable)) {
                return Health.down()
                    .withDetail("error", "PGMQ extension not installed")
                    .build();
            }

            // Check commandbus schema exists
            Boolean schemaExists = jdbcTemplate.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'commandbus')",
                Boolean.class
            );

            if (!Boolean.TRUE.equals(schemaExists)) {
                return Health.down()
                    .withDetail("error", "commandbus schema not found")
                    .build();
            }

            // Get some stats
            Integer pendingCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM commandbus.command WHERE status = 'PENDING'",
                Integer.class
            );

            Integer tsqCount = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM commandbus.command WHERE status = 'IN_TROUBLESHOOTING_QUEUE'",
                Integer.class
            );

            return Health.up()
                .withDetail("pgmq", "available")
                .withDetail("schema", "commandbus")
                .withDetail("pendingCommands", pendingCount)
                .withDetail("troubleshootingCommands", tsqCount)
                .build();

        } catch (Exception e) {
            return Health.down()
                .withDetail("error", e.getMessage())
                .build();
        }
    }
}
```

### 3.2 WorkerHealthIndicator

```java
package com.commandbus.health;

import com.commandbus.worker.Worker;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * Health indicator for Command Bus workers.
 */
@Component
public class WorkerHealthIndicator implements HealthIndicator {

    private final List<Worker> workers;

    public WorkerHealthIndicator(List<Worker> workers) {
        this.workers = workers;
    }

    @Override
    public Health health() {
        if (workers.isEmpty()) {
            return Health.unknown()
                .withDetail("message", "No workers registered")
                .build();
        }

        Map<String, WorkerStatus> workerStatuses = workers.stream()
            .collect(Collectors.toMap(
                Worker::domain,
                w -> new WorkerStatus(w.isRunning(), w.inFlightCount())
            ));

        boolean allRunning = workers.stream().allMatch(Worker::isRunning);
        int totalInFlight = workers.stream().mapToInt(Worker::inFlightCount).sum();

        Health.Builder builder = allRunning ? Health.up() : Health.down();

        return builder
            .withDetail("workers", workerStatuses)
            .withDetail("totalInFlight", totalInFlight)
            .build();
    }

    record WorkerStatus(boolean running, int inFlight) {}
}
```

---

## 4. Worker Auto-Start Configuration

### 4.1 WorkerAutoStartConfiguration

```java
package com.commandbus;

import com.commandbus.handler.HandlerRegistry;
import com.commandbus.policy.RetryPolicy;
import com.commandbus.worker.Worker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.JdbcTemplate;

import jakarta.annotation.PreDestroy;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * Auto-start configuration for workers.
 *
 * <p>Enable with:
 * <pre>
 * commandbus:
 *   worker:
 *     auto-start: true
 *     domains: [payments, orders]
 * </pre>
 */
@Configuration
@ConditionalOnProperty(prefix = "commandbus.worker", name = "auto-start", havingValue = "true")
public class WorkerAutoStartConfiguration {

    private static final Logger log = LoggerFactory.getLogger(WorkerAutoStartConfiguration.class);

    private final List<Worker> workers = new ArrayList<>();
    private final JdbcTemplate jdbcTemplate;
    private final HandlerRegistry handlerRegistry;
    private final RetryPolicy retryPolicy;
    private final CommandBusProperties properties;

    public WorkerAutoStartConfiguration(
            JdbcTemplate jdbcTemplate,
            HandlerRegistry handlerRegistry,
            RetryPolicy retryPolicy,
            CommandBusProperties properties) {
        this.jdbcTemplate = jdbcTemplate;
        this.handlerRegistry = handlerRegistry;
        this.retryPolicy = retryPolicy;
        this.properties = properties;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void startWorkers() {
        // Get domains from registered handlers
        List<String> domains = handlerRegistry.registeredHandlers().stream()
            .map(k -> k.domain())
            .distinct()
            .toList();

        if (domains.isEmpty()) {
            log.warn("No handlers registered, no workers to start");
            return;
        }

        CommandBusProperties.WorkerProperties wp = properties.getWorker();

        for (String domain : domains) {
            Worker worker = Worker.builder()
                .jdbcTemplate(jdbcTemplate)
                .domain(domain)
                .handlerRegistry(handlerRegistry)
                .visibilityTimeout(wp.getVisibilityTimeout())
                .pollIntervalMs(wp.getPollIntervalMs())
                .concurrency(wp.getConcurrency())
                .useNotify(wp.isUseNotify())
                .retryPolicy(retryPolicy)
                .build();

            worker.start();
            workers.add(worker);

            log.info("Started worker for domain={}", domain);
        }
    }

    @PreDestroy
    public void stopWorkers() {
        log.info("Stopping {} workers...", workers.size());

        workers.forEach(w -> w.stop(Duration.ofSeconds(30)));

        log.info("All workers stopped");
    }

    @Bean
    public List<Worker> commandBusWorkers() {
        return workers;
    }
}
```

---

## 5. Example Configuration

### 5.1 application.yml

```yaml
spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/commandbus_db
    username: postgres
    password: postgres
    hikari:
      maximum-pool-size: 20

commandbus:
  enabled: true
  default-max-attempts: 3
  backoff-schedule: [10, 60, 300]

  worker:
    auto-start: true
    visibility-timeout: 30
    poll-interval-ms: 1000
    concurrency: 4
    use-notify: true

  batch:
    default-chunk-size: 1000

management:
  endpoints:
    web:
      exposure:
        include: health,info
  endpoint:
    health:
      show-details: always
```

### 5.2 application-test.yml

```yaml
spring:
  datasource:
    url: jdbc:tc:postgresql:15-alpine:///testdb?TC_INITSCRIPT=db/migration/V001__commandbus_schema.sql

commandbus:
  worker:
    auto-start: false  # Don't auto-start in tests
```

---

## 6. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| SI-1 | Auto-configuration creates all beans | Integration test |
| SI-2 | @ConditionalOnMissingBean allows override | Unit test |
| SI-3 | Properties bound correctly | Unit test |
| SI-4 | Health indicator reports PGMQ status | Integration test |
| SI-5 | Workers auto-start when enabled | Integration test |
| SI-6 | Workers stop gracefully on shutdown | Integration test |
| SI-7 | Disabled via commandbus.enabled=false | Unit test |
