# Testing Specification

## Overview

This specification defines the testing utilities, Testcontainers setup, and fake implementations for the Java Command Bus library.

## Package Structure

```
com.commandbus.testing/
├── FakePgmqClient.java              # In-memory PGMQ for unit tests
├── CommandBusTestConfiguration.java # Test configuration
└── TestContainerConfiguration.java  # Testcontainers setup

src/test/java/com/commandbus/
├── unit/                            # Unit tests (no database)
│   ├── HandlerRegistryTest.java
│   ├── RetryPolicyTest.java
│   └── ...
├── integration/                     # Integration tests (Testcontainers)
│   ├── CommandBusIntegrationTest.java
│   ├── WorkerIntegrationTest.java
│   └── ...
└── e2e/                            # End-to-end tests
    └── FullFlowTest.java
```

---

## 1. Testcontainers Setup

### 1.1 PostgreSQL with PGMQ Container

```java
package com.commandbus.testing;

import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * PostgreSQL container with PGMQ extension.
 *
 * <p>Uses the official PGMQ image which includes the extension pre-installed.
 */
public class PgmqPostgreSQLContainer extends PostgreSQLContainer<PgmqPostgreSQLContainer> {

    private static final DockerImageName IMAGE = DockerImageName
        .parse("quay.io/tembo/pg16-pgmq:latest")
        .asCompatibleSubstituteFor("postgres");

    public PgmqPostgreSQLContainer() {
        super(IMAGE);
        // Apply migration script
        withInitScript("db/migration/V001__commandbus_schema.sql");
    }

    /**
     * Create a singleton container for reuse across tests.
     */
    public static PgmqPostgreSQLContainer getInstance() {
        return Singleton.INSTANCE;
    }

    private static class Singleton {
        private static final PgmqPostgreSQLContainer INSTANCE = new PgmqPostgreSQLContainer();

        static {
            INSTANCE.start();
        }
    }
}
```

### 1.2 TestContainerConfiguration

```java
package com.commandbus.testing;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * Test configuration that provides PostgreSQL + PGMQ container.
 *
 * <p>Usage:
 * <pre>
 * {@literal @}SpringBootTest
 * {@literal @}Import(TestContainerConfiguration.class)
 * class MyIntegrationTest {
 *     // Tests run against real PostgreSQL + PGMQ
 * }
 * </pre>
 */
@TestConfiguration
public class TestContainerConfiguration {

    @Bean
    @ServiceConnection
    public PostgreSQLContainer<?> postgresContainer() {
        return PgmqPostgreSQLContainer.getInstance();
    }
}
```

---

## 2. Fake PGMQ Client

### 2.1 FakePgmqClient

