# Common Pitfalls and Anti-Patterns

This document describes common mistakes when working with the Command Bus library. Review before implementing new features.

## Database Operations

### Wrong: Forgetting Transaction Boundaries

```python
# BAD: Operations not in same transaction
async def send_command(self, command: Command) -> None:
    await self.repo.save(command.metadata)  # Transaction 1
    await self.pgmq.send(command.queue, command.payload)  # Transaction 2
    # If PGMQ send fails, metadata is orphaned!
```

```python
# GOOD: All operations in single transaction
async def send_command(self, command: Command) -> None:
    async with self.pool.connection() as conn:
        async with conn.transaction():
            await self.repo.save(command.metadata, conn=conn)
            await self.pgmq.send(command.queue, command.payload, conn=conn)
```

### Wrong: Not Handling Duplicate Commands

```python
# BAD: Assuming send always succeeds
await command_bus.send(domain="payments", command_id=uuid4(), ...)
```

```python
# GOOD: Handle idempotency
try:
    await command_bus.send(domain="payments", command_id=command_id, ...)
except DuplicateCommandError:
    logger.info("Command already exists", extra={"command_id": command_id})
    # Optionally: return existing command status
```

### Wrong: Long-Running Handlers Without VT Extension

```python
# BAD: Handler takes longer than visibility timeout
async def handle_report(command: Command) -> None:
    await generate_large_report()  # Takes 5 minutes
    # Message becomes visible again, processed twice!
```

```python
# GOOD: Extend VT for long operations
async def handle_report(command: Command, context: HandlerContext) -> None:
    for chunk in report_chunks:
        await process_chunk(chunk)
        await context.extend_visibility(seconds=60)  # Keep extending
```

## Async Patterns

### Wrong: Blocking in Async Code

```python
# BAD: Blocking call in async function
async def process(self) -> None:
    time.sleep(1)  # Blocks the event loop!
    result = requests.get(url)  # Also blocking!
```

```python
# GOOD: Use async equivalents
async def process(self) -> None:
    await asyncio.sleep(1)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            result = await response.json()
```

### Wrong: Not Awaiting Coroutines

```python
# BAD: Coroutine created but not awaited
async def cleanup(self) -> None:
    self.pool.close()  # Returns coroutine, doesn't actually close!
```

```python
# GOOD: Always await
async def cleanup(self) -> None:
    await self.pool.close()
```

### Wrong: Fire-and-Forget Without Error Handling

```python
# BAD: Background task errors are lost
asyncio.create_task(self.send_notification())
```

```python
# GOOD: Handle task errors
task = asyncio.create_task(self.send_notification())
task.add_done_callback(self._handle_task_error)

def _handle_task_error(self, task: asyncio.Task) -> None:
    if task.exception():
        logger.error("Background task failed", exc_info=task.exception())
```

## Error Handling

### Wrong: Catching Too Broad

```python
# BAD: Hides all errors, including bugs
try:
    await process_command(command)
except Exception:
    logger.error("Failed")
```

```python
# GOOD: Catch specific exceptions
try:
    await process_command(command)
except TransientCommandError as e:
    logger.warning("Transient failure, will retry", extra={"code": e.code})
    raise  # Let worker handle retry
except PermanentCommandError as e:
    logger.error("Permanent failure", extra={"code": e.code})
    raise  # Move to troubleshooting
except psycopg.OperationalError as e:
    raise TransientCommandError(code="DB_ERROR", message=str(e)) from e
```

### Wrong: Losing Exception Context

```python
# BAD: Original exception lost
except SomeError as e:
    raise TransientCommandError(code="ERROR", message="Failed")
```

```python
# GOOD: Preserve exception chain
except SomeError as e:
    raise TransientCommandError(code="ERROR", message=str(e)) from e
```

## Testing

### Wrong: Testing with Real Database in Unit Tests

```python
# BAD: Unit test depends on PostgreSQL
async def test_send_command():
    bus = CommandBus(connection_string="postgresql://...")
    await bus.send(...)  # Slow, requires setup
```

```python
# GOOD: Use fakes for unit tests
async def test_send_command(fake_pgmq, fake_repo):
    bus = CommandBus(pgmq=fake_pgmq, repo=fake_repo)
    await bus.send(...)  # Fast, isolated
```

### Wrong: Not Testing Error Paths

```python
# BAD: Only tests happy path
async def test_process_command():
    result = await handler.process(valid_command)
    assert result.success
```

```python
# GOOD: Test error scenarios
async def test_process_invalid_command_raises_permanent_error():
    with pytest.raises(PermanentCommandError) as exc_info:
        await handler.process(invalid_command)
    assert exc_info.value.code == "INVALID_DATA"

async def test_process_timeout_raises_transient_error():
    with pytest.raises(TransientCommandError) as exc_info:
        await handler.process(slow_command)
    assert exc_info.value.code == "TIMEOUT"
```

## Configuration

### Wrong: Hardcoding Configuration

```python
# BAD: Values hardcoded
class CommandBus:
    def __init__(self):
        self.max_retries = 3
        self.vt_seconds = 30
```

```python
# GOOD: Configurable with sensible defaults
class CommandBus:
    def __init__(
        self,
        *,
        max_retries: int = 3,
        vt_seconds: int = 30,
    ):
        self.max_retries = max_retries
        self.vt_seconds = vt_seconds
```

### Wrong: Secrets in Code

```python
# BAD: Never do this
DATABASE_URL = "postgresql://user:password@localhost/db"  # pragma: allowlist secret
```

```python
# GOOD: Use environment variables
DATABASE_URL = os.environ["DATABASE_URL"]
```

## Memory and Resources

### Wrong: Not Closing Resources

```python
# BAD: Connection pool never closed
class Worker:
    def __init__(self):
        self.pool = AsyncConnectionPool(...)

    async def run(self):
        while True:
            await self.process_batch()
    # Pool leaks when worker stops
```

```python
# GOOD: Proper lifecycle management
class Worker:
    async def __aenter__(self):
        self.pool = await AsyncConnectionPool(...).open()
        return self

    async def __aexit__(self, *args):
        await self.pool.close()

# Usage
async with Worker() as worker:
    await worker.run()
```

### Wrong: Unbounded Memory Growth

```python
# BAD: Accumulates all results in memory
results = []
async for command in command_stream:
    result = await process(command)
    results.append(result)  # Memory grows forever
```

```python
# GOOD: Process in batches
async for batch in batched(command_stream, size=100):
    results = await asyncio.gather(*[process(cmd) for cmd in batch])
    await save_results(results)  # Persist and free memory
```
