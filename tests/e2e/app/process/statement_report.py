"""End-to-end StatementReportProcess implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from uuid import UUID

from commandbus.models import Reply
from commandbus.process import (
    BaseProcessManager,
    ProcessCommand,
    ProcessMetadata,
    ProcessResponse,
)

from ..models import TestCommandRepository


class OutputType(StrEnum):
    """Output formats for reports."""

    PDF = "pdf"
    HTML = "html"
    CSV = "csv"


class StatementReportStep(StrEnum):
    """Steps in the statement report process."""

    QUERY = "StatementQuery"
    AGGREGATE = "StatementDataAggregation"
    RENDER = "StatementRender"


@dataclass
class StatementReportState:
    """State for the statement report process."""

    from_date: date
    to_date: date
    account_list: list[str]
    output_type: OutputType
    query_result_path: str | None = None
    aggregated_data_path: str | None = None
    rendered_file_path: str | None = None
    behavior: dict[str, dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "account_list": self.account_list,
            "output_type": str(self.output_type),
            "query_result_path": self.query_result_path,
            "aggregated_data_path": self.aggregated_data_path,
            "rendered_file_path": self.rendered_file_path,
            "behavior": self.behavior,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create state from dictionary."""
        return cls(
            from_date=date.fromisoformat(data["from_date"]),
            to_date=date.fromisoformat(data["to_date"]),
            account_list=data["account_list"],
            output_type=OutputType(data["output_type"]),
            query_result_path=data.get("query_result_path"),
            aggregated_data_path=data.get("aggregated_data_path"),
            rendered_file_path=data.get("rendered_file_path"),
            behavior=data.get("behavior"),
        )


@dataclass(frozen=True)
class StatementQueryRequest:
    """Request for statement query."""

    from_date: date
    to_date: date
    account_list: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "account_list": self.account_list,
        }


@dataclass(frozen=True)
class StatementQueryResponse:
    """Response for statement query."""

    result_path: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(result_path=data["result_path"])


@dataclass(frozen=True)
class StatementAggregationRequest:
    """Request for statement aggregation."""

    data_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"data_path": self.data_path}


@dataclass(frozen=True)
class StatementAggregationResponse:
    """Response for statement aggregation."""

    result_path: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(result_path=data["result_path"])


@dataclass(frozen=True)
class StatementRenderRequest:
    """Request for statement rendering."""

    aggregated_data_path: str
    output_type: OutputType

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregated_data_path": self.aggregated_data_path,
            "output_type": str(self.output_type),
        }


@dataclass(frozen=True)
class StatementRenderResponse:
    """Response for statement rendering."""

    result_path: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(result_path=data["result_path"])


class StatementReportProcess(BaseProcessManager[StatementReportState, StatementReportStep]):
    """Process manager for generating statement reports."""

    def __init__(
        self,
        *args: Any,
        behavior_repo: TestCommandRepository | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._behavior_repo = behavior_repo

    @property
    def process_type(self) -> str:
        return "StatementReport"

    @property
    def domain(self) -> str:
        return "reporting"

    @property
    def state_class(self) -> type[StatementReportState]:
        return StatementReportState

    def create_initial_state(self, initial_data: dict[str, Any]) -> StatementReportState:
        return StatementReportState.from_dict(initial_data)

    def get_first_step(self, state: StatementReportState) -> StatementReportStep:
        return StatementReportStep.QUERY

    async def build_command(
        self, step: StatementReportStep, state: StatementReportState
    ) -> ProcessCommand[Any]:
        match step:
            case StatementReportStep.QUERY:
                return ProcessCommand(
                    command_type=step,
                    data=StatementQueryRequest(
                        from_date=state.from_date,
                        to_date=state.to_date,
                        account_list=state.account_list,
                    ),
                )
            case StatementReportStep.AGGREGATE:
                return ProcessCommand(
                    command_type=step,
                    data=StatementAggregationRequest(data_path=state.query_result_path or ""),
                )
            case StatementReportStep.RENDER:
                return ProcessCommand(
                    command_type=step,
                    data=StatementRenderRequest(
                        aggregated_data_path=state.aggregated_data_path or "",
                        output_type=state.output_type,
                    ),
                )

    def update_state(
        self, state: StatementReportState, step: StatementReportStep, reply: Reply
    ) -> None:
        match step:
            case StatementReportStep.QUERY:
                resp = ProcessResponse.from_reply(reply, StatementQueryResponse)
                if resp.result:
                    state.query_result_path = resp.result.result_path
            case StatementReportStep.AGGREGATE:
                resp = ProcessResponse.from_reply(reply, StatementAggregationResponse)
                if resp.result:
                    state.aggregated_data_path = resp.result.result_path
            case StatementReportStep.RENDER:
                resp = ProcessResponse.from_reply(reply, StatementRenderResponse)
                if resp.result:
                    state.rendered_file_path = resp.result.result_path

    def get_next_step(
        self, current_step: StatementReportStep, reply: Reply, state: StatementReportState
    ) -> StatementReportStep | None:
        match current_step:
            case StatementReportStep.QUERY:
                return StatementReportStep.AGGREGATE
            case StatementReportStep.AGGREGATE:
                return StatementReportStep.RENDER
            case StatementReportStep.RENDER:
                return None

    async def before_send_command(
        self,
        process: ProcessMetadata[StatementReportState, StatementReportStep],
        step: StatementReportStep,
        command_id: UUID,
        command_payload: dict[str, Any],
        conn: Any,
    ) -> None:
        """Persist step-specific behavior for reporting handlers."""
        if self._behavior_repo is None:
            return
        behavior_map = process.state.behavior or {}
        step_behavior = behavior_map.get(step.value)
        if not step_behavior:
            return
        await self._behavior_repo.create(
            command_id,
            step_behavior,
            {"process_id": str(process.process_id), "step": step.value},
            conn=conn,
        )