```java
package com.commandbus.testing;

import com.commandbus.model.PgmqMessage;
import com.commandbus.pgmq.PgmqClient;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * In-memory fake implementation of PgmqClient for unit testing.
 *
 * <p>This fake provides:
 * <ul>
 *   <li>In-memory queue storage</li>
 *   <li>Visibility timeout simulation</li>
 *   <li>Message archive</li>
 *   <li>Notification tracking</li>
 * </ul>
 *
 * <p>Usage:
 * <pre>
 * FakePgmqClient fake = new FakePgmqClient();
 *
 * // Send a message
 * long msgId = fake.send("myqueue", Map.of("key", "value"));
 *
 * // Read messages
 * List<PgmqMessage> messages = fake.read("myqueue", 30, 10);
 *
 * // Verify notifications
 * assertTrue(fake.wasNotified("myqueue"));
 * </pre>
 */
public class FakePgmqClient implements PgmqClient {

    private final Map<String, Queue<FakeMessage>> queues = new ConcurrentHashMap<>();
    private final Map<String, List<FakeMessage>> archives = new ConcurrentHashMap<>();
    private final Set<String> notifiedQueues = ConcurrentHashMap.newKeySet();
    private final Set<String> createdQueues = ConcurrentHashMap.newKeySet();
    private final AtomicLong msgIdCounter = new AtomicLong(1);

    @Override
    public void createQueue(String queueName) {
        createdQueues.add(queueName);
        queues.putIfAbsent(queueName, new LinkedList<>());
    }

    @Override
    public long send(String queueName, Map<String, Object> message) {
        return send(queueName, message, 0);
    }

    @Override
    public long send(String queueName, Map<String, Object> message, int delaySeconds) {
        queues.putIfAbsent(queueName, new LinkedList<>());

        long msgId = msgIdCounter.getAndIncrement();
        Instant visibleAt = Instant.now().plusSeconds(delaySeconds);

        FakeMessage fakeMsg = new FakeMessage(msgId, message, visibleAt, 0);
        queues.get(queueName).add(fakeMsg);

        notifiedQueues.add(queueName);
        return msgId;
    }

    @Override
    public List<Long> sendBatch(String queueName, List<Map<String, Object>> messages) {
        return sendBatch(queueName, messages, 0);
    }

    @Override
    public List<Long> sendBatch(String queueName, List<Map<String, Object>> messages, int delaySeconds) {
        List<Long> msgIds = new ArrayList<>();
        for (Map<String, Object> message : messages) {
            // Don't notify for each message in batch
            queues.putIfAbsent(queueName, new LinkedList<>());
            long msgId = msgIdCounter.getAndIncrement();
            Instant visibleAt = Instant.now().plusSeconds(delaySeconds);
            FakeMessage fakeMsg = new FakeMessage(msgId, message, visibleAt, 0);
            queues.get(queueName).add(fakeMsg);
            msgIds.add(msgId);
        }
        return msgIds;
    }

    @Override
    public void notify(String queueName) {
        notifiedQueues.add(queueName);
    }

    @Override
    public List<PgmqMessage> read(String queueName, int visibilityTimeoutSeconds, int batchSize) {
        Queue<FakeMessage> queue = queues.get(queueName);
        if (queue == null || queue.isEmpty()) {
            return List.of();
        }

        List<PgmqMessage> result = new ArrayList<>();
        Instant now = Instant.now();
        Instant newVt = now.plusSeconds(visibilityTimeoutSeconds);

        Iterator<FakeMessage> iter = queue.iterator();
        while (iter.hasNext() && result.size() < batchSize) {
            FakeMessage msg = iter.next();

            // Skip messages still invisible
            if (msg.visibleAt.isAfter(now)) {
                continue;
            }

            // Update visibility and read count
            msg.visibleAt = newVt;
            msg.readCount++;

            result.add(new PgmqMessage(
                msg.msgId,
                msg.readCount,
                msg.enqueuedAt,
                msg.visibleAt,
                msg.message
            ));
        }

        return result;
    }

    @Override
    public boolean delete(String queueName, long msgId) {
        Queue<FakeMessage> queue = queues.get(queueName);
        if (queue == null) return false;

        return queue.removeIf(m -> m.msgId == msgId);
    }

    @Override
    public boolean archive(String queueName, long msgId) {
        Queue<FakeMessage> queue = queues.get(queueName);
        if (queue == null) return false;

        FakeMessage toArchive = null;
        for (FakeMessage msg : queue) {
            if (msg.msgId == msgId) {
                toArchive = msg;
                break;
            }
        }

        if (toArchive != null) {
            queue.remove(toArchive);
            archives.computeIfAbsent(queueName, k -> new ArrayList<>()).add(toArchive);
            return true;
        }

        return false;
    }

    @Override
    public boolean setVisibilityTimeout(String queueName, long msgId, int visibilityTimeoutSeconds) {
        Queue<FakeMessage> queue = queues.get(queueName);
        if (queue == null) return false;

        for (FakeMessage msg : queue) {
            if (msg.msgId == msgId) {
                msg.visibleAt = Instant.now().plusSeconds(visibilityTimeoutSeconds);
                return true;
            }
        }

        return false;
    }

    @Override
    public Optional<PgmqMessage> getFromArchive(String queueName, String commandId) {
        List<FakeMessage> archive = archives.get(queueName);
        if (archive == null) return Optional.empty();

        // Find by command_id in message payload
        for (int i = archive.size() - 1; i >= 0; i--) {
            FakeMessage msg = archive.get(i);
            if (commandId.equals(msg.message.get("command_id"))) {
                return Optional.of(new PgmqMessage(
                    msg.msgId,
                    msg.readCount,
                    msg.enqueuedAt,
                    msg.visibleAt,
                    msg.message
                ));
            }
        }

        return Optional.empty();
    }

    // --- Test Helpers ---

    /**
     * Check if a queue was notified.
     */
    public boolean wasNotified(String queueName) {
        return notifiedQueues.contains(queueName);
    }

    /**
     * Clear notification tracking.
     */
    public void clearNotifications() {
        notifiedQueues.clear();
    }

    /**
     * Get number of messages in a queue.
     */
    public int queueSize(String queueName) {
        Queue<FakeMessage> queue = queues.get(queueName);
        return queue != null ? queue.size() : 0;
    }

    /**
     * Get number of archived messages.
     */
    public int archiveSize(String queueName) {
        List<FakeMessage> archive = archives.get(queueName);
        return archive != null ? archive.size() : 0;
    }

    /**
     * Check if queue was created.
     */
    public boolean wasCreated(String queueName) {
        return createdQueues.contains(queueName);
    }

    /**
     * Reset all state.
     */
    public void reset() {
        queues.clear();
        archives.clear();
        notifiedQueues.clear();
        createdQueues.clear();
        msgIdCounter.set(1);
    }

    /**
     * Internal message representation.
     */
    private static class FakeMessage {
        final long msgId;
        final Map<String, Object> message;
        final Instant enqueuedAt;
        Instant visibleAt;
        int readCount;

        FakeMessage(long msgId, Map<String, Object> message, Instant visibleAt, int readCount) {
            this.msgId = msgId;
            this.message = new HashMap<>(message);
            this.enqueuedAt = Instant.now();
            this.visibleAt = visibleAt;
            this.readCount = readCount;
        }
    }
}
```

