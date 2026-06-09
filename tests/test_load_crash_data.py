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
