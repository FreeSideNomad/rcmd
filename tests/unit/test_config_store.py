from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.app.config import ConfigStore, RuntimeConfig


class FakeCursor:
    def __init__(self, rows: list[tuple[str, dict[str, Any]]] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[tuple[str, Any | None]] = []

    async def __aenter__(self) -> FakeCursor:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, query: str, params: Any | None = None) -> None:
        self.executed.append((query.strip(), params))

    async def fetchall(self) -> list[tuple[str, dict[str, Any]]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[tuple[str, dict[str, Any]]] | None = None) -> None:
        self.cursor_impl = FakeCursor(rows)

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_impl


class FakePool:
    def __init__(self, rows: list[tuple[str, dict[str, Any]]] | None = None) -> None:
        self.connection_impl = FakeConnection(rows)

    def connection(self) -> FakeConnection:
        return self.connection_impl


@pytest.mark.asyncio
async def test_runtime_config_round_trip() -> None:
    rows = [
        ("worker", {"visibility_timeout": 45}),
        ("retry", {"max_attempts": 4, "backoff_schedule": [5, 30]}),
        ("runtime", {"mode": "sync", "thread_pool_size": 12}),
    ]
    pool = FakePool(rows)
    store = ConfigStore()
    await store.load_from_db(pool)  # type: ignore[arg-type]

    assert store.runtime.mode == "sync"
    assert store.runtime.thread_pool_size == 12

    store.runtime = RuntimeConfig(mode="async", thread_pool_size=None)
    await store.save_to_db(pool)  # type: ignore[arg-type]

    # Validate that runtime row was persisted
    cursor = pool.connection_impl.cursor_impl
    runtime_statements = [stmt for stmt in cursor.executed if "VALUES ('runtime'" in stmt[0]]
    assert runtime_statements, "runtime config should be upserted"
