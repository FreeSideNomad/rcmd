from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from commandbus.process.models import ProcessMetadata
from tests.e2e.app.process.statement_report import (
    OutputType,
    StatementReportProcess,
    StatementReportState,
    StatementReportStep,
)


def build_state() -> StatementReportState:
    return StatementReportState(
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 31),
        account_list=["ACC-1"],
        output_type=OutputType.PDF,
    )


def build_process(behavior_repo: AsyncMock | None = None) -> StatementReportProcess:
    return StatementReportProcess(
        command_bus=AsyncMock(),
        process_repo=AsyncMock(),
        reply_queue="reporting__process_replies",
        pool=AsyncMock(),
        behavior_repo=behavior_repo,
    )


def build_metadata(
    state: StatementReportState,
) -> ProcessMetadata[StatementReportState, StatementReportStep]:
    return ProcessMetadata(
        domain="reporting",
        process_id=uuid4(),
        process_type="StatementReport",
        state=state,
    )


@pytest.mark.asyncio
async def test_before_send_command_persists_behavior():
    behavior_repo = AsyncMock()
    state = build_state()
    state.behavior = {"StatementQuery": {"fail_permanent_pct": 10.0}}
    process = build_process(behavior_repo)
    metadata = build_metadata(state)

    command_id = uuid4()
    conn = AsyncMock()
    await process.before_send_command(
        metadata,
        StatementReportStep.QUERY,
        command_id,
        {},
        conn,
    )

    behavior_repo.create.assert_awaited_once_with(
        command_id,
        {"fail_permanent_pct": 10.0},
        {"process_id": str(metadata.process_id), "step": "StatementQuery"},
        conn=conn,
    )


@pytest.mark.asyncio
async def test_before_send_command_no_behavior_noop():
    behavior_repo = AsyncMock()
    state = build_state()
    state.behavior = None
    process = build_process(behavior_repo)
    metadata = build_metadata(state)

    await process.before_send_command(
        metadata,
        StatementReportStep.QUERY,
        uuid4(),
        {},
        AsyncMock(),
    )

    behavior_repo.create.assert_not_called()
