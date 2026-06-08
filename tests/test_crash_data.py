"""Tests for readonly crash-data SQL validation."""

from __future__ import annotations

import pytest

from digital_twin import crash_data


def test_validate_adds_limit() -> None:
    sql = crash_data.validate_readonly_sql("SELECT borough, COUNT(*) FROM nyc_crashes GROUP BY 1")
    assert "LIMIT 100" in sql


def test_validate_rejects_insert() -> None:
    with pytest.raises(ValueError, match="SELECT"):
        crash_data.validate_readonly_sql("INSERT INTO nyc_crashes VALUES (1)")


def test_validate_rejects_multiple_statements() -> None:
    with pytest.raises(ValueError, match="Multiple"):
        crash_data.validate_readonly_sql("SELECT 1; SELECT 2")


def test_validate_preserves_existing_limit() -> None:
    sql = crash_data.validate_readonly_sql("SELECT 1 LIMIT 5")
    assert sql.endswith("LIMIT 5")
