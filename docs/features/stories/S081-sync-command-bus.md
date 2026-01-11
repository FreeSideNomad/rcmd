# S081: Sync Command Bus

## User Story

As a developer, I want a native synchronous CommandBus that sends commands without async overhead so that sync applications have first-class support.

## Acceptance Criteria

### AC1: SyncCommandBus Class
- Given sync pool and dependencies
- When I create `SyncCommandBus(pool)`
- Then I can call sync methods: `send`, `send_batch`

### AC2: send() Method
- Given a Command object
- When I call `send(command, reply_to=None, correlation_id=None)`
- Then command is persisted and enqueued atomically in transaction

### AC3: send_batch() Method
- Given list of Commands
- When I call `send_batch(commands, reply_to=None)`
- Then batch created and all commands persisted atomically

### AC4: Transaction Semantics
- Given send() is called
- When database error occurs
- Then both command table insert and PGMQ enqueue are rolled back

### AC5: Reply Configuration
- Given reply_to queue specified
- When command is sent
- Then reply_to stored in command metadata for worker to use

## Implementation Notes

**File:** `src/commandbus/sync/bus.py`

**Dependencies:**
- `SyncPgmqClient`
- `SyncCommandRepository`
- `SyncBatchRepository`

**Code Pattern:**
```python
from uuid import UUID, uuid4
from psycopg_pool import ConnectionPool
from commandbus.models import Command, SendResult, CommandMetadata, CommandStatus
from commandbus.sync.pgmq import SyncPgmqClient
from commandbus.sync.repositories.command import SyncCommandRepository
from commandbus.sync.repositories.batch import SyncBatchRepository

class SyncCommandBus:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._pgmq = SyncPgmqClient(pool)
        self._repo = SyncCommandRepository(pool)
        self._batch_repo = SyncBatchRepository(pool)

    def send(
        self,
        command: Command,
        *,
        reply_to: str | None = None,
        correlation_id: UUID | None = None,
    ) -> SendResult:
        queue_name = f"{command.domain}__commands"

        with self._pool.connection() as conn:
            with conn.transaction():
                metadata = self._build_metadata(command, reply_to, correlation_id)
                self._repo.save(metadata, queue_name, conn=conn)
                msg_id = self._pgmq.send(queue_name, command.data, conn=conn)
                return SendResult(command_id=metadata.command_id, msg_id=msg_id)

    def send_batch(
        self,
        commands: list[Command],
        *,
        reply_to: str | None = None,
    ) -> BatchSendResult:
        if not commands:
            raise ValueError("Commands list cannot be empty")

        batch_id = uuid4()
        domain = commands[0].domain
        queue_name = f"{domain}__commands"

        with self._pool.connection() as conn:
            with conn.transaction():
                batch = self._create_batch_metadata(batch_id, domain, len(commands))
                self._batch_repo.create(batch, conn=conn)

                results = []
                for command in commands:
                    metadata = self._build_metadata(
                        command, reply_to, batch_id=batch_id
                    )
                    self._repo.save(metadata, queue_name, conn=conn)
                    msg_id = self._pgmq.send(queue_name, command.data, conn=conn)
                    results.append(SendResult(
                        command_id=metadata.command_id, msg_id=msg_id
                    ))

                return BatchSendResult(batch_id=batch_id, commands=results)

    def _build_metadata(
        self,
        command: Command,
        reply_to: str | None,
        correlation_id: UUID | None = None,
        batch_id: UUID | None = None,
    ) -> CommandMetadata:
        now = datetime.now(tz=timezone.utc)
        return CommandMetadata(
            domain=command.domain,
            command_id=command.command_id,
            command_type=command.command_type,
            status=CommandStatus.PENDING,
            attempts=0,
            max_attempts=command.max_attempts,
            correlation_id=correlation_id,
            reply_to=reply_to,
            created_at=now,
            updated_at=now,
            batch_id=batch_id,
        )
```

**Estimated Lines:** ~150 new
