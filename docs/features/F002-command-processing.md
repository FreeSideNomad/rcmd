# F002: Command Processing

## Summary

Enable workers to receive, process, and complete commands from domain queues with visibility timeout guarantees.

## Motivation

Commands sent to queues need to be:
- Leased by workers with visibility timeout (preventing duplicate processing)
- Dispatched to registered handlers based on command type
- Completed or failed with appropriate state transitions
- Processed concurrently for throughput

This feature provides the worker infrastructure and handler registry for reliable command processing.

## User Stories

- [S004](stories/S004-receive-command.md) - Receive and lease a command
- [S005](stories/S005-complete-command.md) - Complete command successfully
- [S006](stories/S006-register-handler.md) - Register command handler
- [S007](stories/S007-worker-concurrency.md) - Run worker with concurrency

## Acceptance Criteria (Feature-Level)

- [ ] Workers receive commands via `pgmq.read()` with visibility timeout
- [ ] Commands are dispatched to registered handlers by type
- [ ] Successful processing calls `pgmq.delete()` and updates status to COMPLETED
- [ ] Reply message is sent to reply queue on completion
- [ ] Worker supports configurable concurrency
- [ ] pg_notify/LISTEN reduces polling latency (with fallback)
- [ ] Audit events recorded for RECEIVED and COMPLETED

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Worker                              │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  Receiver   │───▶│  Dispatcher │───▶│  Completer  │  │
│  │  (PGMQ read)│    │  (Handler)  │    │  (delete)   │  │
│  └─────────────┘    └─────────────┘    └─────────────┘  │
│         │                  │                  │          │
│         ▼                  ▼                  ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Handler Registry                    │    │
│  │  domain + command_type → handler_fn              │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Dependencies

- F001: Command Sending (commands must exist to process)
- psycopg3 async support
- asyncio for concurrency

### Data Changes

Updates to existing tables:
- `command_bus_command.status` → COMPLETED
- `command_bus_command.attempts` incremented on receive
- `command_bus_audit` entries for RECEIVED, COMPLETED

### API Changes

```python
class CommandBus:
    def register_handler(
        self,
        domain: str,
        command_type: str,
        handler: Callable[[Command, HandlerContext], Awaitable[Any]],
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Register a handler for a command type."""

    async def run_worker(
        self,
        domain: str,
        *,
        concurrency: int = 10,
        vt_seconds: int = 30,
        use_notify: bool = True,
    ) -> None:
        """Run a worker for the specified domain."""

    async def stop(self) -> None:
        """Gracefully stop all workers."""
```

## Out of Scope

- Handler timeout enforcement (rely on VT)
- Dead letter queue (use troubleshooting queue)
- Handler middleware/interceptors (future)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Handler blocks event loop | High | Document async requirements, provide sync wrapper |
| VT expires during processing | Medium | Provide VT extension API in HandlerContext |
| No handler registered | Medium | Log warning, archive message, don't retry |
| Worker crash mid-processing | Low | Message reappears after VT, at-least-once is expected |

## Implementation Milestones

- [ ] Milestone 1: Basic receive and dispatch
- [ ] Milestone 2: Handler registry
- [ ] Milestone 3: Complete with reply
- [ ] Milestone 4: Concurrency and graceful shutdown
- [ ] Milestone 5: pg_notify/LISTEN optimization

## LLM Agent Notes

**Reference Files:**
- `src/commandbus/worker.py` - Worker implementation
- `src/commandbus/handler.py` - Handler registry
- `src/commandbus/pgmq/client.py` - PGMQ read/delete
- `src/commandbus/pgmq/notify.py` - LISTEN implementation

**Patterns to Follow:**
- Use `asyncio.TaskGroup` for concurrent processing
- Graceful shutdown with `asyncio.Event`
- Context manager for worker lifecycle

**Constraints:**
- Handlers must be async functions
- Must not block the event loop
- Must handle `asyncio.CancelledError` for shutdown

**Verification Steps:**
1. `make test-unit` - Handler dispatch tests
2. `make test-integration` - Full receive/complete cycle
3. `make test-e2e` - Producer → Worker → Reply flow
