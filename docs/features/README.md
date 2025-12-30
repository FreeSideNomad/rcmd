# Features & User Stories

This directory contains feature specifications and user stories for the Command Bus library.

## Feature Index

| ID | Feature | Priority | Status |
|----|---------|----------|--------|
| [F001](F001-command-sending.md) | Command Sending | Must Have | Planned |
| [F002](F002-command-processing.md) | Command Processing | Must Have | Planned |
| [F003](F003-retry-error-handling.md) | Retry & Error Handling | Must Have | Planned |
| [F004](F004-troubleshooting-queue.md) | Troubleshooting Queue | Must Have | Planned |
| [F005](F005-observability.md) | Observability & Audit | Should Have | Planned |

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

## Document Format

All features and stories follow the format defined in `.github/ISSUE_TEMPLATE/` to ensure consistency when creating GitHub issues.
