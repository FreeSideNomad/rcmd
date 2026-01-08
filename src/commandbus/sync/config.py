"""Configuration helpers for synchronous runtime defaults."""

from __future__ import annotations

import os
from typing import Final, TypedDict

from commandbus.sync.runtime import SyncRuntime


class _SyncConfigState(TypedDict):
    runtime: SyncRuntime | None
    thread_pool_size: int | None


_STATE: _SyncConfigState = {"runtime": None, "thread_pool_size": None}
_ENV_VAR: Final[str] = "COMMAND_BUS_SYNC_THREADS"


def configure(
    *,
    runtime: SyncRuntime | None = None,
    thread_pool_size: int | None = None,
) -> None:
    """Override global defaults for sync wrappers.

    Args:
        runtime: Shared runtime instance to reuse across wrappers.
        thread_pool_size: Default size for thread pools used by sync workers.
    """
    if runtime is not None:
        _STATE["runtime"] = runtime
    if thread_pool_size is not None:
        if thread_pool_size <= 0:
            raise ValueError("thread_pool_size must be positive")
        _STATE["thread_pool_size"] = thread_pool_size


def get_default_runtime(runtime: SyncRuntime | None = None) -> SyncRuntime:
    """Return the runtime to use for synchronous wrappers."""
    state_runtime = _STATE["runtime"]
    if runtime is not None:
        return runtime
    if state_runtime is None:
        state_runtime = SyncRuntime()
        _STATE["runtime"] = state_runtime
    return state_runtime


def get_thread_pool_size(thread_pool_size: int | None = None) -> int:
    """Resolve the effective thread pool size for sync workers."""
    if thread_pool_size is not None:
        if thread_pool_size <= 0:
            raise ValueError("thread_pool_size must be positive")
        return thread_pool_size

    cached = _STATE["thread_pool_size"]
    if cached is not None:
        return cached

    env_value = os.getenv(_ENV_VAR)
    if env_value:
        try:
            parsed = int(env_value)
            if parsed > 0:
                _STATE["thread_pool_size"] = parsed
                return parsed
        except ValueError:
            pass

    cpu_count = os.cpu_count() or 1
    default = min(32, cpu_count)
    _STATE["thread_pool_size"] = default
    return default


def _reset_for_tests() -> None:
    """Reset global state (intended for tests only)."""
    runtime = _STATE.get("runtime")
    if runtime is not None:
        runtime.shutdown()
    _STATE["runtime"] = None
    _STATE["thread_pool_size"] = None
