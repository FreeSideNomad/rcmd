# Java Command Bus Library - Implementation Specification

## Overview

This specification describes the implementation of a Java/Spring Boot command bus library that provides the same functionality as the Python `commandbus` library. The library uses PostgreSQL with PGMQ extension for message queuing and provides a robust command processing system with retry policies, troubleshooting queues, and batch operations.

## Related Specifications

This document provides the architectural overview. Detailed specifications for each component are in separate files:

| Spec | File | Description |
|------|------|-------------|
| Domain Models | [01-domain-models.md](java-spec/01-domain-models.md) | Records, enums, value objects |
| PGMQ Client | [02-pgmq-client.md](java-spec/02-pgmq-client.md) | PGMQ SQL wrapper |
| Repositories | [03-repositories.md](java-spec/03-repositories.md) | Data access layer |
| Handler System | [04-handler-registry.md](java-spec/04-handler-registry.md) | Handler registration and dispatch |
| Worker | [05-worker.md](java-spec/05-worker.md) | Message processing worker |
| Command Bus API | [06-command-bus.md](java-spec/06-command-bus.md) | Public API |
| Troubleshooting | [07-troubleshooting.md](java-spec/07-troubleshooting.md) | TSQ operations |
| Spring Integration | [08-spring-integration.md](java-spec/08-spring-integration.md) | Auto-configuration |
| Testing | [09-testing.md](java-spec/09-testing.md) | Test utilities |
| Process Manager | [10-process.md](java-spec/10-process.md) | Long-running workflow orchestration |
| E2E Test App | [11-admin-ui.md](java-spec/11-admin-ui.md) | Thymeleaf E2E test application (test scope only) |

---

## 1. Project Setup

### 1.1 Maven Project Structure

Create a new Maven project using Spring Initializr or manually:

```
commandbus-spring/
├── pom.xml
├── src/
│   ├── main/
│   │   ├── java/
│   │   │   └── com/commandbus/
│   │   │       ├── CommandBusAutoConfiguration.java
│   │   │       ├── api/
│   │   │       │   ├── CommandBus.java (interface)
│   │   │       │   └── impl/
│   │   │       │       └── DefaultCommandBus.java
│   │   │       ├── model/
│   │   │       │   ├── Command.java (record)
│   │   │       │   ├── CommandMetadata.java (record)
│   │   │       │   ├── CommandStatus.java (enum)
│   │   │       │   ├── Reply.java (record)
│   │   │       │   └── ... (other models)
│   │   │       ├── exception/
│   │   │       │   ├── CommandBusException.java
│   │   │       │   ├── TransientCommandException.java
│   │   │       │   ├── PermanentCommandException.java
│   │   │       │   └── ...
│   │   │       ├── handler/
│   │   │       │   ├── Handler.java (annotation)
│   │   │       │   ├── HandlerRegistry.java (interface)
│   │   │       │   ├── HandlerContext.java (record)
│   │   │       │   └── impl/
│   │   │       │       └── DefaultHandlerRegistry.java
│   │   │       ├── worker/
│   │   │       │   ├── Worker.java (interface)
│   │   │       │   ├── WorkerProperties.java
│   │   │       │   └── impl/
│   │   │       │       └── DefaultWorker.java
│   │   │       ├── repository/
│   │   │       │   ├── CommandRepository.java (interface)
│   │   │       │   ├── BatchRepository.java (interface)
│   │   │       │   ├── AuditRepository.java (interface)
│   │   │       │   └── impl/
│   │   │       │       ├── JdbcCommandRepository.java
│   │   │       │       ├── JdbcBatchRepository.java
│   │   │       │       └── JdbcAuditRepository.java
│   │   │       ├── pgmq/
│   │   │       │   ├── PgmqClient.java (interface)
│   │   │       │   └── impl/
│   │   │       │       └── JdbcPgmqClient.java
│   │   │       ├── policy/
│   │   │       │   └── RetryPolicy.java (record)
│   │   │       ├── ops/
│   │   │       │   ├── TroubleshootingQueue.java (interface)
│   │   │       │   └── impl/
│   │   │       │       └── DefaultTroubleshootingQueue.java
│   │   │       ├── process/
│   │   │       │   ├── ProcessStatus.java (enum)
│   │   │       │   ├── ProcessState.java (interface)
│   │   │       │   ├── ProcessMetadata.java (record)
│   │   │       │   ├── ProcessAuditEntry.java (record)
│   │   │       │   ├── BaseProcessManager.java (abstract)
│   │   │       │   ├── ProcessReplyRouter.java
│   │   │       │   └── ProcessRepository.java (interface)
│   │   │       └── testing/
│   │   │           ├── FakePgmqClient.java
│   │   │           └── TestCommandBusConfiguration.java
│   │   └── resources/
│   │       ├── META-INF/
│   │       │   └── spring/
│   │       │       └── org.springframework.boot.autoconfigure.AutoConfiguration.imports
│   │       └── db/migration/
│   │           ├── V001__commandbus_schema.sql
│   │           └── V003__process_manager_schema.sql
│   └── test/
│       ├── java/com/commandbus/
│       │   ├── integration/
│       │   ├── unit/
│       │   └── e2e/                   # E2E Test Application (NOT shipped)
│       │       ├── E2ETestApplication.java
│       │       ├── controller/
│       │       ├── service/
│       │       ├── dto/
│       │       └── handlers/
│       └── resources/
│           ├── templates/             # E2E UI templates
│           │   └── pages/ (dashboard.html, commands.html, tsq.html, etc.)
│           ├── static/css/
│           └── application-e2e.yml
└── README.md
```

