# 11. E2E Test Application (Admin UI)

This specification covers the Thymeleaf-based E2E testing application for development and integration testing of the command bus library.

## Important Note

**This is a TEST module only - NOT shipped with the library.**

The E2E test application lives in `src/test/java/com/commandbus/e2e/` and is used for:
- Integration and E2E testing during development
- Manual testing and debugging
- Demonstrating library features

Production applications will implement their own UI using the library's public APIs. This test app serves as a reference implementation and testing tool.

## Overview

The E2E Test App provides:
- Dashboard with system overview statistics
- Command browser with filtering and audit trail
- Troubleshooting Queue (TSQ) management
- Batch progress monitoring
- Process workflow monitoring
- Queue statistics and health
- Command submission forms for testing

## Dependencies

Add to `pom.xml`:

```xml
<dependencies>
    <!-- Thymeleaf -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-thymeleaf</artifactId>
    </dependency>

    <!-- Bootstrap 5 (via WebJars) -->
    <dependency>
        <groupId>org.webjars</groupId>
        <artifactId>bootstrap</artifactId>
        <version>5.3.2</version>
    </dependency>

    <!-- HTMX for partial page updates -->
    <dependency>
        <groupId>org.webjars.npm</groupId>
        <artifactId>htmx.org</artifactId>
        <version>1.9.10</version>
    </dependency>

    <!-- Icons -->
    <dependency>
        <groupId>org.webjars</groupId>
        <artifactId>bootstrap-icons</artifactId>
        <version>1.11.2</version>
    </dependency>
</dependencies>
```

## Project Structure

**Location: `src/test/` (NOT `src/main/`)**

```
src/test/
├── java/com/commandbus/e2e/
│   ├── E2ETestApplication.java        # Spring Boot test application
│   ├── controller/
│   │   ├── DashboardController.java
│   │   ├── CommandController.java
│   │   ├── TsqController.java
│   │   ├── BatchController.java
│   │   ├── ProcessController.java
│   │   ├── QueueController.java
│   │   └── SendCommandController.java  # For submitting test commands
│   ├── dto/
│   │   ├── DashboardStats.java
│   │   ├── CommandView.java
│   │   ├── TsqCommandView.java
│   │   ├── BatchView.java
│   │   ├── ProcessView.java
│   │   └── QueueStats.java
│   ├── service/
│   │   └── E2EService.java
│   └── handlers/
│       └── TestHandlers.java          # Sample handlers for E2E testing
└── resources/
    ├── templates/
    │   ├── layout.html
    │   ├── pages/
    │   │   ├── dashboard.html
    │   │   ├── commands.html
    │   │   ├── send_command.html      # Form to submit test commands
    │   │   ├── tsq.html
    │   │   ├── batches.html
    │   │   ├── batch_detail.html
    │   │   ├── batch_new.html         # Form to create test batches
    │   │   ├── processes_list.html
    │   │   ├── process_detail.html
    │   │   └── queues.html
    │   └── includes/
    │       ├── navbar.html
    │       └── sidebar.html
    ├── static/
    │   └── css/
    │       └── e2e.css
    └── application-e2e.yml            # E2E test configuration
```

---

## Data Transfer Objects

### DashboardStats

```java
package com.commandbus.admin.dto;

public record DashboardStats(
    long pendingCommands,
    long inProgressCommands,
    long tsqCount,
    long activeBatches,
    long completedBatches,
    long runningProcesses,
    long waitingProcesses,
    long totalQueues,
    long totalMessages
) {}
```

### CommandView

```java
package com.commandbus.admin.dto;

import com.commandbus.domain.CommandStatus;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public record CommandView(
    UUID commandId,
    String domain,
    String commandType,
    CommandStatus status,
    Map<String, Object> data,
    UUID correlationId,
    String replyTo,
    UUID batchId,
    int retryCount,
    int maxRetries,
    Instant scheduledAt,
    Instant createdAt,
    Instant updatedAt,
    Instant completedAt,
    String errorCode,
    String errorMessage
) {}
```

### TsqCommandView

```java
package com.commandbus.admin.dto;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public record TsqCommandView(
    long msgId,
    UUID commandId,
    String domain,
    String commandType,
    Map<String, Object> data,
    String errorCode,
    String errorMessage,
    int retryCount,
    Instant enqueuedAt,
    Instant visibleAt
) {}
```

### BatchView

```java
package com.commandbus.admin.dto;

import com.commandbus.domain.BatchStatus;
import java.time.Instant;
import java.util.UUID;

public record BatchView(
    UUID batchId,
    String domain,
    BatchStatus status,
    int totalCommands,
    int completedCommands,
    int failedCommands,
    String callbackQueue,
    Instant createdAt,
    Instant completedAt,
    int progressPercent
) {
    public int progressPercent() {
        if (totalCommands == 0) return 0;
        return (completedCommands * 100) / totalCommands;
    }
}
```

### ProcessView

```java
package com.commandbus.admin.dto;

import com.commandbus.process.ProcessStatus;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public record ProcessView(
    UUID processId,
    String domain,
    String processType,
    ProcessStatus status,
    String currentStep,
    Map<String, Object> state,
    String errorCode,
    String errorMessage,
    Instant createdAt,
    Instant updatedAt,
    Instant completedAt
) {}
```

### QueueStats

```java
package com.commandbus.admin.dto;

public record QueueStats(
    String queueName,
    long queueDepth,
    long archiveSize,
    long messagesPerMinute,
    Instant oldestMessageAt
) {}
```

---

## Admin Service

