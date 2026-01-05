"""Tests for database setup utilities."""

import asyncio

from commandbus import check_schema_exists, get_schema_sql, setup_database


class TestGetSchemaSql:
    """Tests for get_schema_sql function."""

    def test_returns_sql_string(self) -> None:
        """Should return the SQL schema as a string."""
        sql = get_schema_sql()
        assert isinstance(sql, str)
        assert len(sql) > 0

    def test_contains_schema_creation(self) -> None:
        """Should contain commandbus schema creation."""
        sql = get_schema_sql()
        assert "CREATE SCHEMA IF NOT EXISTS commandbus" in sql

    def test_contains_command_table(self) -> None:
        """Should contain command table creation."""
        sql = get_schema_sql()
        assert "CREATE TABLE IF NOT EXISTS commandbus.command" in sql

    def test_contains_stored_procedures(self) -> None:
        """Should contain stored procedure definitions."""
        sql = get_schema_sql()
        assert "CREATE OR REPLACE FUNCTION commandbus.sp_receive_command" in sql
        assert "CREATE OR REPLACE FUNCTION commandbus.sp_finish_command" in sql

    def test_contains_batch_table(self) -> None:
        """Should contain batch table creation."""
        sql = get_schema_sql()
        assert "CREATE TABLE IF NOT EXISTS commandbus.batch" in sql

    def test_contains_audit_table(self) -> None:
        """Should contain audit table creation."""
        sql = get_schema_sql()
        assert "CREATE TABLE IF NOT EXISTS commandbus.audit" in sql


class TestSetupDatabaseSignature:
    """Tests for setup_database function signature."""

    def test_is_async_function(self) -> None:
        """setup_database should be an async function."""
        assert asyncio.iscoroutinefunction(setup_database)

    def test_is_async_function_check_schema(self) -> None:
        """check_schema_exists should be an async function."""
        assert asyncio.iscoroutinefunction(check_schema_exists)
