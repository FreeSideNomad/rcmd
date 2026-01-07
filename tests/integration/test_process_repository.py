from datetime import UTC, datetime
from uuid import uuid4

import pytest

from commandbus.process import (
    PostgresProcessRepository,
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessStatus,
)


@pytest.fixture
async def cleanup_process_table(pool):
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.process_audit")
        await conn.execute("DELETE FROM commandbus.process")
    yield
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.process_audit")
        await conn.execute("DELETE FROM commandbus.process")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_process_with_dict_state(pool, cleanup_process_table):
    repo = PostgresProcessRepository(pool)
    process_id = uuid4()
    domain = "test_domain"

    process = ProcessMetadata(
        domain=domain,
        process_id=process_id,
        process_type="test_type",
        status=ProcessStatus.PENDING,
        current_step=None,
        state={"foo": "bar", "nested": {"baz": 1}},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    await repo.save(process)

    # Verify
    saved = await repo.get_by_id(domain, process_id)
    assert saved is not None
    assert saved.state == {"foo": "bar", "nested": {"baz": 1}}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_log_step_with_dict_data(pool, cleanup_process_table):
    repo = PostgresProcessRepository(pool)
    process_id = uuid4()
    domain = "test_domain"

    process = ProcessMetadata(
        domain=domain,
        process_id=process_id,
        process_type="test_type",
        status=ProcessStatus.PENDING,
        state={},
    )
    await repo.save(process)

    entry = ProcessAuditEntry(
        step_name="step1",
        command_id=uuid4(),
        command_type="cmd",
        command_data={"arg": 1},
        sent_at=datetime.now(UTC),
        reply_outcome=None,
        reply_data=None,
        received_at=None,
    )

    await repo.log_step(domain, process_id, entry)

    trail = await repo.get_audit_trail(domain, process_id)
    assert len(trail) == 1
    assert trail[0].command_data == {"arg": 1}