```java
package com.commandbus.admin.service;

import com.commandbus.admin.dto.*;
import com.commandbus.domain.*;
import com.commandbus.ops.TroubleshootingQueue;
import com.commandbus.pgmq.PgmqClient;
import com.commandbus.process.ProcessRepository;
import com.commandbus.process.ProcessStatus;
import com.commandbus.repository.BatchRepository;
import com.commandbus.repository.CommandRepository;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.*;

@Service
public class AdminService {

    private final JdbcTemplate jdbcTemplate;
    private final CommandRepository commandRepository;
    private final BatchRepository batchRepository;
    private final ProcessRepository processRepository;
    private final TroubleshootingQueue tsq;
    private final PgmqClient pgmqClient;

    public AdminService(
            JdbcTemplate jdbcTemplate,
            CommandRepository commandRepository,
            BatchRepository batchRepository,
            ProcessRepository processRepository,
            TroubleshootingQueue tsq,
            PgmqClient pgmqClient) {
        this.jdbcTemplate = jdbcTemplate;
        this.commandRepository = commandRepository;
        this.batchRepository = batchRepository;
        this.processRepository = processRepository;
        this.tsq = tsq;
        this.pgmqClient = pgmqClient;
    }

    // ========== Dashboard ==========

    @Transactional(readOnly = true)
    public DashboardStats getDashboardStats(String domain) {
        long pending = countCommandsByStatus(domain, CommandStatus.PENDING);
        long inProgress = countCommandsByStatus(domain, CommandStatus.IN_PROGRESS);
        long tsqCount = getTsqCount(domain);
        long activeBatches = countBatchesByStatus(domain, List.of(
            BatchStatus.PENDING, BatchStatus.IN_PROGRESS));
        long completedBatches = countBatchesByStatus(domain, List.of(BatchStatus.COMPLETED));
        long runningProcesses = countProcessesByStatus(domain, List.of(
            ProcessStatus.IN_PROGRESS, ProcessStatus.WAITING_FOR_REPLY));
        long waitingProcesses = countProcessesByStatus(domain, List.of(
            ProcessStatus.WAITING_FOR_TSQ));

        List<QueueStats> queues = getQueueStats(domain);
        long totalQueues = queues.size();
        long totalMessages = queues.stream().mapToLong(QueueStats::queueDepth).sum();

        return new DashboardStats(
            pending, inProgress, tsqCount, activeBatches, completedBatches,
            runningProcesses, waitingProcesses, totalQueues, totalMessages
        );
    }

    // ========== Commands ==========

    @Transactional(readOnly = true)
    public Page<CommandView> getCommands(
            String domain,
            String commandType,
            CommandStatus status,
            Instant fromDate,
            Instant toDate,
            Pageable pageable) {

        StringBuilder sql = new StringBuilder("""
            SELECT command_id, domain, command_type, status, data,
                   correlation_id, reply_to, batch_id, retry_count, max_retries,
                   scheduled_at, created_at, updated_at, completed_at,
                   error_code, error_message
            FROM commandbus.command
            WHERE domain = ?
            """);

        List<Object> params = new ArrayList<>();
        params.add(domain);

        if (commandType != null && !commandType.isBlank()) {
            sql.append(" AND command_type = ?");
            params.add(commandType);
        }
        if (status != null) {
            sql.append(" AND status = ?");
            params.add(status.name());
        }
        if (fromDate != null) {
            sql.append(" AND created_at >= ?");
            params.add(java.sql.Timestamp.from(fromDate));
        }
        if (toDate != null) {
            sql.append(" AND created_at <= ?");
            params.add(java.sql.Timestamp.from(toDate));
        }

        // Count total
        String countSql = "SELECT COUNT(*) FROM (" + sql + ") t";
        long total = jdbcTemplate.queryForObject(countSql, Long.class, params.toArray());

        // Add pagination
        sql.append(" ORDER BY created_at DESC LIMIT ? OFFSET ?");
        params.add(pageable.getPageSize());
        params.add(pageable.getOffset());

        List<CommandView> commands = jdbcTemplate.query(
            sql.toString(),
            (rs, rowNum) -> mapToCommandView(rs),
            params.toArray()
        );

        return new PageImpl<>(commands, pageable, total);
    }

    @Transactional(readOnly = true)
    public Optional<CommandView> getCommandById(String domain, UUID commandId) {
        return commandRepository.getById(domain, commandId)
            .map(this::toCommandView);
    }

    @Transactional(readOnly = true)
    public List<AuditEntry> getCommandAuditTrail(String domain, UUID commandId) {
        return commandRepository.getAuditTrail(domain, commandId);
    }

    // ========== TSQ ==========

    @Transactional(readOnly = true)
    public List<TsqCommandView> getTsqCommands(String domain) {
        return tsq.list(domain).stream()
            .map(this::toTsqView)
            .toList();
    }

    @Transactional
    public void retryTsqCommand(String domain, UUID commandId) {
        tsq.retry(domain, commandId);
    }

    @Transactional
    public void cancelTsqCommand(String domain, UUID commandId, String reason) {
        tsq.cancel(domain, commandId, reason);
    }

    @Transactional
    public void completeTsqCommand(String domain, UUID commandId, Map<String, Object> resultData) {
        tsq.complete(domain, commandId, resultData);
    }

    @Transactional
    public void retryAllTsq(String domain) {
        List<TsqCommandView> commands = getTsqCommands(domain);
        for (TsqCommandView cmd : commands) {
            tsq.retry(domain, cmd.commandId());
        }
    }

    // ========== Batches ==========

    @Transactional(readOnly = true)
    public Page<BatchView> getBatches(
            String domain,
            BatchStatus status,
            Pageable pageable) {

        List<BatchMetadata> batches;
        if (status != null) {
            batches = batchRepository.findByStatus(domain, List.of(status));
        } else {
            batches = batchRepository.findAll(domain, pageable.getPageSize(), (int) pageable.getOffset());
        }

        List<BatchView> views = batches.stream()
            .map(this::toBatchView)
            .toList();

        long total = countBatchesByStatus(domain,
            status != null ? List.of(status) : Arrays.asList(BatchStatus.values()));

        return new PageImpl<>(views, pageable, total);
    }

    @Transactional(readOnly = true)
    public Optional<BatchView> getBatchById(String domain, UUID batchId) {
        return batchRepository.getById(domain, batchId)
            .map(this::toBatchView);
    }

    @Transactional(readOnly = true)
    public Page<CommandView> getBatchCommands(String domain, UUID batchId, Pageable pageable) {
        List<CommandMetadata> commands = commandRepository.findByBatchId(domain, batchId);
        List<CommandView> views = commands.stream()
            .map(this::toCommandView)
            .skip(pageable.getOffset())
            .limit(pageable.getPageSize())
            .toList();

        return new PageImpl<>(views, pageable, commands.size());
    }

    // ========== Processes ==========

    @Transactional(readOnly = true)
    public Page<ProcessView> getProcesses(
            String domain,
            String processType,
            ProcessStatus status,
            Pageable pageable) {

        List<ProcessMetadata<?, ?>> processes;
        if (status != null) {
            processes = processRepository.findByStatus(domain, List.of(status));
        } else if (processType != null && !processType.isBlank()) {
            processes = processRepository.findByType(domain, processType);
        } else {
            processes = processRepository.findByStatus(domain,
                Arrays.asList(ProcessStatus.values()));
        }

        List<ProcessView> views = processes.stream()
            .map(this::toProcessView)
            .skip(pageable.getOffset())
            .limit(pageable.getPageSize())
            .toList();

        return new PageImpl<>(views, pageable, processes.size());
    }

    @Transactional(readOnly = true)
    public Optional<ProcessView> getProcessById(String domain, UUID processId) {
        return processRepository.getById(domain, processId)
            .map(this::toProcessView);
    }

    @Transactional(readOnly = true)
    public List<ProcessAuditEntry> getProcessAuditTrail(String domain, UUID processId) {
        return processRepository.getAuditTrail(domain, processId);
    }

    // ========== Queues ==========

    @Transactional(readOnly = true)
    public List<QueueStats> getQueueStats(String domain) {
        String sql = """
            SELECT queue_name,
                   (SELECT count(*) FROM pgmq.q_{queue}) as depth,
                   (SELECT count(*) FROM pgmq.a_{queue}) as archive_size
            FROM pgmq.meta
            WHERE queue_name LIKE ?
            """;

        // Get all queues for domain
        return jdbcTemplate.query(
            "SELECT queue_name FROM pgmq.meta WHERE queue_name LIKE ?",
            (rs, rowNum) -> {
                String queueName = rs.getString("queue_name");
                return getQueueStatsForQueue(queueName);
            },
            domain + "_%"
        );
    }

    private QueueStats getQueueStatsForQueue(String queueName) {
        String depthSql = "SELECT count(*) FROM pgmq.q_" + queueName;
        String archiveSql = "SELECT count(*) FROM pgmq.a_" + queueName;
        String oldestSql = "SELECT MIN(enqueued_at) FROM pgmq.q_" + queueName;

        long depth = jdbcTemplate.queryForObject(depthSql, Long.class);
        long archive = jdbcTemplate.queryForObject(archiveSql, Long.class);
        java.sql.Timestamp oldest = jdbcTemplate.queryForObject(oldestSql, java.sql.Timestamp.class);

        return new QueueStats(
            queueName,
            depth,
            archive,
            0, // messagesPerMinute - would need metrics tracking
            oldest != null ? oldest.toInstant() : null
        );
    }

    // ========== Helper Methods ==========

    private long countCommandsByStatus(String domain, CommandStatus status) {
        return jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM commandbus.command WHERE domain = ? AND status = ?",
            Long.class, domain, status.name()
        );
    }

    private long getTsqCount(String domain) {
        String tsqQueue = domain + "_tsq";
        try {
            return jdbcTemplate.queryForObject(
                "SELECT count(*) FROM pgmq.q_" + tsqQueue,
                Long.class
            );
        } catch (Exception e) {
            return 0;
        }
    }

    private long countBatchesByStatus(String domain, List<BatchStatus> statuses) {
        String placeholders = String.join(",", statuses.stream().map(s -> "?").toList());
        Object[] params = new Object[statuses.size() + 1];
        params[0] = domain;
        for (int i = 0; i < statuses.size(); i++) {
            params[i + 1] = statuses.get(i).name();
        }

        return jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM commandbus.batch WHERE domain = ? AND status IN (" + placeholders + ")",
            Long.class, params
        );
    }

    private long countProcessesByStatus(String domain, List<ProcessStatus> statuses) {
        String placeholders = String.join(",", statuses.stream().map(s -> "?").toList());
        Object[] params = new Object[statuses.size() + 1];
        params[0] = domain;
        for (int i = 0; i < statuses.size(); i++) {
            params[i + 1] = statuses.get(i).name();
        }

        return jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM commandbus.process WHERE domain = ? AND status IN (" + placeholders + ")",
            Long.class, params
        );
    }

    private CommandView toCommandView(CommandMetadata cmd) {
        return new CommandView(
            cmd.commandId(), cmd.domain(), cmd.commandType(), cmd.status(),
            cmd.data(), cmd.correlationId(), cmd.replyTo(), cmd.batchId(),
            cmd.retryCount(), cmd.maxRetries(), cmd.scheduledAt(),
            cmd.createdAt(), cmd.updatedAt(), cmd.completedAt(),
            cmd.errorCode(), cmd.errorMessage()
        );
    }

    private TsqCommandView toTsqView(TsqMessage msg) {
        return new TsqCommandView(
            msg.msgId(), msg.commandId(), msg.domain(), msg.commandType(),
            msg.data(), msg.errorCode(), msg.errorMessage(),
            msg.retryCount(), msg.enqueuedAt(), msg.visibleAt()
        );
    }

    private BatchView toBatchView(BatchMetadata batch) {
        return new BatchView(
            batch.batchId(), batch.domain(), batch.status(),
            batch.totalCommands(), batch.completedCommands(), batch.failedCommands(),
            batch.callbackQueue(), batch.createdAt(), batch.completedAt(),
            batch.totalCommands() > 0
                ? (batch.completedCommands() * 100) / batch.totalCommands()
                : 0
        );
    }

    private ProcessView toProcessView(ProcessMetadata<?, ?> process) {
        Map<String, Object> stateMap = process.state() instanceof Map
            ? (Map<String, Object>) process.state()
            : process.state().toMap();

        return new ProcessView(
            process.processId(), process.domain(), process.processType(),
            process.status(),
            process.currentStep() != null ? process.currentStep().toString() : null,
            stateMap, process.errorCode(), process.errorMessage(),
            process.createdAt(), process.updatedAt(), process.completedAt()
        );
    }
}
```

