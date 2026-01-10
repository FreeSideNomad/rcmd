"""Command Bus - A Python library for Command Bus over PostgreSQL + PGMQ."""

from commandbus.batch import (
    BatchCompletionCallback,
    check_and_invoke_batch_callback,
    clear_all_callbacks,
    get_batch_callback,
    register_batch_callback,
    remove_batch_callback,
)
from commandbus.bus import CommandBus
from commandbus.exceptions import (
    BatchNotFoundError,
    CommandBusError,
    CommandNotFoundError,
    DuplicateCommandError,
    HandlerAlreadyRegisteredError,
    HandlerNotFoundError,
    InvalidOperationError,
    PermanentCommandError,
    TransientCommandError,
)
from commandbus.handler import HandlerMeta, HandlerRegistry, handler
from commandbus.models import (
    AuditEvent,
    BatchCommand,
    BatchMetadata,
    BatchSendResult,
    BatchStatus,
    Command,
    CommandMetadata,
    CommandStatus,
    CreateBatchResult,
    HandlerContext,
    ReplyOutcome,
    SendRequest,
    SendResult,
    TroubleshootingItem,
)
from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.pgmq.client import PgmqClient, PgmqMessage
from commandbus.policies import DEFAULT_RETRY_POLICY, RetryPolicy
from commandbus.repositories.audit import AuditEventType, PostgresAuditLogger
from commandbus.repositories.batch import PostgresBatchRepository
from commandbus.repositories.command import PostgresCommandRepository
from commandbus.setup import check_schema_exists, get_schema_sql, setup_database
from commandbus.sync import (
    SyncCommandBus,
    SyncProcessReplyRouter,
    SyncWorker,
)
from commandbus.worker import ReceivedCommand, Worker

__all__ = [
    "DEFAULT_RETRY_POLICY",
    "AuditEvent",
    "AuditEventType",
    "BatchCommand",
    "BatchCompletionCallback",
    "BatchMetadata",
    "BatchNotFoundError",
    "BatchSendResult",
    "BatchStatus",
    "Command",
    "CommandBus",
    "CommandBusError",
    "CommandMetadata",
    "CommandNotFoundError",
    "CommandStatus",
    "CreateBatchResult",
    "DuplicateCommandError",
    "HandlerAlreadyRegisteredError",
    "HandlerContext",
    "HandlerMeta",
    "HandlerNotFoundError",
    "HandlerRegistry",
    "InvalidOperationError",
    "PermanentCommandError",
    "PgmqClient",
    "PgmqMessage",
    "PostgresAuditLogger",
    "PostgresBatchRepository",
    "PostgresCommandRepository",
    "ReceivedCommand",
    "ReplyOutcome",
    "RetryPolicy",
    "SendRequest",
    "SendResult",
    "SyncCommandBus",
    "SyncProcessReplyRouter",
    "SyncWorker",
    "TransientCommandError",
    "TroubleshootingItem",
    "TroubleshootingQueue",
    "Worker",
    "__version__",
    "check_and_invoke_batch_callback",
    "check_schema_exists",
    "clear_all_callbacks",
    "get_batch_callback",
    "get_schema_sql",
    "handler",
    "register_batch_callback",
    "remove_batch_callback",
    "setup_database",
]

# Version is set dynamically by hatch-vcs from git tags
try:
    from importlib.metadata import version

    __version__ = version("reliable-cmd")
except Exception:
    __version__ = "0.0.0+unknown"
