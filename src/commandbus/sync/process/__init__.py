"""Native synchronous process management components.

This package provides synchronous implementations for process management,
including the reply router for dispatching replies to process managers.
"""

from commandbus.sync.process.router import SyncProcessReplyRouter

__all__ = [
    "SyncProcessReplyRouter",
]
