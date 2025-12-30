"""Handler registry for command dispatch."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias

from commandbus.exceptions import HandlerAlreadyRegisteredError, HandlerNotFoundError
from commandbus.models import Command, HandlerContext

logger = logging.getLogger(__name__)

# Type alias for handler functions
HandlerFn: TypeAlias = Callable[[Command, HandlerContext], Awaitable[Any]]


class HandlerRegistry:
    """Registry for command handlers.

    Maps (domain, command_type) pairs to handler functions.
    Handlers must be async functions that accept Command and HandlerContext.

    Example:
        registry = HandlerRegistry()

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(command: Command, context: HandlerContext) -> dict:
            # Process the command
            return {"processed": True}

        # Or register directly
        registry.register("payments", "CreditAccount", handle_credit)
    """

    def __init__(self) -> None:
        """Initialize an empty handler registry."""
        self._handlers: dict[tuple[str, str], HandlerFn] = {}

    def register(
        self,
        domain: str,
        command_type: str,
        handler: HandlerFn,
    ) -> None:
        """Register a handler for a command type.

        Args:
            domain: The domain (e.g., "payments")
            command_type: The command type (e.g., "DebitAccount")
            handler: Async function to handle the command

        Raises:
            HandlerAlreadyRegisteredError: If a handler is already registered
                for this domain and command_type combination
        """
        key = (domain, command_type)
        if key in self._handlers:
            raise HandlerAlreadyRegisteredError(domain, command_type)

        self._handlers[key] = handler
        logger.debug(f"Registered handler for {domain}.{command_type}")

    def handler(
        self,
        domain: str,
        command_type: str,
    ) -> Callable[[HandlerFn], HandlerFn]:
        """Decorator to register a handler function.

        Args:
            domain: The domain (e.g., "payments")
            command_type: The command type (e.g., "DebitAccount")

        Returns:
            Decorator that registers the function and returns it unchanged

        Example:
            @registry.handler("payments", "DebitAccount")
            async def handle_debit(command: Command, context: HandlerContext):
                ...
        """

        def decorator(fn: HandlerFn) -> HandlerFn:
            self.register(domain, command_type, fn)
            return fn

        return decorator

    def get(self, domain: str, command_type: str) -> HandlerFn | None:
        """Get the handler for a command type, or None if not found.

        Args:
            domain: The domain
            command_type: The command type

        Returns:
            The registered handler, or None if not found
        """
        return self._handlers.get((domain, command_type))

    def get_or_raise(self, domain: str, command_type: str) -> HandlerFn:
        """Get the handler for a command type, raising if not found.

        Args:
            domain: The domain
            command_type: The command type

        Returns:
            The registered handler

        Raises:
            HandlerNotFoundError: If no handler is registered
        """
        handler = self.get(domain, command_type)
        if handler is None:
            raise HandlerNotFoundError(domain, command_type)
        return handler

    async def dispatch(
        self,
        command: Command,
        context: HandlerContext,
    ) -> Any:
        """Dispatch a command to its registered handler.

        Args:
            command: The command to dispatch
            context: Handler context with metadata and utilities

        Returns:
            The result from the handler

        Raises:
            HandlerNotFoundError: If no handler is registered for the command type
        """
        handler = self.get_or_raise(command.domain, command.command_type)
        logger.debug(
            f"Dispatching {command.domain}.{command.command_type} (command_id={command.command_id})"
        )
        return await handler(command, context)

    def has_handler(self, domain: str, command_type: str) -> bool:
        """Check if a handler is registered for the given command type.

        Args:
            domain: The domain
            command_type: The command type

        Returns:
            True if a handler is registered, False otherwise
        """
        return (domain, command_type) in self._handlers

    def registered_handlers(self) -> list[tuple[str, str]]:
        """Get a list of all registered (domain, command_type) pairs.

        Returns:
            List of (domain, command_type) tuples
        """
        return list(self._handlers.keys())

    def clear(self) -> None:
        """Remove all registered handlers. Useful for testing."""
        self._handlers.clear()