### 1.2 Maven POM Configuration

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.commandbus</groupId>
    <artifactId>commandbus-spring</artifactId>
    <version>1.0.0-SNAPSHOT</version>
    <packaging>jar</packaging>

    <name>Command Bus Spring</name>
    <description>Command Bus implementation for Spring Boot with PostgreSQL and PGMQ</description>

    <properties>
        <java.version>21</java.version>
        <spring-boot.version>3.2.0</spring-boot.version>
        <postgresql.version>42.7.1</postgresql.version>
        <testcontainers.version>1.19.3</testcontainers.version>
        <maven.compiler.source>${java.version}</maven.compiler.source>
        <maven.compiler.target>${java.version}</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>

    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-dependencies</artifactId>
                <version>${spring-boot.version}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
            <dependency>
                <groupId>org.testcontainers</groupId>
                <artifactId>testcontainers-bom</artifactId>
                <version>${testcontainers.version}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>

    <dependencies>
        <!-- Spring Boot -->
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-jdbc</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-actuator</artifactId>
            <optional>true</optional>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-autoconfigure-processor</artifactId>
            <optional>true</optional>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-configuration-processor</artifactId>
            <optional>true</optional>
        </dependency>

        <!-- PostgreSQL -->
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <version>${postgresql.version}</version>
        </dependency>

        <!-- Jackson for JSON -->
        <dependency>
            <groupId>com.fasterxml.jackson.core</groupId>
            <artifactId>jackson-databind</artifactId>
        </dependency>
        <dependency>
            <groupId>com.fasterxml.jackson.datatype</groupId>
            <artifactId>jackson-datatype-jsr310</artifactId>
        </dependency>

        <!-- Logging -->
        <dependency>
            <groupId>org.slf4j</groupId>
            <artifactId>slf4j-api</artifactId>
        </dependency>

        <!-- Testing -->
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.testcontainers</groupId>
            <artifactId>postgresql</artifactId>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.testcontainers</groupId>
            <artifactId>junit-jupiter</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.11.0</version>
                <configuration>
                    <release>${java.version}</release>
                    <compilerArgs>
                        <arg>--enable-preview</arg>
                    </compilerArgs>
                </configuration>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.2.2</version>
                <configuration>
                    <argLine>--enable-preview</argLine>
                </configuration>
            </plugin>
            <plugin>
                <groupId>org.jacoco</groupId>
                <artifactId>jacoco-maven-plugin</artifactId>
                <version>0.8.11</version>
                <executions>
                    <execution>
                        <goals>
                            <goal>prepare-agent</goal>
                        </goals>
                    </execution>
                    <execution>
                        <id>report</id>
                        <phase>test</phase>
                        <goals>
                            <goal>report</goal>
                        </goals>
                    </execution>
                    <execution>
                        <id>check</id>
                        <goals>
                            <goal>check</goal>
                        </goals>
                        <configuration>
                            <rules>
                                <rule>
                                    <element>BUNDLE</element>
                                    <limits>
                                        <limit>
                                            <counter>LINE</counter>
                                            <value>COVEREDRATIO</value>
                                            <minimum>0.80</minimum>
                                        </limit>
                                        <limit>
                                            <counter>BRANCH</counter>
                                            <value>COVEREDRATIO</value>
                                            <minimum>0.80</minimum>
                                        </limit>
                                    </limits>
                                </rule>
                            </rules>
                        </configuration>
                    </execution>
                </executions>
            </plugin>
        </plugins>
    </build>
