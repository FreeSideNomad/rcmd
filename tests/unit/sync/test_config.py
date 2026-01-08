from __future__ import annotations

import pytest

from commandbus.sync import config as sync_config
from commandbus.sync.runtime import SyncRuntime


@pytest.fixture(autouse=True)
def reset_config():
    sync_config._reset_for_tests()
    yield
    sync_config._reset_for_tests()


def test_configure_overrides_runtime_and_threads(monkeypatch) -> None:
    runtime = SyncRuntime()
    sync_config.configure(runtime=runtime, thread_pool_size=8)

    assert sync_config.get_default_runtime() is runtime
    assert sync_config.get_thread_pool_size() == 8
    runtime.shutdown()


def test_thread_pool_size_from_env(monkeypatch) -> None:
    monkeypatch.setenv("COMMAND_BUS_SYNC_THREADS", "12")
    assert sync_config.get_thread_pool_size() == 12


def test_invalid_thread_pool_values(monkeypatch) -> None:
    monkeypatch.delenv("COMMAND_BUS_SYNC_THREADS", raising=False)
    with pytest.raises(ValueError):
        sync_config.configure(thread_pool_size=0)