---

## Controllers

### DashboardController

```java
package com.commandbus.admin.controller;

import com.commandbus.admin.service.AdminService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

@Controller
@RequestMapping("/admin")
public class DashboardController {

    private final AdminService adminService;
    private final String domain;

    public DashboardController(
            AdminService adminService,
            @Value("${commandbus.domain}") String domain) {
        this.adminService = adminService;
        this.domain = domain;
    }

    @GetMapping
    public String dashboard(Model model) {
        model.addAttribute("stats", adminService.getDashboardStats(domain));
        model.addAttribute("domain", domain);
        return "admin/dashboard";
    }
}
```

### CommandController

```java
package com.commandbus.admin.controller;

import com.commandbus.admin.service.AdminService;
import com.commandbus.domain.CommandStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.util.UUID;

@Controller
@RequestMapping("/admin/commands")
public class CommandController {

    private final AdminService adminService;
    private final String domain;

    public CommandController(
            AdminService adminService,
            @Value("${commandbus.domain}") String domain) {
        this.adminService = adminService;
        this.domain = domain;
    }

    @GetMapping
    public String listCommands(
            @RequestParam(required = false) String commandType,
            @RequestParam(required = false) CommandStatus status,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant to,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            Model model) {

        var commands = adminService.getCommands(
            domain, commandType, status, from, to,
            PageRequest.of(page, size)
        );

        model.addAttribute("commands", commands);
        model.addAttribute("commandType", commandType);
        model.addAttribute("status", status);
        model.addAttribute("from", from);
        model.addAttribute("to", to);
        model.addAttribute("statuses", CommandStatus.values());
        model.addAttribute("domain", domain);

        return "admin/commands/list";
    }

    @GetMapping("/{commandId}")
    public String commandDetail(
            @PathVariable UUID commandId,
            Model model) {

        var command = adminService.getCommandById(domain, commandId);
        if (command.isEmpty()) {
            return "redirect:/admin/commands?error=notfound";
        }

        model.addAttribute("command", command.get());
        model.addAttribute("auditTrail", adminService.getCommandAuditTrail(domain, commandId));
        model.addAttribute("domain", domain);

        return "admin/commands/detail";
    }
}
```

