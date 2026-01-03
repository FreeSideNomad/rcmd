# Features & User Stories

This directory contains feature specifications and user stories for the Command Bus library.

## Development Plan

See [development-plan.md](development-plan.md) for the implementation sequence and milestones.

## Feature Index

| ID | Feature | Priority | Status |
|----|---------|----------|--------|
| [F001](F001-command-sending.md) | Command Sending | Must Have | Planned |
| [F002](F002-command-processing.md) | Command Processing | Must Have | Planned |
| [F003](F003-retry-error-handling.md) | Retry & Error Handling | Must Have | Planned |
| [F004](F004-troubleshooting-queue.md) | Troubleshooting Queue | Must Have | Planned |
| [F005](F005-observability.md) | Observability & Audit | Should Have | Planned |
| [F006](F006-e2e-testing-demo.md) | E2E Testing & Demo App | Should Have | Complete |
| [F007](F007-handler-dependency-injection.md) | Handler DI & Transactions | Should Have | Planned |
| [F008](F008-e2e-fastapi-migration.md) | E2E FastAPI Migration | Should Have | Planned |

## User Story Index

Stories are organized by parent feature. Each story follows INVEST criteria and includes Given-When-Then acceptance criteria.

### F001 - Command Sending
- [S001](stories/S001-send-command.md) - Send a command
- [S002](stories/S002-idempotent-send.md) - Idempotent command sending
- [S003](stories/S003-send-with-correlation.md) - Send with correlation ID

### F002 - Command Processing
- [S004](stories/S004-receive-command.md) - Receive and process command
- [S005](stories/S005-complete-command.md) - Complete command successfully
- [S006](stories/S006-register-handler.md) - Register command handler
- [S007](stories/S007-worker-concurrency.md) - Run worker with concurrency

### F003 - Retry & Error Handling
- [S008](stories/S008-transient-retry.md) - Automatic retry on transient failure
- [S009](stories/S009-permanent-failure.md) - Handle permanent failure
- [S010](stories/S010-retry-exhaustion.md) - Handle retry exhaustion

### F004 - Troubleshooting Queue
- [S011](stories/S011-list-troubleshooting.md) - List commands in troubleshooting
- [S012](stories/S012-operator-retry.md) - Operator retry command
- [S013](stories/S013-operator-cancel.md) - Operator cancel command
- [S014](stories/S014-operator-complete.md) - Operator complete command

### F005 - Observability
- [S015](stories/S015-audit-trail.md) - Audit trail for commands
- [S016](stories/S016-query-commands.md) - Query commands by status

### F006 - E2E Testing & Demo Application
- [S017](stories/S017-base-infrastructure.md) - Base Infrastructure Setup
- [S018](stories/S018-send-command-view.md) - Send Command View
- [S019](stories/S019-commands-browser-view.md) - Commands Browser View
- [S020](stories/S020-troubleshooting-queue-view.md) - Troubleshooting Queue View
- [S021](stories/S021-audit-trail-view.md) - Audit Trail View
- [S022](stories/S022-dashboard-view.md) - Dashboard View
- [S023](stories/S023-e2e-tests-success.md) - E2E Tests - Success Scenarios
- [S024](stories/S024-e2e-tests-failure.md) - E2E Tests - Failure Scenarios
- [S025](stories/S025-load-testing.md) - Load Testing Support

### F007 - Handler Dependency Injection & Transactions
- [S026](stories/S026-handler-decorator-class.md) - Use @handler decorator on class methods
- [S027](stories/S027-register-instance.md) - Discover handlers via register_instance()
- [S028](stories/S028-transaction-participation.md) - Handler participates in worker transaction
- [S029](stories/S029-stateless-service-pattern.md) - Implement stateless service pattern
- [S030](stories/S030-composition-root.md) - Wire dependencies in composition root

### F008 - E2E FastAPI Migration (depends on F007)
- S031 - FastAPI Application Factory with Composition Root (uses F007)
- S032 - Dependency Injection Setup (uses F007)
- S033 - Command Endpoints Migration
- S034 - Stats Endpoints Migration
- S035 - TSQ Endpoints Migration
- S036 - Audit Endpoints Migration
- S037 - Pydantic Schema Definitions
- S038 - Web Routes with Jinja2
- S039 - OpenAPI Documentation Review
- S040 - Handler Classes with @handler Decorator (uses F007)

## Document Format

All features and stories follow the format defined in `.github/ISSUE_TEMPLATE/` to ensure consistency when creating GitHub issues.
