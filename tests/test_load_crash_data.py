"""Tests for crash CSV download URL resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "load_crash_data.py"
    spec = importlib.util.spec_from_file_location("load_crash_data", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_nyc_url_uses_correct_dataset_id() -> None:
    mod = _load_script()
    assert "h9gi-nx95" in mod.NYC_CRASHES_DOWNLOAD_URL
    assert "h9gi-n95q" not in mod.NYC_CRASHES_DOWNLOAD_URL


def test_ca_resource_name_mapping_covers_all_ca_files() -> None:
    mod = _load_script()
    assert set(mod.CA_RESOURCE_NAME_TO_FILE.values()) == {
        "2025crashes.csv",
        "2025parties.csv",
        "2025injuredwitnesspassengers.csv",
    }


def test_resolve_download_urls_includes_nyc(monkeypatch) -> None:
    mod = _load_script()

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):  # noqa: ARG002
                return False

            def read(self):
                return b'{"result":{"resources":[]}}'

        return Resp()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    urls = mod.resolve_download_urls()
    assert (
        urls["Motor_Vehicle_Collisions_-_Crashes_20251007.csv"]
        == mod.NYC_CRASHES_DOWNLOAD_URL
    )
    assert "crashes_2025.csv" in urls["2025crashes.csv"]


def test_normalize_redirect_url_strips_s3_port() -> None:
    mod = _load_script()
    raw = (
        "https://s3.amazonaws.com:443/bucket/key?"
        "X-Amz-Signature=abc"
    )
    assert mod.normalize_redirect_url(raw) == (
        "https://s3.amazonaws.com/bucket/key?X-Amz-Signature=abc"
    )


def test_sanitize_column_name_strips_tabs() -> None:
    mod = _load_script()
    assert mod.sanitize_column_name("\tReport Number", index=1) == "Report_Number"


def test_string_schema_from_header_line_all_string() -> None:
    mod = _load_script()
    schema = mod.string_schema_from_header_line(
        "Collision Id,\tReport Number,Crash Date Time\n"
    )
    assert [field.name for field in schema] == [
        "Collision_Id",
        "Report_Number",
        "Crash_Date_Time",
    ]
    assert all(field.field_type == "STRING" for field in schema)


def test_load_ca_table_uses_string_schema(monkeypatch) -> None:
    mod = _load_script()
    captured: dict[str, object] = {}

    class FakeJob:
        def result(self):
            return None

    class FakeClient:
        def load_table_from_uri(self, uri, table_ref, job_config):  # noqa: ARG002
            captured["job_config"] = job_config
            return FakeJob()

        def get_table(self, table_ref):  # noqa: ARG002
            class T:
                num_rows = 1

            return T()

    local = Path("/tmp/test-ca-header.csv")
    local.write_text(
        "Collision Id,\tReport Number,Crash Date Time\n1,2,1/10/2025 8:28:00 AM\n",
        encoding="utf-8",
    )
    try:
        mod.load_table(
            FakeClient(),
            "proj",
            "vehicle_crashes",
            "ca_crashes",
            "gs://b/f.csv",
            local_csv=local,
        )
    finally:
        local.unlink(missing_ok=True)

    job_config = captured["job_config"]
    assert job_config.autodetect is False
    assert job_config.column_name_character_map == "V2"
    assert [field.field_type for field in job_config.schema] == ["STRING"] * 3