### TsqController

```java
package com.commandbus.admin.controller;

import com.commandbus.admin.service.AdminService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import java.util.Map;
import java.util.UUID;

@Controller
@RequestMapping("/admin/tsq")
public class TsqController {

    private final AdminService adminService;
    private final String domain;

    public TsqController(
            AdminService adminService,
            @Value("${commandbus.domain}") String domain) {
        this.adminService = adminService;
        this.domain = domain;
    }

    @GetMapping
    public String listTsq(Model model) {
        model.addAttribute("commands", adminService.getTsqCommands(domain));
        model.addAttribute("domain", domain);
        return "admin/tsq/list";
    }

    @PostMapping("/{commandId}/retry")
    public String retry(
            @PathVariable UUID commandId,
            RedirectAttributes redirectAttributes) {
        try {
            adminService.retryTsqCommand(domain, commandId);
            redirectAttributes.addFlashAttribute("success", "Command queued for retry");
        } catch (Exception e) {
            redirectAttributes.addFlashAttribute("error", "Failed to retry: " + e.getMessage());
        }
        return "redirect:/admin/tsq";
    }

    @PostMapping("/{commandId}/cancel")
    public String cancel(
            @PathVariable UUID commandId,
            @RequestParam String reason,
            RedirectAttributes redirectAttributes) {
        try {
            adminService.cancelTsqCommand(domain, commandId, reason);
            redirectAttributes.addFlashAttribute("success", "Command canceled");
        } catch (Exception e) {
            redirectAttributes.addFlashAttribute("error", "Failed to cancel: " + e.getMessage());
        }
        return "redirect:/admin/tsq";
    }

    @PostMapping("/{commandId}/complete")
    public String complete(
            @PathVariable UUID commandId,
            @RequestParam String resultJson,
            RedirectAttributes redirectAttributes) {
        try {
            // Parse JSON result
            var objectMapper = new com.fasterxml.jackson.databind.ObjectMapper();
            Map<String, Object> result = objectMapper.readValue(resultJson,
                new com.fasterxml.jackson.core.type.TypeReference<>() {});

            adminService.completeTsqCommand(domain, commandId, result);
            redirectAttributes.addFlashAttribute("success", "Command completed manually");
        } catch (Exception e) {
            redirectAttributes.addFlashAttribute("error", "Failed to complete: " + e.getMessage());
        }
        return "redirect:/admin/tsq";
    }

    @PostMapping("/retry-all")
    public String retryAll(RedirectAttributes redirectAttributes) {
        try {
            adminService.retryAllTsq(domain);
            redirectAttributes.addFlashAttribute("success", "All commands queued for retry");
        } catch (Exception e) {
            redirectAttributes.addFlashAttribute("error", "Failed to retry all: " + e.getMessage());
        }
        return "redirect:/admin/tsq";
    }
}
```

### BatchController

```java
package com.commandbus.admin.controller;

import com.commandbus.admin.service.AdminService;
import com.commandbus.domain.BatchStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

import java.util.UUID;

@Controller
@RequestMapping("/admin/batches")
public class BatchController {

    private final AdminService adminService;
    private final String domain;

    public BatchController(
            AdminService adminService,
            @Value("${commandbus.domain}") String domain) {
        this.adminService = adminService;
        this.domain = domain;
    }

    @GetMapping
    public String listBatches(
            @RequestParam(required = false) BatchStatus status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            Model model) {

        var batches = adminService.getBatches(domain, status, PageRequest.of(page, size));

        model.addAttribute("batches", batches);
        model.addAttribute("status", status);
        model.addAttribute("statuses", BatchStatus.values());
        model.addAttribute("domain", domain);

        return "admin/batches/list";
    }

    @GetMapping("/{batchId}")
    public String batchDetail(
            @PathVariable UUID batchId,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            Model model) {

        var batch = adminService.getBatchById(domain, batchId);
        if (batch.isEmpty()) {
            return "redirect:/admin/batches?error=notfound";
        }

        var commands = adminService.getBatchCommands(domain, batchId, PageRequest.of(page, size));

        model.addAttribute("batch", batch.get());
        model.addAttribute("commands", commands);
        model.addAttribute("domain", domain);

        return "admin/batches/detail";
    }
}
```

### ProcessController

```java
package com.commandbus.admin.controller;

import com.commandbus.admin.service.AdminService;
import com.commandbus.process.ProcessStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

import java.util.UUID;

@Controller
@RequestMapping("/admin/processes")
public class ProcessController {

    private final AdminService adminService;
    private final String domain;

    public ProcessController(
            AdminService adminService,
            @Value("${commandbus.domain}") String domain) {
        this.adminService = adminService;
        this.domain = domain;
    }

    @GetMapping
    public String listProcesses(
            @RequestParam(required = false) String processType,
            @RequestParam(required = false) ProcessStatus status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            Model model) {

        var processes = adminService.getProcesses(
            domain, processType, status, PageRequest.of(page, size));

        model.addAttribute("processes", processes);
        model.addAttribute("processType", processType);
        model.addAttribute("status", status);
        model.addAttribute("statuses", ProcessStatus.values());
        model.addAttribute("domain", domain);

        return "admin/processes/list";
    }

    @GetMapping("/{processId}")
    public String processDetail(
            @PathVariable UUID processId,
            Model model) {

        var process = adminService.getProcessById(domain, processId);
        if (process.isEmpty()) {
            return "redirect:/admin/processes?error=notfound";
        }

        model.addAttribute("process", process.get());
        model.addAttribute("auditTrail", adminService.getProcessAuditTrail(domain, processId));
        model.addAttribute("domain", domain);

        return "admin/processes/detail";
    }
}
```

