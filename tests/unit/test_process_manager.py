from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from commandbus.models import Reply, ReplyOutcome
from commandbus.process import (
    BaseProcessManager,
    ProcessCommand,
    ProcessMetadata,
    ProcessStatus,
)


class MockStep(StrEnum):
    STEP_1 = "step_1"
    STEP_2 = "step_2"


@dataclass
class MockState:
    value: int

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MockState":
        return cls(value=data["value"])


class MockProcessManager(BaseProcessManager[MockState, MockStep]):
    @property
    def process_type(self) -> str:
        return "test_process"

    @property
    def domain(self) -> str:
        return "test_domain"

    @property
    def state_class(self) -> type[MockState]:
        return MockState

    def create_initial_state(self, initial_data: dict[str, Any]) -> MockState:
        return MockState(value=initial_data["value"])

    def get_first_step(self, state: MockState) -> MockStep:
        return MockStep.STEP_1

    async def build_command(self, step: MockStep, state: MockState) -> ProcessCommand[Any]:
        return ProcessCommand(command_type="Cmd1", data={"val": state.value})

    def update_state(self, state: MockState, step: MockStep, reply: Reply) -> None:
        if reply.data:
            state.value += reply.data.get("add", 0)

    def get_next_step(
        self, current_step: MockStep, reply: Reply, state: MockState
    ) -> MockStep | None:
        if current_step == MockStep.STEP_1:
            return MockStep.STEP_2
        return None

    def get_compensation_step(self, step: MockStep) -> MockStep | None:
        if step == MockStep.STEP_2:
            return MockStep.STEP_1
        return None


@pytest.fixture
def mock_bus():
    bus = AsyncMock()
    bus.send.return_value = None
    return bus


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_completed_steps.return_value = ["step_2", "step_1"]
    return repo


@pytest.fixture
def mock_pool():
    pool = Mock(spec=AsyncConnectionPool)

    # Mock connection() to return an async context manager
    conn_ctx = AsyncMock()
    conn = AsyncMock(spec=AsyncConnection)
    conn_ctx.__aenter__.return_value = conn
    pool.connection.return_value = conn_ctx

    # Mock transaction() to return an async context manager
    trans_ctx = AsyncMock()
    conn.transaction.return_value = trans_ctx

    return pool


@pytest.fixture
def manager(mock_bus, mock_repo, mock_pool):
    return MockProcessManager(mock_bus, mock_repo, "reply_q", mock_pool)


@pytest.mark.asyncio
async def test_start(manager, mock_repo, mock_bus):
    pid = await manager.start({"value": 10})

    assert isinstance(pid, uuid4().__class__)
    assert mock_repo.save.called
    assert mock_bus.send.called

    # Check save was called
    assert mock_repo.save.called

    # Check update was called with WAITING
    assert mock_repo.update.called
    updated_process = mock_repo.update.call_args[0][0]
    assert updated_process.status == ProcessStatus.WAITING_FOR_REPLY
    assert updated_process.current_step == MockStep.STEP_1


@pytest.mark.asyncio
async def test_start_with_conn(manager, mock_repo, mock_bus):
    conn = AsyncMock(spec=AsyncConnection)
    pid = await manager.start({"value": 10}, conn=conn)

    assert isinstance(pid, uuid4().__class__)
    assert mock_repo.save.called
    # Verify save called with conn
    # call_args is (args, kwargs). args[0] is process. kwargs['conn'] is conn.
    assert mock_repo.save.call_args[1]["conn"] == conn


@pytest.mark.asyncio
async def test_handle_reply_next_step(manager, mock_repo, mock_bus):
    process = ProcessMetadata(
        domain="d",
        process_id=uuid4(),
        process_type="t",
        state=MockState(10),
        status=ProcessStatus.WAITING_FOR_REPLY,
        current_step=MockStep.STEP_1,
    )

    reply = Reply(
        command_id=uuid4(),
        correlation_id=process.process_id,
        outcome=ReplyOutcome.SUCCESS,
        data={"add": 5},
    )

    await manager.handle_reply(reply, process)

    assert process.state.value == 15
    assert process.current_step == MockStep.STEP_2
    assert process.status == ProcessStatus.WAITING_FOR_REPLY
    assert mock_bus.send.called
    assert mock_repo.update.called


@pytest.mark.asyncio
async def test_handle_reply_complete(manager, mock_repo, mock_bus):
    process = ProcessMetadata(
        domain="d",
        process_id=uuid4(),
        process_type="t",
        state=MockState(15),
        status=ProcessStatus.WAITING_FOR_REPLY,
        current_step=MockStep.STEP_2,  # Last step
    )

    reply = Reply(
        command_id=uuid4(),
        correlation_id=process.process_id,
        outcome=ReplyOutcome.SUCCESS,
        data={"add": 5},
    )

    await manager.handle_reply(reply, process)

    assert process.state.value == 20
    assert process.status == ProcessStatus.COMPLETED
    assert process.completed_at is not None
    # No new command sent
    assert not mock_bus.send.called
    assert mock_repo.update.called


@pytest.mark.asyncio
async def test_handle_failure_triggers_compensation(manager, mock_repo, mock_bus):
    """Test that FAILED reply triggers compensation and ends in CANCELED status.

    FAILED replies come from BusinessRuleException and should:
    1. Run compensations for completed steps
    2. Set final status to CANCELED (not WAITING_FOR_TSQ)
    3. Store error details
    """
    process = ProcessMetadata(
        domain="d",
        process_id=uuid4(),
        process_type="t",
        state=MockState(10),
        status=ProcessStatus.WAITING_FOR_REPLY,
        current_step=MockStep.STEP_1,
    )

    reply = Reply(
        command_id=uuid4(),
        correlation_id=process.process_id,
        outcome=ReplyOutcome.FAILED,
        error_code="BUSINESS_RULE_VIOLATION",
        error_message="Account closed",
    )

    await manager.handle_reply(reply, process)

    # Final status should be CANCELED after compensation
    assert process.status == ProcessStatus.CANCELED
    assert process.error_code == "BUSINESS_RULE_VIOLATION"
    assert process.error_message == "Account closed"
    # Compensation runs (sends commands for completed steps with compensation steps)
    # get_completed_steps returns ["step_2", "step_1"] and only step_2 has compensation
    assert mock_bus.send.call_count == 1  # One compensation command sent
    assert mock_repo.update.called


@pytest.mark.asyncio
async def test_handle_cancel(manager, mock_repo, mock_bus):
    process = ProcessMetadata(
        domain="d",
        process_id=uuid4(),
        process_type="t",
        state=MockState(15),
        status=ProcessStatus.WAITING_FOR_TSQ,
        current_step=MockStep.STEP_2,
    )

    reply = Reply(
        command_id=uuid4(), correlation_id=process.process_id, outcome=ReplyOutcome.CANCELED
    )

    await manager.handle_reply(reply, process)

    assert process.status == ProcessStatus.COMPENSATED
    assert process.completed_at is not None
    # Compensation logic check
    assert mock_bus.send.call_count == 1
    assert mock_repo.update.called
