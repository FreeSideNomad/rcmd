from datetime import date

import pytest
from pydantic import ValidationError

from tests.e2e.app.api.schemas import ProcessBatchCreateRequest


def test_process_batch_request_with_behavior():
    request = ProcessBatchCreateRequest(
        count=10,
        from_date=date(2024, 1, 1),
        to_date=date(2024, 1, 31),
        behavior={
            "query": {"fail_permanent_pct": 10.0, "error_code": "Q1"},
            "aggregation": {"timeout_pct": 5.0, "min_duration_ms": 50, "max_duration_ms": 200},
        },
    )

    assert request.count == 10
    assert request.behavior is not None
    assert request.behavior.query is not None
    assert request.behavior.query.fail_permanent_pct == 10.0
    assert request.behavior.aggregation is not None
    assert request.behavior.render is None


def test_process_batch_request_rejects_large_counts():
    with pytest.raises(ValidationError):
        ProcessBatchCreateRequest(
            count=1_000_001,  # Limit is 1,000,000
            from_date=date.today(),
            to_date=date.today(),
            output_type="pdf",
        )