### QueueController

```java
package com.commandbus.admin.controller;

import com.commandbus.admin.service.AdminService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

@Controller
@RequestMapping("/admin/queues")
public class QueueController {

    private final AdminService adminService;
    private final String domain;

    public QueueController(
            AdminService adminService,
            @Value("${commandbus.domain}") String domain) {
        this.adminService = adminService;
        this.domain = domain;
    }

    @GetMapping
    public String queueStats(Model model) {
        model.addAttribute("queues", adminService.getQueueStats(domain));
        model.addAttribute("domain", domain);
        return "admin/queues/stats";
    }
}
```

---

## Thymeleaf Templates

### Layout Template

```html
<!-- templates/admin/layout.html -->
<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org"
      th:fragment="layout(title, content)">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title th:replace="${title}">Admin</title>

    <!-- Bootstrap CSS -->
    <link rel="stylesheet" th:href="@{/webjars/bootstrap/5.3.2/css/bootstrap.min.css}">
    <!-- Bootstrap Icons -->
    <link rel="stylesheet" th:href="@{/webjars/bootstrap-icons/1.11.2/font/bootstrap-icons.css}">
    <!-- Custom CSS -->
    <link rel="stylesheet" th:href="@{/css/admin.css}">
    <!-- HTMX -->
    <script th:src="@{/webjars/htmx.org/1.9.10/dist/htmx.min.js}"></script>
</head>
<body>
    <!-- Navbar -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" th:href="@{/admin}">
                <i class="bi bi-terminal"></i> Command Bus Admin
            </a>
            <span class="navbar-text text-light">
                Domain: <strong th:text="${domain}">default</strong>
            </span>
        </div>
    </nav>

    <div class="container-fluid">
        <div class="row">
            <!-- Sidebar -->
            <nav class="col-md-2 d-md-block bg-light sidebar">
                <div class="position-sticky pt-3">
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link" th:href="@{/admin}"
                               th:classappend="${#request.requestURI == '/admin'} ? 'active'">
                                <i class="bi bi-speedometer2"></i> Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" th:href="@{/admin/commands}"
                               th:classappend="${#request.requestURI.startsWith('/admin/commands')} ? 'active'">
                                <i class="bi bi-list-task"></i> Commands
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" th:href="@{/admin/tsq}"
                               th:classappend="${#request.requestURI.startsWith('/admin/tsq')} ? 'active'">
                                <i class="bi bi-exclamation-triangle"></i> Troubleshooting
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" th:href="@{/admin/batches}"
                               th:classappend="${#request.requestURI.startsWith('/admin/batches')} ? 'active'">
                                <i class="bi bi-collection"></i> Batches
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" th:href="@{/admin/processes}"
                               th:classappend="${#request.requestURI.startsWith('/admin/processes')} ? 'active'">
                                <i class="bi bi-diagram-3"></i> Processes
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" th:href="@{/admin/queues}"
                               th:classappend="${#request.requestURI.startsWith('/admin/queues')} ? 'active'">
                                <i class="bi bi-inbox"></i> Queues
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>

            <!-- Main content -->
            <main class="col-md-10 ms-sm-auto px-md-4 py-3">
                <!-- Flash messages -->
                <div th:if="${success}" class="alert alert-success alert-dismissible fade show">
                    <span th:text="${success}"></span>
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
                <div th:if="${error}" class="alert alert-danger alert-dismissible fade show">
                    <span th:text="${error}"></span>
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>

                <th:block th:replace="${content}"/>
            </main>
        </div>
    </div>

    <!-- Bootstrap JS -->
    <script th:src="@{/webjars/bootstrap/5.3.2/js/bootstrap.bundle.min.js}"></script>
</body>
</html>
```

### Dashboard Template

```html
<!-- templates/admin/dashboard.html -->
<html xmlns:th="http://www.thymeleaf.org"
      th:replace="~{admin/layout :: layout(~{::title}, ~{::content})}">
<head>
    <title>Dashboard - Command Bus Admin</title>
</head>
<body>
<div th:fragment="content">
    <h2>Dashboard</h2>

    <div class="row mt-4">
        <!-- Commands Card -->
        <div class="col-md-4 mb-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">
                        <i class="bi bi-list-task text-primary"></i> Commands
                    </h5>
                    <div class="row text-center mt-3">
                        <div class="col">
                            <h3 th:text="${stats.pendingCommands}">0</h3>
                            <small class="text-muted">Pending</small>
                        </div>
                        <div class="col">
                            <h3 th:text="${stats.inProgressCommands}">0</h3>
                            <small class="text-muted">In Progress</small>
                        </div>
                    </div>
                </div>
                <div class="card-footer">
                    <a th:href="@{/admin/commands}" class="btn btn-sm btn-outline-primary">View All</a>
                </div>
            </div>
        </div>

        <!-- TSQ Card -->
        <div class="col-md-4 mb-3">
            <div class="card" th:classappend="${stats.tsqCount > 0} ? 'border-warning'">
                <div class="card-body">
                    <h5 class="card-title">
                        <i class="bi bi-exclamation-triangle text-warning"></i> Troubleshooting
                    </h5>
                    <div class="text-center mt-3">
                        <h2 th:text="${stats.tsqCount}"
                            th:classappend="${stats.tsqCount > 0} ? 'text-warning'">0</h2>
                        <small class="text-muted">Commands Requiring Attention</small>
                    </div>
                </div>
                <div class="card-footer">
                    <a th:href="@{/admin/tsq}" class="btn btn-sm btn-outline-warning">Manage TSQ</a>
                </div>
            </div>
        </div>

        <!-- Batches Card -->
        <div class="col-md-4 mb-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">
                        <i class="bi bi-collection text-success"></i> Batches
                    </h5>
                    <div class="row text-center mt-3">
                        <div class="col">
                            <h3 th:text="${stats.activeBatches}">0</h3>
                            <small class="text-muted">Active</small>
                        </div>
                        <div class="col">
                            <h3 th:text="${stats.completedBatches}">0</h3>
                            <small class="text-muted">Completed</small>
                        </div>
                    </div>
                </div>
                <div class="card-footer">
                    <a th:href="@{/admin/batches}" class="btn btn-sm btn-outline-success">View Batches</a>
                </div>
            </div>
        </div>
    </div>

    <div class="row">
        <!-- Processes Card -->
        <div class="col-md-6 mb-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">
                        <i class="bi bi-diagram-3 text-info"></i> Processes
                    </h5>
                    <div class="row text-center mt-3">
                        <div class="col">
                            <h3 th:text="${stats.runningProcesses}">0</h3>
                            <small class="text-muted">Running</small>
                        </div>
                        <div class="col">
                            <h3 th:text="${stats.waitingProcesses}"
                                th:classappend="${stats.waitingProcesses > 0} ? 'text-warning'">0</h3>
                            <small class="text-muted">Waiting for TSQ</small>
                        </div>
                    </div>
                </div>
                <div class="card-footer">
                    <a th:href="@{/admin/processes}" class="btn btn-sm btn-outline-info">View Processes</a>
                </div>
            </div>
        </div>

        <!-- Queues Card -->
        <div class="col-md-6 mb-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">
                        <i class="bi bi-inbox text-secondary"></i> Queues
                    </h5>
                    <div class="row text-center mt-3">
                        <div class="col">
                            <h3 th:text="${stats.totalQueues}">0</h3>
                            <small class="text-muted">Total Queues</small>
                        </div>
                        <div class="col">
                            <h3 th:text="${stats.totalMessages}">0</h3>
                            <small class="text-muted">Total Messages</small>
                        </div>
                    </div>
                </div>
                <div class="card-footer">
                    <a th:href="@{/admin/queues}" class="btn btn-sm btn-outline-secondary">Queue Stats</a>
                </div>
            </div>
        </div>
    </div>
</div>
</body>
</html>
```

