"""Handler registry for command dispatch."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeAlias, TypeVar

from commandbus.exceptions import HandlerAlreadyRegisteredError, HandlerNotFoundError
from commandbus.models import Command, HandlerContext

logger = logging.getLogger(__name__)

# Type alias for handler functions
HandlerFn: TypeAlias = Callable[[Command, HandlerContext], Awaitable[Any]]

# Type alias for synchronous handler functions
SyncHandlerFn: TypeAlias = Callable[[Command, HandlerContext], Any]

# Attribute name for storing handler metadata on decorated methods
_HANDLER_ATTR = "_commandbus_handler_meta"

# Generic type for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class HandlerMeta:
    """Metadata attached to decorated handler methods.

    This is set on methods decorated with @handler() and used by
    register_instance() to discover handlers on class instances.
    """

    domain: str
    command_type: str


def handler(domain: str, command_type: str) -> Callable[[F], F]:
    """Decorator to mark a method as a command handler.

    Use this decorator on class methods to mark them as command handlers.
    The decorated methods can then be discovered and registered using
    HandlerRegistry.register_instance().

    Args:
        domain: The domain (e.g., "payments")
        command_type: The command type (e.g., "DebitAccount")

    Returns:
        Decorator that attaches handler metadata to the method

    Example:
        class PaymentHandlers:
            @handler(domain="payments", command_type="DebitAccount")
            async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> dict:
                return {"status": "ok"}

        # Later, register the instance
        registry.register_instance(PaymentHandlers())
    """

    def decorator(fn: F) -> F:
        setattr(fn, _HANDLER_ATTR, HandlerMeta(domain=domain, command_type=command_type))
        return fn

    return decorator


def get_handler_meta(fn: Callable[..., Any]) -> HandlerMeta | None:
    """Get handler metadata from a decorated function.

    Args:
        fn: A function that may have been decorated with @handler

    Returns:
        The HandlerMeta if the function was decorated, None otherwise
    """
    return getattr(fn, _HANDLER_ATTR, None)


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
        self._sync_handlers: dict[tuple[str, str], SyncHandlerFn] = {}

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

    def register_sync(
        self,
        domain: str,
        command_type: str,
        handler: SyncHandlerFn,
    ) -> None:
        """Register a sync handler for a command type.

        Args:
            domain: The domain (e.g., "payments")
            command_type: The command type (e.g., "DebitAccount")
            handler: Sync function to handle the command

        Raises:
            HandlerAlreadyRegisteredError: If a handler is already registered
                for this domain and command_type combination
        """
        key = (domain, command_type)
        if key in self._sync_handlers:
            raise HandlerAlreadyRegisteredError(domain, command_type)

        self._sync_handlers[key] = handler
        logger.debug(f"Registered sync handler for {domain}.{command_type}")

    def sync_handler(
        self,
        domain: str,
        command_type: str,
    ) -> Callable[[SyncHandlerFn], SyncHandlerFn]:
        """Decorator to register a sync handler function.

        Args:
            domain: The domain (e.g., "payments")
            command_type: The command type (e.g., "DebitAccount")

        Returns:
            Decorator that registers the function and returns it unchanged

        Example:
            @registry.sync_handler("payments", "DebitAccount")
            def handle_debit(command: Command, context: HandlerContext):
                ...
        """

        def decorator(fn: SyncHandlerFn) -> SyncHandlerFn:
            self.register_sync(domain, command_type, fn)
            return fn

        return decorator

    def get_sync(self, domain: str, command_type: str) -> SyncHandlerFn | None:
        """Get the sync handler for a command type, or None if not found.

        Args:
            domain: The domain
            command_type: The command type

        Returns:
            The registered sync handler, or None if not found
        """
        return self._sync_handlers.get((domain, command_type))

    def get_sync_or_raise(self, domain: str, command_type: str) -> SyncHandlerFn:
        """Get the sync handler for a command type, raising if not found.

        Args:
            domain: The domain
            command_type: The command type

        Returns:
            The registered sync handler

        Raises:
            HandlerNotFoundError: If no sync handler is registered
        """
        handler = self.get_sync(domain, command_type)
        if handler is None:
            raise HandlerNotFoundError(domain, command_type)
        return handler

    def dispatch_sync(
        self,
        command: Command,
        context: HandlerContext,
    ) -> Any:
        """Dispatch a command to its registered sync handler.

        Args:
            command: The command to dispatch
            context: Handler context with metadata and utilities

        Returns:
            The result from the handler

        Raises:
            HandlerNotFoundError: If no sync handler is registered for the command type
        """
        handler = self.get_sync_or_raise(command.domain, command.command_type)
        logger.debug(
            f"Dispatching (sync) {command.domain}.{command.command_type} "
            f"(command_id={command.command_id})"
        )
        return handler(command, context)

    def has_sync_handler(self, domain: str, command_type: str) -> bool:
        """Check if a sync handler is registered for the given command type.

        Args:
            domain: The domain
            command_type: The command type

        Returns:
            True if a sync handler is registered, False otherwise
        """
        return (domain, command_type) in self._sync_handlers

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

    def registered_sync_handlers(self) -> list[tuple[str, str]]:
        """Get a list of all registered sync (domain, command_type) pairs.

        Returns:
            List of (domain, command_type) tuples
        """
        return list(self._sync_handlers.keys())

    def clear(self) -> None:
        """Remove all registered handlers (async and sync). Useful for testing."""
        self._handlers.clear()
        self._sync_handlers.clear()

    def register_instance(self, instance: object) -> list[tuple[str, str]]:
        """Scan instance for @handler decorated methods and register them.

        This method discovers all methods on the instance that are decorated
        with the @handler decorator and registers them with this registry.
        Private methods (names starting with '_') are skipped.

        Args:
            instance: An object instance with @handler decorated methods

        Returns:
            List of (domain, command_type) tuples that were registered

        Raises:
            HandlerAlreadyRegisteredError: If any handler is already registered.
                Note: If this error is raised, some handlers from the instance
                may have already been registered.

        Example:
            class PaymentHandlers:
                def __init__(self, service):
                    self._service = service

                @handler(domain="payments", command_type="Debit")
                async def handle_debit(self, cmd, ctx):
                    return await self._service.debit(cmd.data["amount"])

            registry = HandlerRegistry()
            registry.register_instance(PaymentHandlers(my_service))
        """
        registered: list[tuple[str, str]] = []

        for name in dir(instance):
            # Skip private and dunder methods
            if name.startswith("_"):
                continue

            method = getattr(instance, name)
            if not callable(method):
                continue

            meta = getattr(method, _HANDLER_ATTR, None)
            if meta is None:
                continue

            if not isinstance(meta, HandlerMeta):
                continue

            self.register(meta.domain, meta.command_type, method)
            registered.append((meta.domain, meta.command_type))
            logger.info(
                f"Discovered handler {instance.__class__.__name__}.{name} "
                f"for {meta.domain}.{meta.command_type}"
            )

        return registered

    def register_instance_as_sync(self, instance: object) -> list[tuple[str, str]]:
        """Scan instance for @handler decorated methods and register them as sync handlers.

        This method discovers all methods on the instance that are decorated
        with the @handler decorator, wraps them with a sync adapter (using
        asyncio.run()), and registers them as sync handlers.

        This is useful for running async handlers in a sync worker context,
        such as in E2E tests that need to test both async and sync modes.

        Private methods (names starting with '_') are skipped.

        Args:
            instance: An object instance with @handler decorated methods

        Returns:
            List of (domain, command_type) tuples that were registered

        Raises:
            HandlerAlreadyRegisteredError: If any handler is already registered.
                Note: If this error is raised, some handlers from the instance
                may have already been registered.

        Example:
            class PaymentHandlers:
                def __init__(self, service):
                    self._service = service

                @handler(domain="payments", command_type="Debit")
                async def handle_debit(self, cmd, ctx):
                    return await self._service.debit(cmd.data["amount"])

            registry = HandlerRegistry()
            # Register as sync handlers for use with SyncWorker
            registry.register_instance_as_sync(PaymentHandlers(my_service))
        """
        registered: list[tuple[str, str]] = []

        for name in dir(instance):
            # Skip private and dunder methods
            if name.startswith("_"):
                continue

            method = getattr(instance, name)
            if not callable(method):
                continue

            meta = getattr(method, _HANDLER_ATTR, None)
            if meta is None:
                continue

            if not isinstance(meta, HandlerMeta):
                continue

            # Create sync wrapper for async handler
            async_handler = method

            def make_sync_wrapper(
                handler: HandlerFn,
            ) -> SyncHandlerFn:
                def sync_wrapper(command: Command, context: HandlerContext) -> Any:
                    # Cast to coroutine for asyncio.run() - all our handlers are coroutines
                    coro = handler(command, context)
                    return asyncio.run(coro)  # type: ignore[arg-type]

                return sync_wrapper

            sync_handler = make_sync_wrapper(async_handler)

            self.register_sync(meta.domain, meta.command_type, sync_handler)
            registered.append((meta.domain, meta.command_type))
            logger.info(
                f"Discovered async handler {instance.__class__.__name__}.{name}, "
                f"registered as sync for {meta.domain}.{meta.command_type}"
            )

        return registered
