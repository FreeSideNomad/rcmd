"""Unit tests for CommandBus exceptions."""

import pytest

from commandbus.exceptions import (
    BusinessRuleException,
    CommandBusError,
    PermanentCommandError,
    TransientCommandError,
)


class TestBusinessRuleException:
    """Tests for BusinessRuleException class."""

    def test_create_with_all_fields(self) -> None:
        """Test creating exception with code, message, and details."""
        exc = BusinessRuleException(
            code="ACCOUNT_CLOSED",
            message="Account was closed before statement generation",
            details={"account_id": "123", "closed_date": "2024-01-01"},
        )

        assert exc.code == "ACCOUNT_CLOSED"
        assert exc.error_message == "Account was closed before statement generation"
        assert exc.details == {"account_id": "123", "closed_date": "2024-01-01"}
        assert str(exc) == "[ACCOUNT_CLOSED] Account was closed before statement generation"

    def test_create_without_details(self) -> None:
        """Test creating exception with only code and message."""
        exc = BusinessRuleException(
            code="INVALID_DATE",
            message="Date is in the future",
        )

        assert exc.code == "INVALID_DATE"
        assert exc.error_message == "Date is in the future"
        assert exc.details == {}

    def test_create_with_none_details(self) -> None:
        """Test creating exception with explicit None details."""
        exc = BusinessRuleException(
            code="MISSING_DATA",
            message="Required data not found",
            details=None,
        )

        assert exc.code == "MISSING_DATA"
        assert exc.error_message == "Required data not found"
        assert exc.details == {}

    def test_inherits_from_command_bus_error(self) -> None:
        """Test that BusinessRuleException inherits from CommandBusError."""
        exc = BusinessRuleException(code="TEST", message="Test")

        assert isinstance(exc, CommandBusError)
        assert isinstance(exc, Exception)

    def test_not_transient_or_permanent(self) -> None:
        """Test that BusinessRuleException is NOT a TransientCommandError or Permanent."""
        exc = BusinessRuleException(code="TEST", message="Test")

        assert not isinstance(exc, TransientCommandError)
        assert not isinstance(exc, PermanentCommandError)

    def test_can_be_raised_and_caught(self) -> None:
        """Test that exception can be raised and caught."""
        with pytest.raises(BusinessRuleException) as exc_info:
            raise BusinessRuleException(
                code="VALIDATION_FAILED",
                message="Input validation failed",
                details={"field": "email", "reason": "invalid format"},
            )

        assert exc_info.value.code == "VALIDATION_FAILED"
        assert exc_info.value.details == {"field": "email", "reason": "invalid format"}

    def test_can_be_caught_as_command_bus_error(self) -> None:
        """Test that BusinessRuleException can be caught as CommandBusError."""
        with pytest.raises(CommandBusError):
            raise BusinessRuleException(code="TEST", message="Test")

    def test_empty_details_dict(self) -> None:
        """Test that empty details dict is handled correctly."""
        exc = BusinessRuleException(
            code="TEST",
            message="Test",
            details={},
        )
        assert exc.details == {}


class TestExceptionComparison:
    """Tests comparing BusinessRuleException with other exception types."""

    def test_same_interface_as_transient(self) -> None:
        """Test that BusinessRuleException has same fields as TransientCommandError."""
        transient = TransientCommandError(
            code="TIMEOUT",
            message="Connection timeout",
            details={"timeout_ms": 5000},
        )
        business = BusinessRuleException(
            code="RULE_VIOLATED",
            message="Business rule violated",
            details={"rule": "max_amount"},
        )

        # Both have the same field names
        assert hasattr(transient, "code")
        assert hasattr(transient, "error_message")
        assert hasattr(transient, "details")

        assert hasattr(business, "code")
        assert hasattr(business, "error_message")
        assert hasattr(business, "details")

    def test_same_interface_as_permanent(self) -> None:
        """Test that BusinessRuleException has same fields as PermanentCommandError."""
        permanent = PermanentCommandError(
            code="INVALID_INPUT",
            message="Invalid input data",
            details={"field": "amount"},
        )
        business = BusinessRuleException(
            code="RULE_VIOLATED",
            message="Business rule violated",
            details={"rule": "max_amount"},
        )

        # Both have the same field names
        assert hasattr(permanent, "code")
        assert hasattr(permanent, "error_message")
        assert hasattr(permanent, "details")

        assert hasattr(business, "code")
        assert hasattr(business, "error_message")
        assert hasattr(business, "details")