---

## 3. Test Configuration

### 3.1 CommandBusTestConfiguration

```java
package com.commandbus.testing;

import com.commandbus.pgmq.PgmqClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/**
 * Test configuration that replaces real PGMQ with fake.
 *
 * <p>Usage for unit tests:
 * <pre>
 * {@literal @}SpringBootTest
 * {@literal @}Import(CommandBusTestConfiguration.class)
 * class MyUnitTest {
 *     {@literal @}Autowired
 *     FakePgmqClient fakePgmq;
 *
 *     {@literal @}BeforeEach
 *     void setup() {
 *         fakePgmq.reset();
 *     }
 * }
 * </pre>
 */
@TestConfiguration
public class CommandBusTestConfiguration {

    @Bean
    @Primary
    public FakePgmqClient fakePgmqClient() {
        return new FakePgmqClient();
    }

    @Bean
    @Primary
    public PgmqClient pgmqClient(FakePgmqClient fake) {
        return fake;
    }
}
```

---

## 4. Test Examples

### 4.1 Unit Test (No Database)

```java
package com.commandbus.unit;

import com.commandbus.handler.CommandHandler;
import com.commandbus.handler.HandlerRegistry;
import com.commandbus.handler.impl.DefaultHandlerRegistry;
import com.commandbus.exception.HandlerNotFoundException;
import com.commandbus.exception.HandlerAlreadyRegisteredException;
import com.commandbus.model.Command;
import com.commandbus.model.HandlerContext;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class HandlerRegistryTest {

    private HandlerRegistry registry;

    @BeforeEach
    void setup() {
        registry = new DefaultHandlerRegistry();
    }

    @Test
    void shouldRegisterAndDispatchHandler() throws Exception {
        // Given
        CommandHandler handler = (cmd, ctx) -> Map.of("processed", true);
        registry.register("payments", "Debit", handler);

        Command command = new Command(
            "payments", "Debit", UUID.randomUUID(),
            Map.of("amount", 100), null, null, Instant.now()
        );
        HandlerContext context = new HandlerContext(command, 1, 3, 1L, null);

        // When
        Object result = registry.dispatch(command, context);

        // Then
        assertNotNull(result);
        assertEquals(Map.of("processed", true), result);
    }

    @Test
    void shouldThrowOnDuplicateRegistration() {
        // Given
        CommandHandler handler = (cmd, ctx) -> null;
        registry.register("payments", "Debit", handler);

        // When/Then
        assertThrows(HandlerAlreadyRegisteredException.class,
            () -> registry.register("payments", "Debit", handler));
    }

    @Test
    void shouldThrowOnMissingHandler() {
        // Given
        Command command = new Command(
            "payments", "Unknown", UUID.randomUUID(),
            Map.of(), null, null, Instant.now()
        );
        HandlerContext context = new HandlerContext(command, 1, 3, 1L, null);

        // When/Then
        assertThrows(HandlerNotFoundException.class,
            () -> registry.dispatch(command, context));
    }
}
```

### 4.2 Integration Test (Testcontainers)

