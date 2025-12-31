"""Command Bus - A Python library for Command Bus over PostgreSQL + PGMQ."""

from commandbus.bus import CommandBus, SendResult
from commandbus.exceptions import (
    CommandBusError,
    DuplicateCommandError,
    HandlerAlreadyRegisteredError,
    HandlerNotFoundError,
    PermanentCommandError,
    TransientCommandError,
)
from commandbus.handler import HandlerRegistry
from commandbus.models import (
    Command,
    CommandMetadata,
    CommandStatus,
    HandlerContext,
    ReplyOutcome,
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
    "AuditEventType",
    "Command",
    "CommandBus",
    "CommandBusError",
    "CommandMetadata",
    "CommandStatus",
    "DuplicateCommandError",
    "HandlerAlreadyRegisteredError",
    "HandlerContext",
    "HandlerNotFoundError",
    "HandlerRegistry",
    "PermanentCommandError",
    "PgmqClient",
    "PgmqMessage",
    "PostgresAuditLogger",
    "PostgresCommandRepository",
    "ReceivedCommand",
    "ReplyOutcome",
    "RetryPolicy",
    "SendResult",
    "TransientCommandError",
    "TroubleshootingItem",
    "TroubleshootingQueue",
    "Worker",
]

__version__ = "0.1.0"
