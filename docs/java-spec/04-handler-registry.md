# Handler System Specification

## Overview

This specification defines the handler registration and dispatch system for the Java Command Bus library. Handlers are registered via Spring annotations and invoked by the worker to process commands.

## Package Structure

```
com.commandbus.handler/
├── Handler.java                    # Annotation
├── HandlerRegistry.java            # Interface
├── CommandHandler.java             # Functional interface
└── impl/
    └── DefaultHandlerRegistry.java # Implementation
```

---

## 1. Handler Annotation

### 1.1 @Handler Annotation

```java
package com.commandbus.handler;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as a command handler.
 *
 * <p>Methods annotated with @Handler are automatically discovered and registered
 * by the HandlerRegistry when component scanning is enabled.
 *
 * <p>Handler methods must have the signature:
 * <pre>
 * Object handleXxx(Command command, HandlerContext context)
 * </pre>
 *
 * <p>The return value is serialized as JSON and included in the reply message
 * if reply_to is configured. Return null for no result.
 *
 * <p>Example:
 * <pre>
 * {@literal @}Component
 * public class PaymentHandlers {
 *
 *     {@literal @}Handler(domain = "payments", commandType = "DebitAccount")
 *     public Map<String, Object> handleDebit(Command command, HandlerContext context) {
 *         var amount = (Integer) command.data().get("amount");
 *         // Process debit...
 *         return Map.of("status", "debited", "balance", 900);
 *     }
 * }
 * </pre>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface Handler {

    /**
     * The domain this handler processes commands for.
     *
     * @return domain name (e.g., "payments")
     */
    String domain();

    /**
     * The command type this handler processes.
     *
     * @return command type (e.g., "DebitAccount")
     */
    String commandType();
}
```

---

## 2. Functional Interface

### 2.1 CommandHandler

```java
package com.commandbus.handler;

import com.commandbus.model.Command;
import com.commandbus.model.HandlerContext;

/**
 * Functional interface for command handlers.
 *
 * <p>Handlers process commands and optionally return a result that is
 * included in the reply message.
 *
 * <p>Handlers can throw:
 * <ul>
 *   <li>{@link com.commandbus.exception.TransientCommandException} - for retryable failures</li>
 *   <li>{@link com.commandbus.exception.PermanentCommandException} - for non-retryable failures</li>
 *   <li>Any other exception - treated as transient failure</li>
 * </ul>
 */
@FunctionalInterface
public interface CommandHandler {

    /**
     * Process a command.
     *
     * @param command The command to process
     * @param context Handler context with metadata and utilities
     * @return Optional result to include in reply (may be null)
     * @throws Exception on processing failure
     */
    Object handle(Command command, HandlerContext context) throws Exception;
}
```

---

## 3. Registry Interface

### 3.1 HandlerRegistry

```java
package com.commandbus.handler;

import com.commandbus.model.Command;
import com.commandbus.model.HandlerContext;

import java.util.List;
import java.util.Optional;

/**
 * Registry for command handlers.
 *
 * <p>Maps (domain, commandType) pairs to handler functions. The registry
 * discovers handlers via Spring component scanning and @Handler annotations.
 */
public interface HandlerRegistry {

    /**
     * Register a handler for a command type.
     *
     * @param domain The domain (e.g., "payments")
     * @param commandType The command type (e.g., "DebitAccount")
     * @param handler The handler function
     * @throws com.commandbus.exception.HandlerAlreadyRegisteredException if handler exists
     */
    void register(String domain, String commandType, CommandHandler handler);

    /**
     * Get the handler for a command type.
     *
     * @param domain The domain
     * @param commandType The command type
     * @return Optional containing the handler if found
     */
    Optional<CommandHandler> get(String domain, String commandType);

    /**
     * Get the handler for a command type, throwing if not found.
     *
     * @param domain The domain
     * @param commandType The command type
     * @return The handler
     * @throws com.commandbus.exception.HandlerNotFoundException if not found
     */
    CommandHandler getOrThrow(String domain, String commandType);

    /**
     * Dispatch a command to its registered handler.
     *
     * @param command The command to dispatch
     * @param context Handler context
     * @return Result from handler (may be null)
     * @throws com.commandbus.exception.HandlerNotFoundException if no handler registered
     * @throws Exception from handler execution
     */
    Object dispatch(Command command, HandlerContext context) throws Exception;

    /**
     * Check if a handler is registered.
     *
     * @param domain The domain
     * @param commandType The command type
     * @return true if handler is registered
     */
    boolean hasHandler(String domain, String commandType);

    /**
     * Get list of all registered (domain, commandType) pairs.
     *
     * @return List of registered handler keys
     */
    List<HandlerKey> registeredHandlers();

    /**
     * Remove all handlers. Useful for testing.
     */
    void clear();

    /**
     * Scan a Spring bean for @Handler annotated methods and register them.
     *
     * @param bean The bean to scan
     * @return List of registered handler keys
     */
    List<HandlerKey> registerBean(Object bean);

    /**
     * Key for handler lookup.
     */
    record HandlerKey(String domain, String commandType) {}
}
```

