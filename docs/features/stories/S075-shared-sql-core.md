# S075: Shared SQL Core

## User Story

As a developer, I want SQL constants, parameter builders, and row parsers extracted into a shared `_core/` module so that both async and sync implementations can reuse identical database logic without duplication.

## Acceptance Criteria

### AC1: CommandSQL Class
- Given command operations need consistent SQL
- When I import `CommandSQL` from `_core.command_sql`
- Then I have access to: `SAVE`, `GET`, `UPDATE_STATUS`, `SP_RECEIVE`, `SP_FINISH`, `LIST`, `FIND_BY_BATCH`

### AC2: CommandParams Static Methods
- Given I need to build SQL parameters
- When I call `CommandParams.save(metadata, queue_name)`
- Then I get a tuple of 13 parameters matching SAVE SQL placeholders

### AC3: CommandParsers Static Methods
- Given I have a database row tuple
- When I call `CommandParsers.from_row(row)`
- Then I get a properly typed `CommandMetadata` with all 15 fields populated

### AC4: BatchSQL, BatchParams, BatchParsers
- Given batch operations need consistent SQL
- When I use `_core.batch_sql` module
- Then batch operations share SQL across async/sync

### AC5: ProcessSQL, ProcessParams, ProcessParsers
- Given process operations need consistent SQL
- When I use `_core.process_sql` module
- Then process operations share SQL across async/sync

### AC6: PgmqSQL, PgmqParams, PgmqParsers
- Given PGMQ operations need consistent SQL
- When I use `_core.pgmq_sql` module
- Then PGMQ operations share SQL across async/sync

## Implementation Notes

**Files to Create:**
- `src/commandbus/_core/__init__.py`
- `src/commandbus/_core/command_sql.py`
- `src/commandbus/_core/batch_sql.py`
- `src/commandbus/_core/process_sql.py`
- `src/commandbus/_core/pgmq_sql.py`

**Files to Modify:**
- `src/commandbus/repositories/command.py` - Refactor to use _core
- `src/commandbus/repositories/batch.py` - Refactor to use _core
- `src/commandbus/process/repository.py` - Refactor to use _core
- `src/commandbus/pgmq/client.py` - Refactor to use _core

**Code Pattern:**
```python
# _core/command_sql.py
from uuid import UUID
from commandbus.models import CommandMetadata, CommandStatus

class CommandSQL:
    SAVE = """
        INSERT INTO commandbus.command (
            domain, queue_name, msg_id, command_id, command_type,
            status, attempts, max_attempts, correlation_id, reply_queue,
            created_at, updated_at, batch_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    GET = """
        SELECT domain, queue_name, msg_id, command_id, command_type,
               status, attempts, max_attempts, correlation_id, reply_queue,
               created_at, updated_at, completed_at, error_code, error_message,
               batch_id
        FROM commandbus.command
        WHERE domain = %s AND command_id = %s
    """

class CommandParams:
    @staticmethod
    def save(metadata: CommandMetadata, queue_name: str) -> tuple:
        return (
            metadata.domain,
            queue_name,
            str(metadata.msg_id),
            str(metadata.command_id),
            metadata.command_type,
            metadata.status.value,
            metadata.attempts,
            metadata.max_attempts,
            str(metadata.correlation_id) if metadata.correlation_id else None,
            metadata.reply_to,
            metadata.created_at,
            metadata.updated_at,
            str(metadata.batch_id) if metadata.batch_id else None,
        )

class CommandParsers:
    @staticmethod
    def from_row(row: tuple) -> CommandMetadata:
        return CommandMetadata(
            domain=row[0],
            queue_name=row[1],
            msg_id=row[2],
            command_id=UUID(row[3]) if isinstance(row[3], str) else row[3],
            command_type=row[4],
            status=CommandStatus(row[5]),
            attempts=row[6],
            max_attempts=row[7],
            correlation_id=UUID(row[8]) if row[8] else None,
            reply_to=row[9],
            created_at=row[10],
            updated_at=row[11],
            completed_at=row[12],
            error_code=row[13],
            error_message=row[14],
            batch_id=UUID(row[15]) if row[15] else None,
        )
```

**Estimated Lines:** ~300 new, ~200 refactored