### TSQ List Template

```html
<!-- templates/admin/tsq/list.html -->
<html xmlns:th="http://www.thymeleaf.org"
      th:replace="~{admin/layout :: layout(~{::title}, ~{::content})}">
<head>
    <title>Troubleshooting Queue - Command Bus Admin</title>
</head>
<body>
<div th:fragment="content">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="bi bi-exclamation-triangle"></i> Troubleshooting Queue</h2>
        <form th:action="@{/admin/tsq/retry-all}" method="post" th:if="${!commands.isEmpty()}">
            <button type="submit" class="btn btn-warning"
                    onclick="return confirm('Retry all commands?')">
                <i class="bi bi-arrow-clockwise"></i> Retry All
            </button>
        </form>
    </div>

    <div th:if="${commands.isEmpty()}" class="alert alert-success">
        <i class="bi bi-check-circle"></i> No commands in troubleshooting queue
    </div>

    <div th:unless="${commands.isEmpty()}" class="table-responsive">
        <table class="table table-hover">
            <thead>
                <tr>
                    <th>Command ID</th>
                    <th>Type</th>
                    <th>Error</th>
                    <th>Retry Count</th>
                    <th>Enqueued At</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                <tr th:each="cmd : ${commands}">
                    <td>
                        <code th:text="${#strings.abbreviate(cmd.commandId.toString(), 12)}">uuid</code>
                    </td>
                    <td th:text="${cmd.commandType}">Type</td>
                    <td>
                        <span class="badge bg-danger" th:text="${cmd.errorCode}">ERR</span>
                        <small th:text="${#strings.abbreviate(cmd.errorMessage, 50)}">message</small>
                    </td>
                    <td th:text="${cmd.retryCount}">0</td>
                    <td th:text="${#temporals.format(cmd.enqueuedAt, 'yyyy-MM-dd HH:mm:ss')}">time</td>
                    <td>
                        <div class="btn-group btn-group-sm">
                            <!-- Retry -->
                            <form th:action="@{/admin/tsq/{id}/retry(id=${cmd.commandId})}" method="post"
                                  class="d-inline">
                                <button type="submit" class="btn btn-outline-primary" title="Retry">
                                    <i class="bi bi-arrow-clockwise"></i>
                                </button>
                            </form>

                            <!-- Complete -->
                            <button type="button" class="btn btn-outline-success"
                                    data-bs-toggle="modal"
                                    th:data-bs-target="'#completeModal' + ${cmd.commandId}"
                                    title="Complete Manually">
                                <i class="bi bi-check-lg"></i>
                            </button>

                            <!-- Cancel -->
                            <button type="button" class="btn btn-outline-danger"
                                    data-bs-toggle="modal"
                                    th:data-bs-target="'#cancelModal' + ${cmd.commandId}"
                                    title="Cancel">
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>

                        <!-- Complete Modal -->
                        <div class="modal fade" th:id="'completeModal' + ${cmd.commandId}" tabindex="-1">
                            <div class="modal-dialog">
                                <div class="modal-content">
                                    <form th:action="@{/admin/tsq/{id}/complete(id=${cmd.commandId})}" method="post">
                                        <div class="modal-header">
                                            <h5 class="modal-title">Complete Command Manually</h5>
                                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                        </div>
                                        <div class="modal-body">
                                            <div class="mb-3">
                                                <label class="form-label">Result Data (JSON)</label>
                                                <textarea name="resultJson" class="form-control" rows="5"
                                                          placeholder='{"status": "ok"}'>{}</textarea>
                                            </div>
                                        </div>
                                        <div class="modal-footer">
                                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                                            <button type="submit" class="btn btn-success">Complete</button>
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>

                        <!-- Cancel Modal -->
                        <div class="modal fade" th:id="'cancelModal' + ${cmd.commandId}" tabindex="-1">
                            <div class="modal-dialog">
                                <div class="modal-content">
                                    <form th:action="@{/admin/tsq/{id}/cancel(id=${cmd.commandId})}" method="post">
                                        <div class="modal-header">
                                            <h5 class="modal-title">Cancel Command</h5>
                                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                        </div>
                                        <div class="modal-body">
                                            <div class="mb-3">
                                                <label class="form-label">Cancellation Reason</label>
                                                <input type="text" name="reason" class="form-control" required
                                                       placeholder="Enter reason for cancellation">
                                            </div>
                                        </div>
                                        <div class="modal-footer">
                                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                                            <button type="submit" class="btn btn-danger">Cancel Command</button>
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
</body>
</html>
```

