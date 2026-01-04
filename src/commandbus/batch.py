"""Batch completion callback registry and utilities.

This module provides an in-memory registry for batch completion callbacks.
Callbacks are registered when a batch is created with an on_complete parameter
and are invoked when the batch reaches a terminal state (COMPLETED or
COMPLETED_WITH_FAILURES).

Note: Callbacks are in-memory only and will be lost on worker restart.
Applications should poll for completion as a fallback.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from commandbus.models import BatchMetadata
    from commandbus.repositories.batch import PostgresBatchRepository

logger = logging.getLogger(__name__)

# Type alias for batch completion callbacks
BatchCompletionCallback = Callable[["BatchMetadata"], Awaitable[Any]]

# Global in-memory registry for batch callbacks
# Key: (domain, batch_id) tuple, Value: callback function
_batch_callbacks: dict[tuple[str, UUID], BatchCompletionCallback] = {}

# Lock for thread-safe access to the registry
_registry_lock = asyncio.Lock()


async def register_batch_callback(
    domain: str,
    batch_id: UUID,
    callback: BatchCompletionCallback,
) -> None:
    """Register a callback for batch completion.

    Args:
        domain: The domain of the batch
        batch_id: The batch ID
        callback: Async function to call when batch completes.
                  Receives BatchMetadata as argument.
    """
    async with _registry_lock:
        _batch_callbacks[(domain, batch_id)] = callback
    logger.debug(f"Registered callback for batch {domain}.{batch_id}")


def get_batch_callback(
    domain: str,
    batch_id: UUID,
) -> BatchCompletionCallback | None:
    """Get the registered callback for a batch.

    Note: This does not use the lock for read performance.
    Dictionary reads are atomic in Python.

    Args:
        domain: The domain of the batch
        batch_id: The batch ID

    Returns:
        The callback if registered, None otherwise
    """
    return _batch_callbacks.get((domain, batch_id))


async def remove_batch_callback(domain: str, batch_id: UUID) -> None:
    """Remove a batch callback from the registry.

    Args:
        domain: The domain of the batch
        batch_id: The batch ID
    """
    async with _registry_lock:
        _batch_callbacks.pop((domain, batch_id), None)
    logger.debug(f"Removed callback for batch {domain}.{batch_id}")


async def invoke_batch_callback(
    domain: str,
    batch_id: UUID,
    batch_repo: PostgresBatchRepository,
) -> None:
    """Invoke the callback for a completed batch.

    This function should be called when is_batch_complete=True is returned
    from sp_finish_command or TSQ operations.

    The callback is invoked outside of any database transaction.
    Callback exceptions are caught and logged but not propagated.

    Args:
        domain: The domain of the batch
        batch_id: The batch ID
        batch_repo: Batch repository to fetch batch metadata
    """
    callback = get_batch_callback(domain, batch_id)
    if callback is None:
        return

    # Fetch the batch to get its final status for the callback
    batch = await batch_repo.get(domain, batch_id)
    if batch is None:
        logger.warning(f"Batch {domain}.{batch_id} not found for callback")
        await remove_batch_callback(domain, batch_id)
        return

    try:
        logger.info(
            f"Invoking callback for batch {domain}.{batch_id} (status={batch.status.value})"
        )
        await callback(batch)
        logger.debug(f"Callback for batch {domain}.{batch_id} completed successfully")
    except Exception as e:
        logger.exception(f"Batch callback error for {domain}.{batch_id}: {e}")
    finally:
        # Always remove the callback after invocation (success or failure)
        await remove_batch_callback(domain, batch_id)


async def check_and_invoke_batch_callback(
    domain: str,
    batch_id: UUID,
    batch_repo: PostgresBatchRepository,
) -> None:
    """Check if batch is complete and invoke callback if registered.

    DEPRECATED: Use invoke_batch_callback instead when is_batch_complete=True
    is returned from sp_finish_command or TSQ operations.

    This function should be called after any operation that might complete a batch
    (e.g., command complete, TSQ cancel, TSQ complete).

    The callback is invoked outside of any database transaction.
    Callback exceptions are caught and logged but not propagated.

    Args:
        domain: The domain of the batch
        batch_id: The batch ID
        batch_repo: Batch repository to fetch batch metadata
    """
    callback = get_batch_callback(domain, batch_id)
    if callback is None:
        return

    # Fetch the batch to check its status
    batch = await batch_repo.get(domain, batch_id)
    if batch is None:
        logger.warning(f"Batch {domain}.{batch_id} not found for callback")
        await remove_batch_callback(domain, batch_id)
        return

    # Only invoke callback if batch is in a terminal state
    if batch.status.value not in ("COMPLETED", "COMPLETED_WITH_FAILURES"):
        return

    try:
        logger.info(
            f"Invoking callback for batch {domain}.{batch_id} (status={batch.status.value})"
        )
        await callback(batch)
        logger.debug(f"Callback for batch {domain}.{batch_id} completed successfully")
    except Exception as e:
        logger.exception(f"Batch callback error for {domain}.{batch_id}: {e}")
    finally:
        # Always remove the callback after invocation (success or failure)
        await remove_batch_callback(domain, batch_id)


def clear_all_callbacks() -> None:
    """Clear all registered callbacks.

    This is primarily useful for testing.
    """
    _batch_callbacks.clear()
    logger.debug("Cleared all batch callbacks")