---

## 4. Implementation

### 4.1 DefaultHandlerRegistry

```java
package com.commandbus.handler.impl;

import com.commandbus.exception.HandlerAlreadyRegisteredException;
import com.commandbus.exception.HandlerNotFoundException;
import com.commandbus.handler.CommandHandler;
import com.commandbus.handler.Handler;
import com.commandbus.handler.HandlerRegistry;
import com.commandbus.model.Command;
import com.commandbus.model.HandlerContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Default implementation of HandlerRegistry.
 *
 * <p>Implements BeanPostProcessor to automatically discover and register
 * handlers from Spring beans annotated with @Handler.
 */
@Component
public class DefaultHandlerRegistry implements HandlerRegistry, BeanPostProcessor {

    private static final Logger log = LoggerFactory.getLogger(DefaultHandlerRegistry.class);

    private final Map<HandlerKey, CommandHandler> handlers = new ConcurrentHashMap<>();

    @Override
    public void register(String domain, String commandType, CommandHandler handler) {
        var key = new HandlerKey(domain, commandType);
        if (handlers.containsKey(key)) {
            throw new HandlerAlreadyRegisteredException(domain, commandType);
        }
        handlers.put(key, handler);
        log.debug("Registered handler for {}.{}", domain, commandType);
    }

    @Override
    public Optional<CommandHandler> get(String domain, String commandType) {
        return Optional.ofNullable(handlers.get(new HandlerKey(domain, commandType)));
    }

    @Override
    public CommandHandler getOrThrow(String domain, String commandType) {
        return get(domain, commandType)
            .orElseThrow(() -> new HandlerNotFoundException(domain, commandType));
    }

    @Override
    public Object dispatch(Command command, HandlerContext context) throws Exception {
        var handler = getOrThrow(command.domain(), command.commandType());
        log.debug("Dispatching {}.{} (commandId={})",
            command.domain(), command.commandType(), command.commandId());
        return handler.handle(command, context);
    }

    @Override
    public boolean hasHandler(String domain, String commandType) {
        return handlers.containsKey(new HandlerKey(domain, commandType));
    }

    @Override
    public List<HandlerKey> registeredHandlers() {
        return List.copyOf(handlers.keySet());
    }

    @Override
    public void clear() {
        handlers.clear();
    }

    @Override
    public List<HandlerKey> registerBean(Object bean) {
        List<HandlerKey> registered = new ArrayList<>();

        for (Method method : bean.getClass().getMethods()) {
            Handler annotation = method.getAnnotation(Handler.class);
            if (annotation == null) {
                continue;
            }

            // Validate method signature
            validateHandlerMethod(method);

            String domain = annotation.domain();
            String commandType = annotation.commandType();

            // Create handler that invokes the method
            CommandHandler handler = (command, context) -> {
                return method.invoke(bean, command, context);
            };

            register(domain, commandType, handler);
            registered.add(new HandlerKey(domain, commandType));

            log.info("Discovered handler {}.{}() for {}.{}",
                bean.getClass().getSimpleName(), method.getName(), domain, commandType);
        }

        return registered;
    }

    /**
     * BeanPostProcessor callback - scans beans for @Handler methods.
     */
    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) {
        // Check if bean has any @Handler annotated methods
        boolean hasHandlers = Arrays.stream(bean.getClass().getMethods())
            .anyMatch(m -> m.isAnnotationPresent(Handler.class));

        if (hasHandlers) {
            registerBean(bean);
        }

        return bean;
    }

    private void validateHandlerMethod(Method method) {
        Class<?>[] params = method.getParameterTypes();
        if (params.length != 2 ||
            !params[0].equals(Command.class) ||
            !params[1].equals(HandlerContext.class)) {

            throw new IllegalArgumentException(
                "Handler method " + method.getName() + " must have signature: " +
                "Object methodName(Command command, HandlerContext context)"
            );
        }
    }
}
```

---

## 5. Handler Implementation Patterns

### 5.1 Basic Handler

```java
@Component
public class PaymentHandlers {

    private final PaymentService paymentService;

    public PaymentHandlers(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @Handler(domain = "payments", commandType = "DebitAccount")
    public Map<String, Object> handleDebit(Command command, HandlerContext context) {
        var accountId = (String) command.data().get("account_id");
        var amount = ((Number) command.data().get("amount")).intValue();

        var result = paymentService.debit(accountId, amount);

        return Map.of(
            "status", "debited",
            "newBalance", result.balance(),
            "transactionId", result.transactionId()
        );
    }

    @Handler(domain = "payments", commandType = "CreditAccount")
    public Map<String, Object> handleCredit(Command command, HandlerContext context) {
        var accountId = (String) command.data().get("account_id");
        var amount = ((Number) command.data().get("amount")).intValue();

        var result = paymentService.credit(accountId, amount);

        return Map.of("status", "credited", "newBalance", result.balance());
    }
}
```