```java
package com.commandbus.integration;

import com.commandbus.api.CommandBus;
import com.commandbus.model.CommandMetadata;
import com.commandbus.model.CommandStatus;
import com.commandbus.model.SendResult;
import com.commandbus.testing.TestContainerConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
@Import(TestContainerConfiguration.class)
class CommandBusIntegrationTest {

    @Autowired
    CommandBus commandBus;

    @Test
    void shouldSendAndRetrieveCommand() {
        // Given
        String domain = "test";
        String commandType = "TestCommand";
        UUID commandId = UUID.randomUUID();
        Map<String, Object> data = Map.of("key", "value");

        // When
        SendResult result = commandBus.send(domain, commandType, commandId, data);

        // Then
        assertNotNull(result);
        assertEquals(commandId, result.commandId());
        assertTrue(result.msgId() > 0);

        // Verify persisted
        CommandMetadata metadata = commandBus.getCommand(domain, commandId);
        assertNotNull(metadata);
        assertEquals(CommandStatus.PENDING, metadata.status());
        assertEquals(0, metadata.attempts());
    }

    @Test
    void shouldRejectDuplicateCommand() {
        // Given
        UUID commandId = UUID.randomUUID();
        commandBus.send("test", "TestCommand", commandId, Map.of());

        // When/Then
        assertThrows(DuplicateCommandException.class,
            () -> commandBus.send("test", "TestCommand", commandId, Map.of()));
    }
}
```

### 4.3 Worker Integration Test

```java
package com.commandbus.integration;

import com.commandbus.api.CommandBus;
import com.commandbus.handler.Handler;
import com.commandbus.handler.HandlerRegistry;
import com.commandbus.model.*;
import com.commandbus.testing.TestContainerConfiguration;
import com.commandbus.worker.Worker;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
@Import({TestContainerConfiguration.class, WorkerIntegrationTest.TestHandlers.class})
class WorkerIntegrationTest {

    @Autowired
    CommandBus commandBus;

    @Autowired
    JdbcTemplate jdbcTemplate;

    @Autowired
    HandlerRegistry handlerRegistry;

    @Autowired
    TestHandlers testHandlers;

    @Test
    void shouldProcessCommandSuccessfully() throws Exception {
        // Given
        UUID commandId = UUID.randomUUID();
        CountDownLatch latch = new CountDownLatch(1);
        testHandlers.setCallback(cmd -> latch.countDown());

        Worker worker = Worker.builder()
            .jdbcTemplate(jdbcTemplate)
            .domain("test")
            .handlerRegistry(handlerRegistry)
            .concurrency(1)
            .build();

        // When
        worker.start();
        commandBus.send("test", "ProcessMe", commandId, Map.of("value", 42));

        // Then
        assertTrue(latch.await(10, TimeUnit.SECONDS), "Handler not invoked");

        worker.stop(Duration.ofSeconds(5)).join();

        CommandMetadata metadata = commandBus.getCommand("test", commandId);
        assertEquals(CommandStatus.COMPLETED, metadata.status());
    }

    @TestConfiguration
    static class TestHandlers {
        private volatile Runnable callback;

        void setCallback(Runnable callback) {
            this.callback = callback;
        }

        @Handler(domain = "test", commandType = "ProcessMe")
        public Map<String, Object> handleProcessMe(Command command, HandlerContext context) {
            if (callback != null) {
                callback.run();
            }
            return Map.of("processed", command.data().get("value"));
        }
    }
}
```

---

## 5. Test Markers and Categories

### 5.1 Test Categories

```java
package com.commandbus.testing;

import org.junit.jupiter.api.Tag;
import java.lang.annotation.*;

/**
 * Marker for integration tests requiring database.
 */
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@Tag("integration")
public @interface IntegrationTest {}

/**
 * Marker for end-to-end tests.
 */
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@Tag("e2e")
public @interface E2ETest {}

/**
 * Marker for slow tests.
 */
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@Tag("slow")
public @interface SlowTest {}
```

### 5.2 Maven Surefire Configuration

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>3.2.2</version>
    <configuration>
        <!-- Run unit tests by default -->
        <excludedGroups>integration,e2e,slow</excludedGroups>
    </configuration>
</plugin>

<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-failsafe-plugin</artifactId>
    <version>3.2.2</version>
    <configuration>
        <!-- Run integration tests -->
        <groups>integration</groups>
    </configuration>
    <executions>
        <execution>
            <goals>
                <goal>integration-test</goal>
                <goal>verify</goal>
            </goals>
        </execution>
    </executions>
</plugin>
```

---

## 6. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| TS-1 | FakePgmqClient passes all unit tests | Unit test suite |
| TS-2 | Testcontainers starts PGMQ successfully | Integration test |
| TS-3 | Integration tests run against real DB | Maven failsafe |
| TS-4 | 80% line coverage achieved | JaCoCo report |
| TS-5 | 80% branch coverage achieved | JaCoCo report |
| TS-6 | Test isolation (no state leakage) | Parallel test run |
| TS-7 | FakePgmqClient simulates visibility timeout | Unit test |
| TS-8 | FakePgmqClient simulates archive | Unit test |
