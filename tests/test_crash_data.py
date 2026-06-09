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


def test_qualify_table_names_skips_information_schema_literals() -> None:
    sql = (
        "SELECT column_name FROM `p.d.INFORMATION_SCHEMA.COLUMNS` "
        "WHERE table_name = 'ca_crashes' LIMIT 10"
    )
    out = crash_data._qualify_table_names(sql, "p", "d")  # noqa: SLF001
    assert "table_name = 'ca_crashes'" in out
    assert "`p.d.ca_crashes`" not in out


def test_qualify_table_names_qualifies_from_clause() -> None:
    sql = "SELECT COUNT(*) AS n FROM ca_crashes"
    out = crash_data._qualify_table_names(sql, "my-proj", "vehicle_crashes")  # noqa: SLF001
    assert "FROM `my-proj.vehicle_crashes.ca_crashes`" in out