### 5.2 Handler with Error Handling

```java
@Component
public class OrderHandlers {

    @Handler(domain = "orders", commandType = "CreateOrder")
    public Map<String, Object> handleCreateOrder(Command command, HandlerContext context) {
        var customerId = (String) command.data().get("customer_id");
        var items = (List<?>) command.data().get("items");

        // Validation - permanent failure
        if (customerId == null || customerId.isBlank()) {
            throw new PermanentCommandException(
                "INVALID_CUSTOMER",
                "Customer ID is required"
            );
        }

        // External service call - transient failure
        try {
            var order = orderService.createOrder(customerId, items);
            return Map.of("orderId", order.getId());
        } catch (ServiceUnavailableException e) {
            throw new TransientCommandException(
                "SERVICE_UNAVAILABLE",
                "Order service temporarily unavailable",
                Map.of("retryAfter", 30)
            );
        }
    }
}
```

### 5.3 Long-Running Handler with Visibility Extension

```java
@Component
public class ReportHandlers {

    @Handler(domain = "reports", commandType = "GenerateReport")
    public Map<String, Object> handleGenerateReport(Command command, HandlerContext context) {
        var reportType = (String) command.data().get("type");

        // Long-running operation - extend visibility
        if ("comprehensive".equals(reportType)) {
            context.extendVisibility(120); // Extend to 2 minutes
        }

        var report = reportService.generate(reportType);

        return Map.of(
            "reportId", report.getId(),
            "downloadUrl", report.getUrl()
        );
    }
}
```

### 5.4 Handler with Retry-Aware Logic

```java
@Component
public class NotificationHandlers {

    @Handler(domain = "notifications", commandType = "SendEmail")
    public void handleSendEmail(Command command, HandlerContext context) {
        var recipient = (String) command.data().get("to");
        var subject = (String) command.data().get("subject");

        // Adjust behavior based on attempt
        if (context.isLastAttempt()) {
            log.warn("Last attempt to send email to {}", recipient);
            // Maybe use fallback delivery method
        }

        try {
            emailService.send(recipient, subject);
        } catch (DeliveryException e) {
            if (context.isLastAttempt()) {
                // On last attempt, fail permanently to avoid retry loop
                throw new PermanentCommandException(
                    "DELIVERY_FAILED",
                    "Could not deliver email after " + context.maxAttempts() + " attempts"
                );
            }
            throw new TransientCommandException("DELIVERY_FAILED", e.getMessage());
        }
    }
}
```

---

## 6. Programmatic Registration

### 6.1 Manual Registration

```java
@Configuration
public class HandlerConfiguration {

    @Bean
    public CommandRunner registerHandlers(HandlerRegistry registry, PaymentService paymentService) {
        return args -> {
            // Register lambda handler
            registry.register("payments", "QuickDebit", (command, context) -> {
                var amount = (Integer) command.data().get("amount");
                paymentService.quickDebit(amount);
                return null;
            });

            // Register method reference
            registry.register("payments", "RefundPayment",
                paymentService::handleRefund);
        };
    }
}
```

### 6.2 Dynamic Registration

```java
@Service
public class DynamicHandlerService {

    private final HandlerRegistry registry;

    public void registerWorkflowHandler(String workflowId, CommandHandler handler) {
        registry.register("workflows", "Execute_" + workflowId, handler);
    }

    public void unregisterWorkflowHandler(String workflowId) {
        // Note: Would need to add remove() to interface
    }
}
```

---

## 7. Thread Safety

The `DefaultHandlerRegistry` uses `ConcurrentHashMap` for thread-safe handler storage. Handlers are typically registered during application startup and read during processing, making this pattern safe.

```java
// Thread-safe registration (typically at startup)
registry.register("domain", "type", handler);

// Thread-safe dispatch (concurrent from multiple workers)
registry.dispatch(command, context);
```

---

## 8. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| HR-1 | @Handler methods auto-discovered at startup | Integration test |
| HR-2 | Handlers invoked with correct Command and Context | Unit test |
| HR-3 | HandlerNotFoundException thrown for missing handler | Unit test |
| HR-4 | HandlerAlreadyRegisteredException on duplicate | Unit test |
| HR-5 | Handler return value available for reply | Unit test |
| HR-6 | TransientCommandException properly propagated | Unit test |
| HR-7 | PermanentCommandException properly propagated | Unit test |
| HR-8 | Method signature validated at registration | Unit test |
| HR-9 | registeredHandlers() returns all handlers | Unit test |
| HR-10 | clear() removes all handlers | Unit test |
