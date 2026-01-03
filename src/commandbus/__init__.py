"""Command Bus - A Python library for Command Bus over PostgreSQL + PGMQ."""

from commandbus.bus import CommandBus
from commandbus.exceptions import (
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
    BatchSendResult,
    Command,
    CommandMetadata,
    CommandStatus,
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
from commandbus.repositories.command import PostgresCommandRepository
from commandbus.worker import ReceivedCommand, Worker

__all__ = [
    "DEFAULT_RETRY_POLICY",
    "AuditEvent",
    "AuditEventType",
    "BatchSendResult",
    "Command",
    "CommandBus",
    "CommandBusError",
    "CommandMetadata",
    "CommandNotFoundError",
    "CommandStatus",
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
    "PostgresCommandRepository",
    "ReceivedCommand",
    "ReplyOutcome",
    "RetryPolicy",
    "SendRequest",
    "SendResult",
    "TransientCommandError",
    "TroubleshootingItem",
    "TroubleshootingQueue",
    "Worker",
    "handler",
]

__version__ = "0.1.0"
