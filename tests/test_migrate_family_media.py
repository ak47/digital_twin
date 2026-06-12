"""Unit tests for the dump-parse / reconciliation logic of migrate_family_media.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "migrate_family_media.py"
    spec = importlib.util.spec_from_file_location("migrate_family_media", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_script()


DUMP_FIXTURE = r"""
CREATE TABLE `photo_galleries` (...) TYPE=InnoDB;
INSERT INTO `photo_galleries` VALUES ('amsterdam', 4, 'Amsterdam', 1, '1999-12-15 00:00:00', '2000-01-01 00:00:00', 'Mom\'s trip & more');
INSERT INTO `photo_galleries` VALUES ('test', 99, 'Test gallery', 0, '1999-12-15 00:00:00', NULL, 'inactive');
INSERT INTO `photo_galleries` VALUES ('Xmas2003', 1, 'Xmas 2003', 1, '2003-12-15 00:00:00', NULL, '');
INSERT INTO `photos` VALUES (1, 'amsterdam', 'Canal at dusk', 'dsc0042', 'gif', 'dsc0042', 'jpg', NULL, NULL);
INSERT INTO `photos` VALUES (2, 'amsterdam', NULL, 'missing_thumb', 'gif', 'dsc0050', 'jpg', NULL, NULL);
INSERT INTO `photos` VALUES (3, 'amsterdam', 'Ghost row', 'nofile', 'gif', 'nofile', 'jpg', NULL, NULL);
INSERT INTO `photos` VALUES (4, 'test', 'In inactive gallery', 'x', 'gif', 'x', 'jpg', NULL, NULL);
INSERT INTO `photos` VALUES (5, 'Xmas2003', 'Tree', 'tree', 'gif', 'tree', 'jpg', NULL, NULL);
INSERT INTO `videos` VALUES (1, 'Ava\'s First Video (5mb)', 'video/AvaVid1.MPG', 'Ava\'s First Video', '_new', 'avaVid1', '2003-12-24 00:00:00', NULL, NULL);
INSERT INTO `videos` VALUES (2, 'Paper Fun (12 MB)', 'video/paper_fun.mpg', 'Paper everywhere', '_new', 'paper', '2004-05-01 00:00:00', NULL, NULL);
"""


@pytest.fixture(scope="module")
def parsed(mod):
    return mod.parse_dump(DUMP_FIXTURE)


class TestDumpParsing:
    def test_galleries_parsed_with_fields(self, parsed) -> None:
        galleries = {g["name"]: g for g in parsed["galleries"]}
        assert galleries["amsterdam"]["title"] == "Amsterdam"
        assert galleries["amsterdam"]["order"] == 4
        assert galleries["amsterdam"]["description"] == "Mom's trip & more"
        assert galleries["amsterdam"]["active"] is True

    def test_inactive_gallery_flagged(self, parsed) -> None:
        galleries = {g["name"]: g for g in parsed["galleries"]}
        assert galleries["test"]["active"] is False

    def test_photos_grouped_by_gallery_with_null_caption(self, parsed) -> None:
        photos = parsed["photos"]
        amsterdam = [p for p in photos if p["gallery"] == "amsterdam"]
        assert len(amsterdam) == 3
        assert amsterdam[0]["caption"] == "Canal at dusk"
        assert amsterdam[1]["caption"] is None
        assert amsterdam[0]["thumb_stem"] == "dsc0042"
        assert amsterdam[0]["image_stem"] == "dsc0042"

    def test_videos_parsed_with_size_suffix_stripped(self, parsed) -> None:
        videos = parsed["videos"]
        assert videos[0]["title"] == "Ava's First Video"
        assert videos[0]["file"] == "AvaVid1.MPG"
        assert videos[0]["description"] == "Ava's First Video"
        assert videos[0]["date"] == "2003-12-24"
        assert videos[1]["title"] == "Paper Fun"

    def test_empty_description_becomes_null(self, parsed) -> None:
        galleries = {g["name"]: g for g in parsed["galleries"]}
        assert galleries["Xmas2003"]["description"] is None


class TestStripSizeSuffix:
    def test_variants(self, mod) -> None:
        assert mod.strip_size_suffix("Title (5mb)") == "Title"
        assert mod.strip_size_suffix("Title (12 MB)") == "Title"
        assert mod.strip_size_suffix("Title") == "Title"
        assert mod.strip_size_suffix("(5mb) leading kept (5mb)") == "(5mb) leading kept"


class TestReconcile:
    def _fs(self):
        # filesystem inventory: gallery -> {"thumbs": {stem,...}, "fulls": {stem,...}}
        return {
            "amsterdam": {
                "thumbs": {"dsc0042"},
                "fulls": {"dsc0042", "dsc0050", "dsc0099"},
            },
            "Xmas2003": {"thumbs": {"tree"}, "fulls": {"tree"}},
        }

    def test_inactive_galleries_excluded(self, mod, parsed) -> None:
        manifest, report = mod.reconcile(parsed, self._fs())
        names = [g["name"] for g in manifest["galleries"]]
        assert "test" not in names

    def test_galleries_sorted_by_order(self, mod, parsed) -> None:
        manifest, _ = mod.reconcile(parsed, self._fs())
        assert [g["name"] for g in manifest["galleries"]] == ["Xmas2003", "amsterdam"]

    def test_db_orphan_dropped_and_reported(self, mod, parsed) -> None:
        manifest, report = mod.reconcile(parsed, self._fs())
        amsterdam = next(g for g in manifest["galleries"] if g["name"] == "amsterdam")
        stems = [i["full"] for i in amsterdam["items"]]
        assert not any("nofile" in s for s in stems)
        assert any("nofile" in entry for entry in report["db_rows_missing_files"])

    def test_file_orphan_appended_caption_less_at_end(self, mod, parsed) -> None:
        manifest, report = mod.reconcile(parsed, self._fs())
        amsterdam = next(g for g in manifest["galleries"] if g["name"] == "amsterdam")
        last = amsterdam["items"][-1]
        assert "dsc0099" in last["full"]
        assert last["caption"] is None
        assert any("dsc0099" in entry for entry in report["files_without_db_rows"])

    def test_missing_thumb_falls_back_to_full(self, mod, parsed) -> None:
        manifest, _ = mod.reconcile(parsed, self._fs())
        amsterdam = next(g for g in manifest["galleries"] if g["name"] == "amsterdam")
        item = next(i for i in amsterdam["items"] if "dsc0050" in i["full"])
        assert item["thumb"] == item["full"]

    def test_object_keys_use_expected_layout(self, mod, parsed) -> None:
        manifest, _ = mod.reconcile(parsed, self._fs())
        amsterdam = next(g for g in manifest["galleries"] if g["name"] == "amsterdam")
        first = amsterdam["items"][0]
        assert first["thumb"] == "galleries/amsterdam/thumbs/dsc0042.gif"
        assert first["full"] == "galleries/amsterdam/full/dsc0042.jpg"


class TestVideoMatching:
    def test_case_insensitive_extension_matching(self, mod, parsed) -> None:
        # disk has lowercase .mpg for a row that says paper_fun.mpg and
        # uppercase .MPG elsewhere; both must match case-insensitively.
        files = ["AvaVid1.MPG", "PAPER_FUN.mpg"]
        matched = mod.match_video_files(parsed["videos"], files)
        assert len(matched) == 2
        assert matched[0]["disk_file"] == "AvaVid1.MPG"
        assert matched[1]["disk_file"] == "PAPER_FUN.mpg"

    def test_unmatched_video_reported(self, mod, parsed) -> None:
        matched = mod.match_video_files(parsed["videos"], ["AvaVid1.MPG"])
        assert len(matched) == 1
