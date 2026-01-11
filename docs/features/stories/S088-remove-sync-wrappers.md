# S088: Remove Sync Wrappers

## User Story

As a developer, I want old sync wrapper code removed so that the codebase has a single, clean sync implementation.

## Acceptance Criteria

### AC1: Delete SyncRuntime
- Given `src/commandbus/sync/runtime.py` exists
- When cleanup complete
- Then file is deleted

### AC2: Delete Old SyncWorker Wrapper
- Given old SyncWorker wraps async Worker
- When cleanup complete
- Then old wrapper removed, native SyncWorker remains

### AC3: Delete Old SyncProcessReplyRouter Wrapper
- Given old wrapper exists
- When cleanup complete
- Then old wrapper removed

### AC4: Update __init__.py Exports
- Given sync module exports
- When cleanup complete
- Then exports point to native implementations only

### AC5: Remove config.py Threading Config
- Given `get_thread_pool_size()` function
- When no longer needed
- Then remove or simplify

### AC6: Update Documentation
- Given docs reference old wrappers
- When cleanup complete
- Then docs updated to describe native sync

## Implementation Notes

**Files to Delete:**
- `src/commandbus/sync/runtime.py` - Background event loop wrapper
- Any wrapper classes that will be replaced

**Current runtime.py content (to be removed):**
```python
# This entire pattern is eliminated:
class SyncRuntime:
    """Background event loop for running async code from sync context."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        """Start background event loop thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._started.wait()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run async coroutine from sync context."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()
```

**Files to Modify:**

`src/commandbus/sync/__init__.py`:
```python
# BEFORE:
from commandbus.sync.runtime import SyncRuntime
from commandbus.sync.worker import SyncWorker  # wrapper
from commandbus.sync.bus import SyncCommandBus  # wrapper
from commandbus.sync.process import SyncProcessReplyRouter  # wrapper

# AFTER:
from commandbus.sync.worker import SyncWorker  # native
from commandbus.sync.bus import SyncCommandBus  # native
from commandbus.sync.health import HealthStatus, HealthState
from commandbus.sync.watchdog import WorkerWatchdog
from commandbus.sync.process.router import SyncProcessReplyRouter  # native

__all__ = [
    "SyncWorker",
    "SyncCommandBus",
    "SyncProcessReplyRouter",
    "HealthStatus",
    "HealthState",
    "WorkerWatchdog",
]
```

`src/commandbus/sync/config.py` (simplify or delete):
```python
# BEFORE:
def get_thread_pool_size(config_value: int | None = None) -> int:
    """Get thread pool size from config or environment."""
    if config_value is not None:
        return config_value
    env_value = os.environ.get("SYNC_THREAD_POOL_SIZE")
    if env_value:
        return int(env_value)
    return os.cpu_count() or 4

# AFTER: Delete if not needed, or simplify to just pool sizing
```

**Documentation Updates:**

Update `docs/sync-refactoring-plan.md` to mark wrapper removal complete:
```markdown
## Removed Components

The following wrapper components have been removed in favor of native implementations:

- `SyncRuntime` - Background event loop thread (replaced by direct sync calls)
- Old `SyncWorker` - Wrapped async Worker (replaced by native ThreadPoolExecutor)
- Old `SyncProcessReplyRouter` - Wrapped async router (replaced by native)
- `get_thread_pool_size()` - Threading config (simplified or removed)
```

**Migration Checklist:**
1. [ ] Ensure all E2E tests pass with native sync
2. [ ] Delete `src/commandbus/sync/runtime.py`
3. [ ] Remove wrapper classes from existing files
4. [ ] Update `__init__.py` exports
5. [ ] Simplify or remove `config.py`
6. [ ] Update documentation
7. [ ] Run `make ready` to verify nothing breaks

**Estimated Lines:** ~200 deleted
