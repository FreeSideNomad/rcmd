"""Base Process Manager implementation."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from uuid import UUID, uuid4

from commandbus.models import Reply, ReplyOutcome
from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessCommand,
    ProcessMetadata,
    ProcessState,
    ProcessStatus,
)

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

    from commandbus.bus import CommandBus
    from commandbus.process.repository import ProcessRepository

logger = logging.getLogger(__name__)

# Type variables for generic base class
TState = TypeVar("TState", bound=ProcessState)
TStep = TypeVar("TStep", bound=StrEnum)


class BaseProcessManager(ABC, Generic[TState, TStep]):
    """Base class for implementing process managers with typed state and steps."""

    def __init__(
        self,
        command_bus: CommandBus,
        process_repo: ProcessRepository,
        reply_queue: str,
        pool: AsyncConnectionPool,
    ):
        self.command_bus = command_bus
        self.process_repo = process_repo
        self.reply_queue = reply_queue
        self.pool = pool

    @property
    @abstractmethod
    def process_type(self) -> str:
        """Return unique process type identifier."""
        pass

    @property
    @abstractmethod
    def domain(self) -> str:
        """Return the domain this process operates in."""
        pass

    @property
    @abstractmethod
    def state_class(self) -> type[TState]:
        """Return the class used for state to enable deserialization."""
        pass

    @abstractmethod
    def create_initial_state(self, initial_data: dict[str, Any]) -> TState:
        """Create typed state from initial input data.

        Args:
            initial_data: Raw input data dict.

        Returns:
            Typed state instance.
        """
        pass

    async def start(
        self,
        initial_data: dict[str, Any],
        conn: AsyncConnection[Any] | None = None,
    ) -> UUID:
        """Start a new process instance.

        Args:
            initial_data: Initial state data for the process.
            conn: Optional connection to run in existing transaction.

        Returns:
            The process_id (UUID) of the new process.
        """
        process_id = uuid4()

        # Create typed state from input
        state = self.create_initial_state(initial_data)

        process = ProcessMetadata[TState, TStep](
            domain=self.domain,
            process_id=process_id,
            process_type=self.process_type,
            status=ProcessStatus.PENDING,
            current_step=None,
            state=state,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        async def _start_impl(c: AsyncConnection[Any]) -> None:
            await self.process_repo.save(process, conn=c)

            # Determine and execute first step
            first_step = self.get_first_step(state)
            await self._execute_step(process, first_step, c)

        if conn:
            await _start_impl(conn)
        else:
            async with self.pool.connection() as new_conn, new_conn.transaction():
                await _start_impl(new_conn)

        return process_id

    @abstractmethod
    def get_first_step(self, state: TState) -> TStep:
        """Determine the first step based on initial state."""
        pass

    @abstractmethod
    async def build_command(
        self,
        step: TStep,
        state: TState,
    ) -> ProcessCommand[Any]:
        """Build typed command for a step.

        Args:
            step: The step (StrEnum) to build command for.
            state: Current typed process state.

        Returns:
            ProcessCommand with typed data.
        """
        pass

    @abstractmethod
    def update_state(
        self,
        state: TState,
        step: TStep,
        reply: Reply,
    ) -> None:
        """Update state in place with data from reply.

        Args:
            state: Typed process state to update.
            step: The step that just completed.
            reply: The reply received.
        """
        pass

    @abstractmethod
    def get_next_step(
        self,
        current_step: TStep,
        reply: Reply,
        state: TState,
    ) -> TStep | None:
        """Determine next step based on reply and state.

        Args:
            current_step: The step that just completed.
            reply: The reply received.
            state: Current process state (after update_state).

        Returns:
            - TStep: Next step to execute
            - None: Process complete
        """
        pass

    def get_compensation_step(self, _step: TStep) -> TStep | None:
        """Get compensation step for a given step.

        Override to provide compensation mapping.

        Args:
            _step: The step that needs compensation.

        Returns:
            Compensation step, or None if no compensation needed.
        """
        return None

    async def handle_reply(
        self,
        reply: Reply,
        process: ProcessMetadata[Any, Any],
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Handle incoming reply and advance process.

        Args:
            reply: The reply received from command execution.
            process: The process metadata (state might be dict).
            conn: Optional connection to run in existing transaction.
        """
        # Ensure state is typed
        if isinstance(process.state, dict):
            process.state = self.state_class.from_dict(process.state)

        # Cast process to typed version for internal use
        typed_process: ProcessMetadata[TState, TStep] = process

        async def _handle_impl(c: AsyncConnection[Any]) -> None:
            # Record reply in audit log
            await self._record_reply(typed_process, reply, c)

            # Handle cancellation from TSQ - trigger compensation
            if reply.outcome == ReplyOutcome.CANCELED:
                logger.info(
                    f"Process {typed_process.process_id} command canceled in TSQ, "
                    f"running compensations"
                )
                await self._run_compensations(typed_process, c)
                return

            # Update state in place
            # Note: TStep is bound to StrEnum, but from DB it might be str.
            # We rely on StrEnum equality with str.
            current_step = typed_process.current_step
            # If current_step is None (shouldn't happen for reply), we can't update state properly
            if current_step is None:
                logger.error(
                    f"Received reply for process {typed_process.process_id} with no current step"
                )
                return

            self.update_state(typed_process.state, current_step, reply)

            # Handle failure (goes to TSQ, wait for operator)
            if reply.outcome == ReplyOutcome.FAILED:
                await self._handle_failure(typed_process, reply, c)
                return

            # Determine next step
            next_step = self.get_next_step(
                current_step,
                reply,
                typed_process.state,
            )

            if next_step is None:
                await self._complete_process(typed_process, c)
            else:
                await self._execute_step(typed_process, next_step, c)

        if conn:
            await _handle_impl(conn)
        else:
            async with self.pool.connection() as new_conn, new_conn.transaction():
                await _handle_impl(new_conn)

    def handle_reply_sync(
        self,
        reply: Reply,
        process: ProcessMetadata[Any, Any],
        conn: Any = None,  # noqa: ARG002
    ) -> None:
        """Handle incoming reply synchronously.

        This is a sync wrapper around handle_reply that uses asyncio.run()
        to execute the async logic. This allows the same process manager
        to work with both async and sync reply routers.

        Note: This method creates a new event loop for each call. For high
        throughput scenarios, consider using the async handle_reply directly
        with a persistent event loop.

        Args:
            reply: The reply received from command execution.
            process: The process metadata (state might be dict).
            conn: Connection parameter (ignored in sync version, uses pool).
        """
        # Run the async handle_reply in a new event loop
        # Note: conn is not passed as the sync version manages its own connection
        asyncio.run(self.handle_reply(reply, process, conn=None))

    async def before_send_command(
        self,
        process: ProcessMetadata[TState, TStep],
        step: TStep,
        command_id: UUID,
        command_payload: dict[str, Any],
        conn: AsyncConnection[Any],
    ) -> None:
        """Hook for subclasses to mutate state or side effects before sending command."""

    async def _execute_step(
        self,
        process: ProcessMetadata[TState, TStep],
        step: TStep,
        conn: AsyncConnection[Any],
    ) -> UUID:
        """Execute a single step by sending command."""
        command = await self.build_command(step, process.state)
        command_id = uuid4()

        # Safely convert data to dict
        command_payload = (
            command.data.to_dict() if hasattr(command.data, "to_dict") else command.data
        )

        await self.before_send_command(process, step, command_id, command_payload, conn)
        await self.command_bus.send(
            domain=self.domain,
            command_type=command.command_type,
            command_id=command_id,
            data=command_payload,
            correlation_id=process.process_id,
            reply_to=self.reply_queue,
            conn=conn,
        )

        process.current_step = step
        process.status = ProcessStatus.WAITING_FOR_REPLY
        process.updated_at = datetime.now(UTC)

        # Record in audit log
        await self._record_command(
            process, step, command_id, command.command_type, command_payload, conn
        )
        await self.process_repo.update(process, conn=conn)

        return command_id

    async def _run_compensations(
        self,
        process: ProcessMetadata[TState, TStep],
        conn: AsyncConnection[Any],
    ) -> None:
        """Run compensating commands for completed steps in reverse order."""
        completed_steps = await self.process_repo.get_completed_steps(
            process.domain, process.process_id, conn=conn
        )

        # We need to map string steps back to TStep if possible, or just work with strings
        # get_compensation_step expects TStep.
        # Since TStep is StrEnum, str should work for lookup if implemented robustly.

        # But wait, get_completed_steps returns list[str].
        # And get_compensation_step takes TStep.
        # I should probably just pass the string, as StrEnum works with strings.

        for step_name in reversed(completed_steps):
            # We assume step_name can be cast/used as TStep
            # or get_compensation_step handles strings.
            # Ideally we'd cast: step = TStep(step_name) but we don't have TStep class here.
            # We'll treat it as Any to satisfy type checker for now.
            step: Any = step_name

            comp_step = self.get_compensation_step(step)
            if comp_step:
                process.current_step = comp_step
                process.status = ProcessStatus.COMPENSATING
                await self.process_repo.update(process, conn=conn)

                # Execute compensation and wait for reply
                await self._execute_step(process, comp_step, conn)
                # Note: Reply router will call handle_reply for compensation replies

        process.status = ProcessStatus.COMPENSATED
        process.completed_at = datetime.now(UTC)
        await self.process_repo.update(process, conn=conn)

    async def _complete_process(
        self,
        process: ProcessMetadata[TState, TStep],
        conn: AsyncConnection[Any],
    ) -> None:
        """Mark process as completed."""
        process.status = ProcessStatus.COMPLETED
        process.completed_at = datetime.now(UTC)
        process.updated_at = datetime.now(UTC)
        await self.process_repo.update(process, conn=conn)

    async def _handle_failure(
        self,
        process: ProcessMetadata[TState, TStep],
        reply: Reply,
        conn: AsyncConnection[Any],
    ) -> None:
        """Handle step failure - command is in TSQ."""
        process.status = ProcessStatus.WAITING_FOR_TSQ
        process.error_code = reply.error_code
        process.error_message = reply.error_message
        process.updated_at = datetime.now(UTC)
        await self.process_repo.update(process, conn=conn)

    async def _record_command(
        self,
        process: ProcessMetadata[TState, TStep],
        step: TStep,
        command_id: UUID,
        command_type: str,
        command_data: dict[str, Any],
        conn: AsyncConnection[Any],
    ) -> None:
        """Record command execution in audit log."""
        entry = ProcessAuditEntry(
            step_name=str(step),  # Ensure string
            command_id=command_id,
            command_type=command_type,
            command_data=command_data,
            sent_at=datetime.now(UTC),
        )
        await self.process_repo.log_step(process.domain, process.process_id, entry, conn=conn)

    async def _record_reply(
        self,
        process: ProcessMetadata[TState, TStep],
        reply: Reply,
        conn: AsyncConnection[Any],
    ) -> None:
        """Update audit log with reply information."""
        entry = ProcessAuditEntry(
            step_name=str(process.current_step) if process.current_step else "",
            command_id=reply.command_id,
            command_type="",  # Will be looked up
            command_data=None,
            sent_at=datetime.now(UTC),  # Will be preserved
            reply_outcome=reply.outcome,
            reply_data=reply.data,
            received_at=datetime.now(UTC),
        )
        await self.process_repo.update_step_reply(
            process.domain, process.process_id, reply.command_id, entry, conn=conn
        )
