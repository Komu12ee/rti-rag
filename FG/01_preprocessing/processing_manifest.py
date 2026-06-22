"""Small manifest helper for Stage 1 / Stage 2 preprocessing.

The manifest prevents accidental duplicate work. It is intentionally simple:
one JSON file, atomic writes, and entries keyed by the PDF content hash.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path(__file__).resolve().parent / "processed_manifest.json"


def utc_now() -> str:
    """Return an ISO timestamp. Keeping this in one function makes tests easier."""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    """Hash a file in chunks so large PDFs do not get loaded into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load the manifest. If it is missing or invalid, return an empty one."""
    if not path.exists():
        return {"version": 1, "entries": []}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "entries": []}


def save_manifest(manifest: dict[str, Any], path: Path = MANIFEST_PATH) -> None:
    """Write the manifest atomically so a crash cannot leave half-written JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def find_entry(manifest: dict[str, Any], sha256: str | None = None, pdf_stem: str | None = None) -> dict[str, Any] | None:
    """Find an entry by content hash first, then by stem as a fallback."""
    entries = manifest.setdefault("entries", [])
    if sha256:
        for entry in entries:
            if entry.get("sha256") == sha256:
                return entry
    if pdf_stem:
        for entry in entries:
            if entry.get("pdf_stem") == pdf_stem:
                return entry
    return None


def make_base_entry(pdf_path: Path, sha256: str) -> dict[str, Any]:
    """Create the required manifest fields for a PDF."""
    now = utc_now()
    return {
        "pdf_name": pdf_path.name,
        "pdf_stem": pdf_path.stem,
        "source_path": str(pdf_path),
        "file_size": pdf_path.stat().st_size if pdf_path.exists() else None,
        "sha256": sha256,
        "stage1_status": "",
        "stage2_status": "",
        "stage1_output_dir": "",
        "stage2_structured_md": "",
        "stage2_structured_json": "",
        "processed_at": now,
        "updated_at": now,
        "error": None,
    }


def upsert_entry(manifest: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace exactly one record for the PDF hash."""
    entries = manifest.setdefault("entries", [])
    now = utc_now()
    entry["updated_at"] = now
    if not entry.get("processed_at"):
        entry["processed_at"] = now

    for index, existing in enumerate(entries):
        if existing.get("sha256") == entry.get("sha256"):
            merged = {**existing, **entry, "processed_at": existing.get("processed_at") or entry["processed_at"]}
            entries[index] = merged
            return merged

    entries.append(entry)
    return entry


def stage1_output_exists(entry: dict[str, Any] | None) -> bool:
    """A Stage 1 output is valid when metadata.json exists in its folder."""
    if not entry:
        return False
    output_dir = entry.get("stage1_output_dir")
    if not output_dir:
        return False
    return (Path(output_dir) / "metadata.json").exists()


def stage2_output_exists(entry: dict[str, Any] | None) -> bool:
    """A Stage 2 output is valid only when both structured files exist."""
    if not entry:
        return False
    md_path = entry.get("stage2_structured_md")
    json_path = entry.get("stage2_structured_json")
    return bool(md_path and json_path and Path(md_path).exists() and Path(json_path).exists())
