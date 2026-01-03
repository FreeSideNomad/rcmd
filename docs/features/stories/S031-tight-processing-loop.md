# S031: Tight Processing Loop for High Throughput

## Parent Feature

[F002 - Command Processing](../F002-command-processing.md)

## User Story

**As a** platform operator running multiple worker instances
**I want** workers to continuously drain the queue when messages are pending
**So that** high-volume command bursts are processed efficiently without waiting for poll intervals

## Context

When a large batch of commands arrives (e.g., 1000 commands), the current worker implementation processes only one batch per notification cycle. After processing a batch of N commands (where N = concurrency), the worker waits for a new pg_notify signal or poll_interval timeout before processing the next batch. This creates artificial delays even when hundreds of messages are pending.

### Current Behavior (Problem)

With concurrency=4 and poll_interval=10s, processing 1000 commands:
1. Receive notification → process 4 commands → **wait for next notification**
2. Since only ~1 NOTIFY was sent for bulk insert, worker waits 10 seconds
3. Process next 4 commands → wait again
4. Total time: ~2500 seconds (41+ minutes) instead of optimal ~250 seconds

### Desired Behavior

1. Receive notification → process batch of 4 commands
2. Immediately check for more work → process next batch
3. Continue tight loop until queue is empty (receive returns 0 commands)
4. Only then wait for notification or poll_interval
5. Total time for 1000 commands: ~250 seconds (with 1-second average processing)

## Acceptance Criteria (Given-When-Then)

### Scenario: Drain queue continuously when work is available

**Given** a worker is running with concurrency=4
**And** 100 commands are pending in the queue
**When** the worker receives a notification or poll triggers
**Then** the worker processes batches of 4 continuously
**And** does not wait for notifications between batches
**And** only waits for notification/poll when receive() returns empty

### Scenario: Multi-worker coordination remains safe

**Given** 10 worker instances are running on the same queue
**And** 1000 commands are pending
**When** all workers run tight processing loops
**Then** each command is processed exactly once (PGMQ visibility timeout ensures this)
**And** workers do not duplicate work
**And** workers efficiently share the load

### Scenario: No busy-wait when queue is empty

**Given** 10 worker instances are running on the same queue
**And** the queue is empty
**When** all workers check for work
**Then** each worker waits on pg_notify or poll_interval
**And** no worker busy-loops calling receive() repeatedly
**And** database load remains minimal

### Scenario: Immediate wake-up for new work

**Given** a worker is idle waiting for notifications
**And** a new command is sent to the queue
**When** pg_notify is received
**Then** the worker immediately enters the tight processing loop
**And** processes all available work before returning to wait state

### Scenario: Backpressure when all slots are busy

**Given** a worker with concurrency=4
**And** 4 commands are currently being processed (all slots busy)
**When** more commands are available in the queue
**Then** the worker waits for at least one slot to become available
**And** immediately fetches more work when a slot frees up
**And** does not drop or ignore pending commands

## Technical Design

### Processing Loop Algorithm

```python
async def _run_with_notify(self, semaphore, poll_interval):
    await listen_conn.set_autocommit(True)
    await listen_conn.execute(f"LISTEN {channel}")

    while not stop_event.is_set():
        # TIGHT LOOP: Process all available work
        while not stop_event.is_set():
            available_slots = semaphore._value

            if available_slots == 0:
                # All workers busy - wait for any to complete
                await self._wait_for_slot()
                continue

            commands = await self.receive(batch_size=available_slots)

            if not commands:
                # Queue empty (for this worker) - exit tight loop
                break

            # Spawn concurrent processing tasks
            for cmd in commands:
                task = asyncio.create_task(self._process_command(cmd, semaphore))
                self._in_flight.add(task)
                task.add_done_callback(self._in_flight.discard)

        # IDLE: Wait for notification or poll timeout
        try:
            gen = listen_conn.notifies(timeout=poll_interval)
            async for _ in gen:
                break  # Wake up, return to tight loop
        except TimeoutError:
            pass  # Poll fallback
```

### Multi-Worker Safety

- **PGMQ Atomicity**: `pgmq.read()` atomically claims messages with visibility timeout
- **No Coordination Needed**: Each worker independently reads what's available
- **Thundering Herd Mitigation**: When queue empties, workers naturally spread out waiting for notifications
- **Optional Jitter**: Small random delay (0-10ms) after notification to reduce contention

### Key Invariants

1. `receive()` returning empty means no more work **for this worker** (other workers may have claimed messages)
2. Tight loop runs only while work exists - no busy-wait on empty queue
3. Notification/poll wait only happens when queue appears empty
4. Backpressure is handled by waiting for semaphore slots

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Continuous drain | Integration | `tests/integration/test_worker.py::test_tight_loop_drains_queue` |
| Multi-worker safety | Integration | `tests/integration/test_worker.py::test_multi_worker_no_duplicates` |
| No busy-wait | Unit | `tests/unit/test_worker.py::test_no_busy_wait_on_empty` |
| Backpressure | Unit | `tests/unit/test_worker.py::test_waits_for_slot` |

## Story Size

M (2000-5000 tokens, refactoring existing module)

## Priority (MoSCoW)

Should Have (performance optimization for production workloads)

## Dependencies

- S007: Run worker with concurrency (must be working)
- Issue #108: pg_notify must be working (NOTIFY on send + autocommit on listen)

## Technical Notes

- Use `asyncio.wait()` with `FIRST_COMPLETED` to wait for any slot to free up
- Consider adding metrics: batches_processed, empty_receives, notification_wakeups
- The `poll_interval` becomes a fallback, not the primary pacing mechanism
- Existing graceful shutdown logic remains unchanged

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/worker.py` - Worker class, `_run_with_notify()` method
- `docs/features/stories/S007-worker-concurrency.md` - Related story

**Constraints:**
- Must maintain backward compatibility with existing Worker API
- Must not change behavior when queue has low volume (single commands)
- Must handle `asyncio.CancelledError` for graceful shutdown
- Must not starve other asyncio coroutines (use `await` appropriately)

**Implementation Steps:**
1. Refactor `_run_with_notify()` to use nested while loops
2. Add `_wait_for_slot()` helper method
3. Update unit tests to verify tight loop behavior
4. Add integration test for queue draining performance

**Verification Steps:**
1. Run `make test-unit` - all tests pass
2. Run E2E demo with 100+ commands, verify continuous processing
3. Run multiple worker instances, verify no duplicate processing

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration test for queue draining
- [ ] E2E verification with bulk commands
- [ ] No regressions in graceful shutdown
- [ ] Documentation updated