### Process Detail Template

```html
<!-- templates/admin/processes/detail.html -->
<html xmlns:th="http://www.thymeleaf.org"
      th:replace="~{admin/layout :: layout(~{::title}, ~{::content})}">
<head>
    <title>Process Detail - Command Bus Admin</title>
</head>
<body>
<div th:fragment="content">
    <nav aria-label="breadcrumb">
        <ol class="breadcrumb">
            <li class="breadcrumb-item"><a th:href="@{/admin}">Dashboard</a></li>
            <li class="breadcrumb-item"><a th:href="@{/admin/processes}">Processes</a></li>
            <li class="breadcrumb-item active" th:text="${process.processId}">ID</li>
        </ol>
    </nav>

    <div class="card mb-4">
        <div class="card-header">
            <h5>Process Details</h5>
        </div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-6">
                    <dl class="row">
                        <dt class="col-sm-4">Process ID</dt>
                        <dd class="col-sm-8"><code th:text="${process.processId}">uuid</code></dd>

                        <dt class="col-sm-4">Type</dt>
                        <dd class="col-sm-8" th:text="${process.processType}">type</dd>

                        <dt class="col-sm-4">Status</dt>
                        <dd class="col-sm-8">
                            <span class="badge"
                                  th:classappend="${process.status.name() == 'COMPLETED'} ? 'bg-success' :
                                                  (${process.status.name() == 'FAILED'} ? 'bg-danger' :
                                                  (${process.status.name() == 'WAITING_FOR_TSQ'} ? 'bg-warning' : 'bg-info'))"
                                  th:text="${process.status}">STATUS</span>
                        </dd>

                        <dt class="col-sm-4">Current Step</dt>
                        <dd class="col-sm-8" th:text="${process.currentStep ?: 'N/A'}">step</dd>
                    </dl>
                </div>
                <div class="col-md-6">
                    <dl class="row">
                        <dt class="col-sm-4">Created At</dt>
                        <dd class="col-sm-8" th:text="${#temporals.format(process.createdAt, 'yyyy-MM-dd HH:mm:ss')}">time</dd>

                        <dt class="col-sm-4">Updated At</dt>
                        <dd class="col-sm-8" th:text="${#temporals.format(process.updatedAt, 'yyyy-MM-dd HH:mm:ss')}">time</dd>

                        <dt class="col-sm-4">Completed At</dt>
                        <dd class="col-sm-8" th:text="${process.completedAt != null ? #temporals.format(process.completedAt, 'yyyy-MM-dd HH:mm:ss') : 'N/A'}">time</dd>
                    </dl>
                </div>
            </div>

            <div th:if="${process.errorCode}" class="alert alert-danger mt-3">
                <strong>Error:</strong> <span th:text="${process.errorCode}">code</span> -
                <span th:text="${process.errorMessage}">message</span>
            </div>
        </div>
    </div>

    <!-- State -->
    <div class="card mb-4">
        <div class="card-header">
            <h5>Process State</h5>
        </div>
        <div class="card-body">
            <pre class="bg-light p-3"><code th:text="${#jackson.writeValueAsString(process.state)}">state</code></pre>
        </div>
    </div>

    <!-- Audit Trail -->
    <div class="card">
        <div class="card-header">
            <h5>Step History</h5>
        </div>
        <div class="card-body">
            <div class="timeline">
                <div th:each="entry : ${auditTrail}" class="timeline-item mb-4">
                    <div class="d-flex">
                        <div class="timeline-marker"
                             th:classappend="${entry.replyOutcome?.name() == 'SUCCESS'} ? 'bg-success' :
                                             (${entry.replyOutcome?.name() == 'FAILED'} ? 'bg-danger' : 'bg-secondary')">
                        </div>
                        <div class="timeline-content ms-3 flex-grow-1">
                            <div class="d-flex justify-content-between">
                                <h6 th:text="${entry.stepName}">Step Name</h6>
                                <small class="text-muted"
                                       th:text="${#temporals.format(entry.sentAt, 'HH:mm:ss')}">time</small>
                            </div>
                            <p class="mb-1">
                                <span class="badge bg-secondary" th:text="${entry.commandType}">type</span>
                                <code class="ms-2" th:text="${#strings.abbreviate(entry.commandId.toString(), 12)}">cmd</code>
                            </p>
                            <div th:if="${entry.replyOutcome}" class="mt-2">
                                <span class="badge"
                                      th:classappend="${entry.replyOutcome.name() == 'SUCCESS'} ? 'bg-success' : 'bg-danger'"
                                      th:text="${entry.replyOutcome}">outcome</span>
                                <small class="text-muted ms-2"
                                       th:if="${entry.receivedAt}"
                                       th:text="'Received: ' + ${#temporals.format(entry.receivedAt, 'HH:mm:ss')}">time</small>
                            </div>
                            <div th:if="${entry.replyOutcome == null}" class="mt-2">
                                <span class="badge bg-warning">Pending</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
</body>
</html>
```

---

## Custom CSS

```css
/* static/css/admin.css */

.sidebar {
    min-height: calc(100vh - 56px);
    border-right: 1px solid #dee2e6;
}

.sidebar .nav-link {
    color: #333;
    padding: 0.75rem 1rem;
}

.sidebar .nav-link.active {
    background-color: #e9ecef;
    font-weight: 600;
}

.sidebar .nav-link:hover {
    background-color: #f8f9fa;
}

.sidebar .nav-link i {
    margin-right: 0.5rem;
}

/* Timeline styles */
.timeline-marker {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-top: 4px;
}

.timeline-item:not(:last-child) .timeline-content {
    border-left: 2px solid #dee2e6;
    padding-left: 1rem;
    margin-left: -1rem;
    padding-bottom: 1rem;
}

/* Progress bar in tables */
.progress-sm {
    height: 0.5rem;
}

/* Status badges */
.badge-pending { background-color: #6c757d; }
.badge-in-progress { background-color: #0d6efd; }
.badge-completed { background-color: #198754; }
.badge-failed { background-color: #dc3545; }
.badge-waiting { background-color: #ffc107; color: #000; }

/* Card hover effect */
.card-hover:hover {
    box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
    transition: box-shadow 0.15s ease-in-out;
}

/* JSON display */
pre code {
    white-space: pre-wrap;
    word-wrap: break-word;
}
```

---

## E2E Test Application

