"""One-shot migration of the 2005 family photo/video archive to the private GCS bucket.

Parses the recovered 2006 MySQL dump (path passed via --dump; the dump is
NEVER committed) for gallery/photo/video metadata, reconciles it against the
old repo's filesystem in both directions, transcodes the MPEG-1/2 videos to
browser-playable MP4 (H.264/AAC, +faststart) with extracted poster frames,
uploads everything under galleries/ and videos/, and writes manifest.json to
the bucket root (schema: specs/002-site-refresh/contracts/media-manifest.md
in the ak47.github.io repo).

Idempotent: already-uploaded objects are skipped; rerunning is a no-op.

Usage:
  uv run python scripts/migrate_family_media.py \
      --dump ~/Documents/rails/thorondor.sql.zip.sql \
      --old-repo ~/Documents/rails/no_ego \
      --bucket <family-media-bucket> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

FFMPEG_ARGS = [
    "-c:v", "libx264", "-crf", "23", "-preset", "medium",
    "-c:a", "aac",
    "-movflags", "+faststart",
    # MPEG-1/2 sources can have odd dimensions; libx264 yuv420p needs even.
    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
]
POSTER_SEEK_SECONDS = 1.0


# ---------------------------------------------------------------------------
# Dump parsing
# ---------------------------------------------------------------------------

def _parse_values(raw: str) -> list:
    """Parse the value tuple of a single MySQL `INSERT ... VALUES (...)` line."""
    values: list = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch in " ,":
            i += 1
            continue
        if ch == "'":
            buf = []
            i += 1
            while i < n:
                ch = raw[i]
                if ch == "\\" and i + 1 < n:
                    nxt = raw[i + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    i += 2
                    continue
                if ch == "'":
                    if i + 1 < n and raw[i + 1] == "'":  # doubled quote escape
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(ch)
                i += 1
            values.append("".join(buf))
        else:
            j = i
            while j < n and raw[j] != ",":
                j += 1
            token = raw[i:j].strip()
            if token.upper() == "NULL":
                values.append(None)
            else:
                try:
                    values.append(int(token))
                except ValueError:
                    values.append(token)
            i = j
    return values


def _insert_rows(dump_text: str, table: str) -> list[list]:
    pattern = re.compile(
        r"INSERT INTO `" + re.escape(table) + r"` VALUES \((.*)\);\s*$"
    )
    rows = []
    for line in dump_text.splitlines():
        m = pattern.match(line.strip())
        if m:
            rows.append(_parse_values(m.group(1)))
    return rows


def strip_size_suffix(title: str) -> str:
    """Drop stale trailing size annotations like '(5mb)' / '(12 MB)'."""
    return re.sub(r"\s*\(\d+\s*mb\)\s*$", "", title, flags=re.IGNORECASE).strip()


def _date_only(value) -> str | None:
    if not value or not isinstance(value, str):
        return None
    return value.split(" ")[0] or None


def parse_dump(dump_text: str) -> dict:
    """Extract galleries, photos, and videos from the 2006 dump text."""
    galleries = [
        {
            "name": row[0],
            "order": row[1] or 0,
            "title": row[2],
            "active": bool(row[3]),
            "description": (row[6] or "").strip() or None,
        }
        # photo_galleries: (pgid, list_order, title, active, created, revised, description)
        for row in _insert_rows(dump_text, "photo_galleries")
    ]
    photos = [
        {
            "gallery": row[1],
            "caption": (row[2] or "").strip() or None,
            "thumb_stem": row[3],
            "thumb_type": row[4] or "gif",
            "image_stem": row[5],
            "image_type": row[6] or "jpg",
        }
        # photos: (phid, pgid, description, thumb_file, thumb_type, image_file, image_type, ...)
        for row in _insert_rows(dump_text, "photos")
    ]
    videos = [
        {
            "title": strip_size_suffix(row[1] or ""),
            "file": (row[2] or "").split("/")[-1],
            "description": (row[3] or "").strip() or None,
            "date": _date_only(row[6]),
        }
        # videos: (vid, href_text, href_file, href_title, target, id, date_added, ...)
        for row in _insert_rows(dump_text, "videos")
    ]
    return {"galleries": galleries, "photos": photos, "videos": videos}


# ---------------------------------------------------------------------------
# Reconciliation (research.md R7)
# ---------------------------------------------------------------------------

def scan_filesystem(old_repo: Path) -> dict:
    """Inventory gallery stems on disk: {gallery: {"thumbs": set, "fulls": set}}."""
    inventory: dict[str, dict[str, set]] = {}
    gifs = old_repo / "public" / "images" / "GIFs"
    jpgs = old_repo / "public" / "images" / "JPGs"
    for base, key in ((gifs, "thumbs"), (jpgs, "fulls")):
        if not base.is_dir():
            continue
        for gallery_dir in base.iterdir():
            if not gallery_dir.is_dir():
                continue
            entry = inventory.setdefault(
                gallery_dir.name, {"thumbs": set(), "fulls": set()}
            )
            for f in gallery_dir.iterdir():
                if f.is_file():
                    entry[key].add(f.stem)
    return inventory


def _thumb_key(gallery: str, stem: str, ext: str = "gif") -> str:
    return f"galleries/{gallery}/thumbs/{stem}.{ext}"


def _full_key(gallery: str, stem: str, ext: str = "jpg") -> str:
    return f"galleries/{gallery}/full/{stem}.{ext}"


def reconcile(parsed: dict, fs_inventory: dict) -> tuple[dict, dict]:
    """Build the manifest galleries section + a both-directions drift report.

    - inactive galleries are skipped entirely (never migrated)
    - DB rows whose full image is missing on disk are dropped and reported
    - files with no DB row are appended caption-less at the end of the gallery
    - photos whose thumb is missing reuse the full image as thumb (CSS-scaled)
    """
    report = {"db_rows_missing_files": [], "files_without_db_rows": []}
    photos_by_gallery: dict[str, list[dict]] = {}
    for photo in parsed["photos"]:
        photos_by_gallery.setdefault(photo["gallery"], []).append(photo)

    manifest_galleries = []
    for gallery in sorted(parsed["galleries"], key=lambda g: g["order"]):
        if not gallery["active"]:
            continue
        name = gallery["name"]
        fs = fs_inventory.get(name, {"thumbs": set(), "fulls": set()})
        items = []
        seen_fulls: set[str] = set()
        for photo in photos_by_gallery.get(name, []):
            stem = photo["image_stem"]
            if stem not in fs["fulls"]:
                report["db_rows_missing_files"].append(f"{name}/{stem}")
                continue
            seen_fulls.add(stem)
            full = _full_key(name, stem, photo["image_type"])
            if photo["thumb_stem"] in fs["thumbs"]:
                thumb = _thumb_key(name, photo["thumb_stem"], photo["thumb_type"])
            else:
                thumb = full
            items.append({"caption": photo["caption"], "thumb": thumb, "full": full})
        for stem in sorted(fs["fulls"] - seen_fulls):
            report["files_without_db_rows"].append(f"{name}/{stem}")
            full = _full_key(name, stem)
            thumb = _thumb_key(name, stem) if stem in fs["thumbs"] else full
            items.append({"caption": None, "thumb": thumb, "full": full})
        manifest_galleries.append(
            {
                "name": name,
                "title": gallery["title"],
                "description": gallery["description"],
                "order": gallery["order"],
                "items": items,
            }
        )
    return {"galleries": manifest_galleries}, report


def match_video_files(videos: list[dict], disk_files: list[str]) -> list[dict]:
    """Pair dump video rows with on-disk files, case-insensitively (3 of the
    28 files use a lowercase .mpg extension)."""
    by_lower = {f.lower(): f for f in disk_files}
    matched = []
    for video in videos:
        disk = by_lower.get(video["file"].lower())
        if disk is None:
            continue
        matched.append({**video, "disk_file": disk})
    return matched


# ---------------------------------------------------------------------------
# Transcode + upload (not unit-tested; exercised by the one-shot run)
# ---------------------------------------------------------------------------

def transcode_video(src: Path, out_dir: Path) -> tuple[Path, Path]:
    stem = src.stem
    mp4 = out_dir / f"{stem}.mp4"
    poster = out_dir / f"{stem}.jpg"
    if not mp4.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), *FFMPEG_ARGS, str(mp4)],
            check=True,
            capture_output=True,
        )
    if not poster.exists():
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(POSTER_SEEK_SECONDS),
                "-i", str(src),
                "-frames:v", "1", "-q:v", "3",
                str(poster),
            ],
            check=True,
            capture_output=True,
        )
    return mp4, poster


def _upload(bucket, key: str, path: Path, *, dry_run: bool) -> bool:
    """Upload one file unless the object already exists. Returns True if uploaded."""
    blob = bucket.blob(key)
    if blob.exists():
        return False
    if not dry_run:
        blob.upload_from_filename(str(path))
    return True


def run_migration(
    dump_path: Path, old_repo: Path, bucket_name: str, *, dry_run: bool = False
) -> int:
    parsed = parse_dump(dump_path.read_text(encoding="utf-8", errors="replace"))
    manifest, report = reconcile(parsed, scan_filesystem(old_repo))

    video_dir = old_repo / "public" / "video"
    disk_videos = [f.name for f in video_dir.iterdir() if f.is_file()] if video_dir.is_dir() else []
    matched_videos = match_video_files(parsed["videos"], disk_videos)
    unmatched = [v["file"] for v in parsed["videos"]] if not disk_videos else [
        v["file"]
        for v in parsed["videos"]
        if v["file"].lower() not in {f.lower() for f in disk_videos}
    ]

    bucket = None
    if not dry_run:
        from google.cloud import storage

        bucket = storage.Client().bucket(bucket_name)

    uploaded = skipped = 0

    def upload(key: str, path: Path) -> None:
        nonlocal uploaded, skipped
        if dry_run:
            uploaded += 1
            return
        if _upload(bucket, key, path, dry_run=dry_run):
            uploaded += 1
        else:
            skipped += 1

    # Photos
    gifs = old_repo / "public" / "images" / "GIFs"
    jpgs = old_repo / "public" / "images" / "JPGs"
    for gallery in manifest["galleries"]:
        name = gallery["name"]
        for item in gallery["items"]:
            full_file = jpgs / name / Path(item["full"]).name
            if full_file.is_file():
                upload(item["full"], full_file)
            if item["thumb"] != item["full"]:
                thumb_file = gifs / name / Path(item["thumb"]).name
                if thumb_file.is_file():
                    upload(item["thumb"], thumb_file)

    # Videos: transcode locally, upload mp4 + poster
    manifest_videos = []
    with tempfile.TemporaryDirectory(prefix="family-transcode-") as tmp:
        out_dir = Path(tmp)
        for video in matched_videos:
            src = video_dir / video["disk_file"]
            stem = Path(video["disk_file"]).stem
            video_key = f"videos/{stem}.mp4"
            poster_key = f"videos/{stem}.jpg"
            if not dry_run:
                mp4, poster = transcode_video(src, out_dir)
                upload(video_key, mp4)
                upload(poster_key, poster)
            else:
                uploaded += 2
            manifest_videos.append(
                {
                    "title": video["title"],
                    "description": video["description"],
                    "date": video["date"],
                    "video": video_key,
                    "poster": poster_key,
                }
            )

    manifest_doc = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": f"{dump_path.name} (2006-12) + filesystem walk",
        "galleries": manifest["galleries"],
        "videos": manifest_videos,
    }
    if not dry_run:
        bucket.blob("manifest.json").upload_from_string(
            json.dumps(manifest_doc, indent=2),
            content_type="application/json",
        )

    photo_count = sum(len(g["items"]) for g in manifest["galleries"])
    print(f"galleries (active): {len(manifest['galleries'])}")
    print(f"photos in manifest: {photo_count}")
    print(f"videos matched:     {len(manifest_videos)} / {len(parsed['videos'])}")
    if unmatched:
        print(f"videos UNMATCHED:   {unmatched}")
    print(f"objects uploaded:   {uploaded}  (skipped existing: {skipped})")
    print(f"DB rows w/ missing files ({len(report['db_rows_missing_files'])}): "
          f"{report['db_rows_missing_files']}")
    print(f"files w/o DB rows ({len(report['files_without_db_rows'])}): "
          f"{report['files_without_db_rows']}")
    if dry_run:
        print("DRY RUN — nothing uploaded.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True, type=Path,
                        help="Path to the 2006 MySQL dump (never committed)")
    parser.add_argument("--old-repo", required=True, type=Path,
                        help="Path to the 2005 Rails repo checkout")
    parser.add_argument("--bucket", required=True, help="Family media bucket name")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse, reconcile, and report without uploading")
    args = parser.parse_args()
    if not args.dump.is_file():
        parser.error(f"dump not found: {args.dump}")
    if not args.old_repo.is_dir():
        parser.error(f"old repo not found: {args.old_repo}")
    return run_migration(args.dump, args.old_repo, args.bucket, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