</project>
```

---

## 2. Architecture Overview

### 2.1 Component Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Application Layer (Shipped Library)                 │
│  ┌────────────┐  ┌────────────┐  ┌─────────────────┐  ┌──────────────────┐   │
│  │ CommandBus │  │   Worker   │  │ TroubleshootingQ│  │ ProcessManager   │   │
│  │ (send)     │  │ (process)  │  │ (operator ops)  │  │ (workflows)      │   │
│  └─────┬──────┘  └─────┬──────┘  └───────┬─────────┘  └────────┬─────────┘   │
└───────────┼─────────────┼─────────────────┼─────────────────┼────────────────┘
            │             │                 │                 │
┌───────────┴─────────────┴─────────────────┴─────────────────┴────────────────┐
│                    E2E Test Application (NOT shipped - test scope only)       │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                        Thymeleaf UI                                     │  │
│  │   Dashboard | Commands | TSQ | Batches | Processes | Queues             │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
            │             │                 │                 │
┌───────────┼─────────────┼─────────────────┼─────────────────┼────────────────┐
│           │          Domain Layer         │                 │                │
│  ┌────────▼────────┐  ┌────────▼────────┐  ┌───────────────▼──────────────┐  │
│  │ HandlerRegistry │  │  RetryPolicy    │  │ Command, Batch, Process...   │  │
│  └─────────────────┘  └─────────────────┘  └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
            │             │                 │                 │
┌───────────┼─────────────┼─────────────────┼─────────────────┼────────────────┐
│           │        Infrastructure Layer   │                 │                │
│  ┌────────▼────────┐  ┌────────▼────────┐  ┌───────────────▼──────────────┐  │
│  │   PgmqClient    │  │   Repositories  │  │  ProcessRepository           │  │
│  └────────┬────────┘  └────────┬────────┘  └───────────────┬──────────────┘  │
└───────────┼─────────────────────┼──────────────────────────┼─────────────────┘
            │                     │                          │
            └─────────────────────┴──────────────────────────┘
                                  │
                         ┌────────▼────────┐
                         │   PostgreSQL    │
                         │   + PGMQ        │
                         └─────────────────┘
```

### 2.2 Design Principles

1. **Interface-First Design**: All public APIs are interfaces with hidden implementations
2. **Clean Domain Model**: Domain objects (records) have no persistence annotations
3. **Dependency Injection**: All components are Spring beans
4. **Immutability**: Use Java records for immutable data structures
5. **Transaction Management**: Spring's declarative transaction support
6. **Virtual Threads**: Use Java 21 virtual threads for concurrency

### 2.3 Key Patterns

| Pattern | Usage |
|---------|-------|
| Repository | Data access abstraction for commands, batches, audit |
| Strategy | RetryPolicy for configurable retry behavior |
| Observer | Batch completion callbacks |
| Factory | CommandBus creates commands and batches |
| Template Method | Worker processing loop |

---

## 3. Database Schema

The library uses the **exact same PostgreSQL schema** as the Python implementation. This ensures compatibility and allows gradual migration between implementations.

### 3.1 Schema Overview

```sql
-- Schema: commandbus
-- Extension: pgmq

-- Tables:
-- commandbus.batch     - Batch metadata
-- commandbus.command   - Command metadata
-- commandbus.audit     - Audit trail (append-only)
-- commandbus.payload_archive - Archived payloads

-- PGMQ Tables (auto-created):
-- pgmq.{domain}__commands        - Command queue
-- pgmq.a_{domain}__commands      - Command archive
-- pgmq.{domain}__replies         - Reply queue (optional)
```