**This is a standalone Spring Boot application for testing, NOT an auto-configuration.**

```java
package com.commandbus.e2e;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * E2E Test Application for CommandBus library.
 *
 * This application is used for:
 * - Integration testing during development
 * - Manual testing and debugging
 * - Demonstrating library features
 *
 * NOT shipped with the library - test scope only.
 */
@SpringBootApplication
public class E2ETestApplication {

    public static void main(String[] args) {
        SpringApplication.run(E2ETestApplication.class, args);
    }
}
```

### Test Handlers

```java
package com.commandbus.e2e.handlers;

import com.commandbus.domain.Command;
import com.commandbus.domain.HandlerContext;
import com.commandbus.exception.PermanentCommandError;
import com.commandbus.exception.TransientCommandError;
import com.commandbus.handler.Handler;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * Sample handlers for E2E testing scenarios.
 */
@Component
public class TestHandlers {

    @Handler(domain = "test", commandType = "SuccessCommand")
    public Map<String, Object> handleSuccess(Command command, HandlerContext context) {
        // Simulates successful processing
        return Map.of(
            "status", "processed",
            "input", command.data()
        );
    }

    @Handler(domain = "test", commandType = "TransientFailCommand")
    public Map<String, Object> handleTransientFail(Command command, HandlerContext context) {
        // Simulates transient failure - will retry
        if (context.attempt() < 3) {
            throw new TransientCommandError("TIMEOUT", "Simulated timeout");
        }
        return Map.of("status", "recovered");
    }

    @Handler(domain = "test", commandType = "PermanentFailCommand")
    public Map<String, Object> handlePermanentFail(Command command, HandlerContext context) {
        // Simulates permanent failure - goes to TSQ immediately
        throw new PermanentCommandError("INVALID_DATA", "Simulated permanent error");
    }

    @Handler(domain = "test", commandType = "SlowCommand")
    public Map<String, Object> handleSlow(Command command, HandlerContext context)
            throws InterruptedException {
        // Simulates long-running command
        int delayMs = (Integer) command.data().getOrDefault("delayMs", 5000);
        Thread.sleep(delayMs);
        return Map.of("status", "completed", "delayMs", delayMs);
    }
}
```

### Configuration (application-e2e.yml)

```yaml
# E2E Test Application Configuration
# Located in src/test/resources/application-e2e.yml

spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/commandbus_test
    username: postgres
    password: postgres

commandbus:
  domain: test
  default-max-attempts: 3
  backoff-schedule: [1, 2, 5]  # Fast retries for testing
  worker:
    visibility-timeout: 30
    poll-interval: 500
    concurrency: 4
    use-notify: true

server:
  port: 8080
```

### Running the E2E Application

```bash
# From project root, run with test profile
mvn spring-boot:run -Dspring-boot.run.profiles=e2e -pl commandbus-spring

# Or run the main class directly
java -jar target/commandbus-spring-tests.jar --spring.profiles.active=e2e
```

---

## Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| AC1 | E2E app is in `src/test/` and NOT shipped with library | Verify JAR contents |
| AC2 | Dashboard shows pending commands, TSQ count, active batches, running processes | Manual UI test |
| AC3 | Command browser supports filtering by type, status, date range | Manual UI test |
| AC4 | Command detail shows full audit trail | Manual UI test |
| AC5 | TSQ list shows all commands with error details | Manual UI test |
| AC6 | TSQ supports Retry, Cancel (with reason), Complete (with result) actions | Manual UI test |
| AC7 | TSQ supports bulk Retry All operation | Manual UI test |
| AC8 | Batch list shows progress bar (completed/total) | Manual UI test |
| AC9 | Batch detail drills down to batch commands | Manual UI test |
| AC10 | Process list shows current step and status | Manual UI test |
| AC11 | Process detail shows step-by-step audit trail | Manual UI test |
| AC12 | Queue stats shows depth and archive size per queue | Manual UI test |
| AC13 | Send Command form can submit test commands | Manual UI test |
| AC14 | Test handlers demonstrate success, transient failure, permanent failure scenarios | E2E test |
| AC15 | Application starts with Testcontainers for database | Integration test |

---

## UI Wireframes

### Dashboard

```
+--------------------------------------------------+
| Command Bus Admin                    Domain: orders|
+--------+-----------------------------------------+
|        |                                         |
| Dash   |  +----------+  +----------+  +-------+  |
| Cmds   |  | Commands |  |   TSQ    |  |Batches|  |
| TSQ    |  |  50  10  |  |    5     |  |  3  7 |  |
| Batch  |  |pend prog |  |attention |  |act cmp|  |
| Proc   |  +----------+  +----------+  +-------+  |
| Queue  |                                         |
|        |  +------------+  +------------+         |
|        |  |  Processes |  |   Queues   |         |
|        |  |   12   2   |  |   5   120  |         |
|        |  |  run  wait |  | queues msg |         |
|        |  +------------+  +------------+         |
+--------+-----------------------------------------+
```

### TSQ Management

```
+--------------------------------------------------+
| Troubleshooting Queue              [Retry All]   |
+--------------------------------------------------+
| Command ID | Type        | Error    | Actions    |
|------------|-------------|----------|------------|
| abc123...  | CreateOrder | TIMEOUT  | [R] [C] [X]|
| def456...  | ProcessPay  | INVALID  | [R] [C] [X]|
+--------------------------------------------------+
[R] = Retry  [C] = Complete  [X] = Cancel
```

### Process Timeline

```
+--------------------------------------------------+
| Process: ORDER_FULFILLMENT                        |
| Status: WAITING_FOR_TSQ  Step: PROCESS_PAYMENT   |
+--------------------------------------------------+
|                                                   |
| Timeline:                                         |
|                                                   |
| [o] RESERVE_INVENTORY                    10:15:30 |
|  |  ReserveInventory cmd-123                      |
|  |  [SUCCESS] 10:15:32                            |
|  |                                                |
| [o] PROCESS_PAYMENT                      10:15:33 |
|  |  ProcessPayment cmd-456                        |
|  |  [FAILED] Payment declined            10:15:35 |
|                                                   |
+--------------------------------------------------+
```

---

## Cross-References

- [06-command-bus.md](06-command-bus.md) - CommandBus API
- [07-troubleshooting.md](07-troubleshooting.md) - TSQ operations
- [10-process.md](10-process.md) - Process manager
- [03-repositories.md](03-repositories.md) - Repository interfaces