### 3.2 Migration File

Copy the Python migration file to `src/main/resources/db/migration/V001__commandbus_schema.sql`. The migration includes:

- Schema creation (`commandbus`)
- Table definitions with indexes
- Stored procedures:
  - `sp_receive_command()` - Atomic command receive
  - `sp_finish_command()` - Atomic completion/failure
  - `sp_fail_command()` - Record transient failure
  - `sp_update_batch_counters()` - Batch counter management
  - `sp_start_batch()` - Batch start transition
  - `sp_tsq_complete/cancel/retry()` - TSQ operations

---

## 4. Configuration Properties

```yaml
# application.yml
commandbus:
  # Default retry configuration
  default-max-attempts: 3
  backoff-schedule: [10, 60, 300]  # seconds

  # Worker configuration
  worker:
    visibility-timeout: 30  # seconds
    poll-interval: 1000     # milliseconds
    concurrency: 4          # concurrent handlers
    use-notify: true        # use pg_notify for instant wake

  # Batch configuration
  batch:
    default-chunk-size: 1000

  # Queue naming
  queue-suffix: commands
  reply-suffix: replies
```

---

## 5. Message Flow

### 5.1 Send Command Flow

```
1. CommandBus.send(domain, commandType, commandId, data)
   │
   ├─ Validate batch_id if provided
   ├─ Check for duplicate command_id
   │
   ▼
2. [Transaction Start]
   │
   ├─ Build message payload (JSON)
   ├─ pgmq.send(queue, message) → msg_id
   ├─ Save CommandMetadata (PENDING status)
   ├─ Insert audit event (SENT)
   ├─ NOTIFY {queue}_notify
   │
   ▼
3. [Transaction Commit]
   │
   └─ Return SendResult(commandId, msgId)
```

### 5.2 Process Command Flow

```
1. Worker.run() [Virtual Thread Pool]
   │
   ├─ LISTEN pgmq_notify_{queue}
   │
   ▼
2. [Message Loop]
   │
   ├─ pgmq.read(queue, visibilityTimeout, batchSize)
   │
   ▼
3. For each message:
   │
   ├─ sp_receive_command() → increment attempts, status=IN_PROGRESS
   ├─ Build Command from payload
   ├─ Build HandlerContext(attempt, maxAttempts, msgId)
   │
   ▼
4. Dispatch to handler (via HandlerRegistry)
   │
   ├─ [Success] → complete()
   │   ├─ pgmq.delete(queue, msgId)
   │   ├─ sp_finish_command(COMPLETED)
   │   ├─ Send reply if reply_to configured
   │   └─ Invoke batch callback if complete
   │
   ├─ [TransientException] → fail()
   │   ├─ If retries remaining:
   │   │   ├─ sp_fail_command()
   │   │   └─ pgmq.set_vt(backoff)
   │   └─ If retries exhausted:
   │       ├─ pgmq.archive()
   │       └─ sp_finish_command(IN_TROUBLESHOOTING_QUEUE)
   │
   └─ [PermanentException] → failPermanent()
       ├─ pgmq.archive()
       └─ sp_finish_command(IN_TROUBLESHOOTING_QUEUE)
```

---

## 6. Quick Start Guide

### 6.1 Add Dependency

```xml
<dependency>
    <groupId>com.commandbus</groupId>
    <artifactId>commandbus-spring</artifactId>
    <version>1.0.0</version>
</dependency>
```

### 6.2 Configure Database

```yaml
spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/mydb
    username: postgres
    password: postgres

commandbus:
  default-max-attempts: 3
```

### 6.3 Define a Handler

```java
@Component
public class PaymentHandlers {

    @Handler(domain = "payments", commandType = "DebitAccount")
    public Map<String, Object> handleDebit(Command command, HandlerContext context) {
        var accountId = (String) command.data().get("account_id");
        var amount = (Integer) command.data().get("amount");

        // Process the debit...

        return Map.of("status", "debited", "balance", 900);
    }
}
```

### 6.4 Send a Command

```java
@Service
public class PaymentService {

    private final CommandBus commandBus;

    public PaymentService(CommandBus commandBus) {
        this.commandBus = commandBus;
    }

    public void processPayment(String accountId, int amount) {
        var result = commandBus.send(
            "payments",
            "DebitAccount",
            UUID.randomUUID(),
            Map.of("account_id", accountId, "amount", amount)
        );

        log.info("Sent command: {}", result.commandId());
    }
}
```

### 6.5 Start the Worker

```java
@Configuration
public class WorkerConfiguration {

    @Bean
    public Worker paymentWorker(
            JdbcTemplate jdbcTemplate,
            HandlerRegistry registry,
            WorkerProperties properties) {

        return Worker.builder()
            .jdbcTemplate(jdbcTemplate)
            .domain("payments")
            .handlerRegistry(registry)
            .visibilityTimeout(properties.getVisibilityTimeout())
            .concurrency(properties.getConcurrency())
            .build();
    }

    @EventListener(ApplicationReadyEvent.class)
    public void startWorker(Worker paymentWorker) {
        paymentWorker.start();
    }
}
```

---

## 7. Functional Acceptance Criteria

### 7.1 Command Sending

| ID | Criterion | Verification |
|----|-----------|--------------|
| CS-1 | Commands are persisted atomically with PGMQ message | Transaction rollback test |
| CS-2 | Duplicate command_id raises DuplicateCommandException | Unit test |
| CS-3 | Correlation ID auto-generated if not provided | Unit test |
| CS-4 | Reply queue configured via reply_to parameter | Integration test |
| CS-5 | Batch commands share batch_id | Integration test |

### 7.2 Command Processing

| ID | Criterion | Verification |
|----|-----------|--------------|
| CP-1 | Handler invoked with correct Command and Context | Unit test |
| CP-2 | Successful completion deletes PGMQ message | Integration test |
| CP-3 | TransientException triggers retry with backoff | Integration test |
| CP-4 | PermanentException moves to TSQ immediately | Integration test |
| CP-5 | Retries exhausted moves to TSQ | Integration test |
| CP-6 | Visibility timeout extended for long handlers | Integration test |

### 7.3 Batch Operations

| ID | Criterion | Verification |
|----|-----------|--------------|
| BO-1 | All batch commands created atomically | Transaction rollback test |
| BO-2 | Batch status transitions: PENDING → IN_PROGRESS → COMPLETED | Integration test |
| BO-3 | Completion callback invoked when all commands done | Integration test |
| BO-4 | Partial failures result in COMPLETED_WITH_FAILURES | Integration test |

### 7.4 Troubleshooting Queue

| ID | Criterion | Verification |
|----|-----------|--------------|
| TQ-1 | operator_retry re-enqueues with attempts=0 | Integration test |
| TQ-2 | operator_cancel sends CANCELED reply | Integration test |
| TQ-3 | operator_complete sends SUCCESS reply | Integration test |
| TQ-4 | TSQ operations update batch counters | Integration test |

---

## 8. Implementation Order

Recommended implementation sequence:

1. **Domain Models** (01) - Foundation for all other components
2. **Exceptions** (part of 01) - Error handling foundation
3. **PGMQ Client** (02) - Low-level queue operations
4. **Repositories** (03) - Data access layer
5. **Handler System** (04) - Handler registration and dispatch
6. **Command Bus** (06) - Sending commands
7. **Worker** (05) - Processing commands
8. **Troubleshooting** (07) - Operator operations
9. **Spring Integration** (08) - Auto-configuration
10. **Testing** (09) - Test utilities and fakes
11. **Process Manager** (10) - Long-running workflow orchestration
12. **E2E Test App** (11) - Thymeleaf test application (test scope only, not shipped)

---

## 9. Compatibility Notes

### 9.1 Python Interoperability

The Java library is designed to be **wire-compatible** with the Python implementation:

- Same database schema and stored procedures
- Same PGMQ message format (JSON)
- Same queue naming convention (`{domain}__commands`)
- Same command lifecycle and status values

This allows:
- Java workers to process commands sent by Python
- Python workers to process commands sent by Java
- Gradual migration between implementations

### 9.2 Breaking Changes to Avoid

- Do not modify the database schema
- Do not change the message payload structure
- Do not alter stored procedure signatures
- Do not change queue naming conventions
