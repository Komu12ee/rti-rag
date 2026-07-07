#!/usr/bin/env python3
"""
Clean CG RTI officer registry data.

Input:
    rti-rag/data/raw/officers_raw_*.json

Output:
    rti-rag/data/processed/
        officers_clean_<timestamp>.json
        officers_clean_<timestamp>.csv
        officers_validation_report_<timestamp>.json
        officers_clean_latest.json
        officers_clean_latest.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ────────────────────────────────────────────────────────────────
# Project paths
# Script location: rti-rag/Scraper/clean_officers.py
# ────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR

RAW_DIR = PROJECT_ROOT / "raw"
PROCESSED_DIR = PROJECT_ROOT / "processed"


def clean_text(value: Any) -> str:
    """
    Clean English/Hindi text without destroying Unicode characters.
    Keeps valid Hindi text intact while removing extra spaces/newlines.
    """
    if value is None:
        return ""

    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ")  # non-breaking space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_email(value: Any) -> str:
    return clean_text(value).lower()


def normalize_role(raw_role: Any) -> str:
    """
    Convert portal role text to a short controlled vocabulary.
    """
    role = clean_text(raw_role).casefold()

    if "public information officer" in role:
        return "PIO"

    if "first appellate officer" in role:
        return "FAA"

    # Keep future unknown roles instead of deleting them.
    return clean_text(raw_role).upper() or "UNKNOWN"


def stable_hash(*parts: Any) -> str:
    """
    Generate deterministic ID.
    officecode alone is not enough because the same office can have
    different PIO and FAA records.
    """
    raw = "|".join(clean_text(part).casefold() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def latest_raw_file() -> Path:
    files = sorted(RAW_DIR.glob("officers_raw_*.json"))

    if not files:
        raise FileNotFoundError(
            f"No officers_raw_*.json file found in:\n{RAW_DIR}"
        )

    return files[-1]


def clean_record(raw: dict[str, Any], source_file: str) -> dict[str, Any]:
    """
    Convert one API record into a clean canonical officer record.
    Do not delete rows merely because name or email is blank.
    """
    office_code = clean_text(raw.get("officecode"))
    designation_code = clean_text(raw.get("original_designationcode"))
    role = normalize_role(raw.get("rtidesignation"))

    name = clean_text(raw.get("name"))
    email = normalize_email(raw.get("emailid"))
    designation = clean_text(raw.get("originaldesignation_name"))
    office_name = clean_text(raw.get("office_name"))
    office_address = clean_text(raw.get("office_address"))
    department_code = clean_text(raw.get("office_base_dept_code"))
    department = clean_text(raw.get("dept_name"))
    district = clean_text(raw.get("distname")).upper()
    office_level = clean_text(raw.get("local_office_level_name"))
    office_section = clean_text(raw.get("office_section_name"))
    serial_no = raw.get("serialno")

    # One office can have both a PIO and FAA, so role is part of the key.
    record_key = stable_hash(
        office_code,
        role,
        email,
        name,
        designation_code,
        department_code,
    )

    return {
        # Stable identifiers
        "officer_record_id": f"RTI_OFF_{record_key}",
        "office_id": f"RTI_OFFICE_{office_code}" if office_code else "",
        "source_serial_no": serial_no,

        # Officer identity
        "officer_name": name,
        "email": email,
        "designation_code": designation_code,
        "designation": designation,

        # RTI responsibility
        "rti_role": role,  # PIO / FAA
        "rti_role_original": clean_text(raw.get("rtidesignation")),

        # Office information
        "office_code": office_code,
        "office_name": office_name,
        "office_address": office_address,
        "office_section_name": office_section,
        "office_level": office_level,

        # Department and location
        "department_code": department_code,
        "department_name": department,
        "department_key": department.casefold(),
        "district": district,
        "district_key": district.casefold(),

        # Provenance and audit fields
        "source_api": "https://rtionline.cg.gov.in/rti/api/Pio/GetListOfEmployees",
        "source_file": source_file,
        "is_active": True,
    }


def build_validation_report(
    raw_rows: list[dict[str, Any]],
    clean_rows: list[dict[str, Any]],
    source_file: Path,
) -> dict[str, Any]:
    roles = Counter(row["rti_role"] for row in clean_rows)
    districts = Counter(row["district"] for row in clean_rows if row["district"])
    departments = Counter(
        row["department_name"] for row in clean_rows if row["department_name"]
    )

    record_ids = [row["officer_record_id"] for row in clean_rows]
    duplicate_ids = [
        record_id
        for record_id, count in Counter(record_ids).items()
        if count > 1
    ]

    blank_name = sum(not row["officer_name"] for row in clean_rows)
    blank_email = sum(not row["email"] for row in clean_rows)
    blank_office_code = sum(not row["office_code"] for row in clean_rows)
    blank_department = sum(not row["department_name"] for row in clean_rows)
    blank_district = sum(not row["district"] for row in clean_rows)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source_file),
        "source_record_count": len(raw_rows),
        "clean_record_count": len(clean_rows),
        "unique_officer_record_ids": len(set(record_ids)),
        "duplicate_officer_record_ids": len(duplicate_ids),
        "duplicate_id_examples": duplicate_ids[:20],
        "role_counts": dict(roles),
        "unique_districts": len(districts),
        "unique_departments": len(departments),
        "blank_field_counts": {
            "officer_name": blank_name,
            "email": blank_email,
            "office_code": blank_office_code,
            "department_name": blank_department,
            "district": blank_district,
        },
        "top_10_districts_by_records": dict(districts.most_common(10)),
        "top_10_departments_by_records": dict(departments.most_common(10)),
        "notes": [
            "Blank names are retained because some valid official records may only provide office email/designation.",
            "No rows are automatically removed at this cleaning stage.",
            "officer_record_id includes office code, RTI role, email, name, designation code and department code.",
        ],
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("No cleaned rows available to write CSV.")

    fieldnames = list(rows[0].keys())

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean CG RTI officer registry JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional raw JSON path. Default: latest officers_raw_*.json",
    )
    args = parser.parse_args()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    input_file = args.input if args.input else latest_raw_file()

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found:\n{input_file}")

    print(f"\nReading raw file:\n{input_file}")

    raw_data = json.loads(input_file.read_text(encoding="utf-8"))

    if raw_data.get("status") is not True:
        print("\nWarning: API status is not True.")

    raw_rows = raw_data.get("table", [])

    if not isinstance(raw_rows, list):
        raise ValueError("Expected 'table' field to contain a list of officer records.")

    clean_rows = [
        clean_record(raw, source_file=input_file.name)
        for raw in raw_rows
        if isinstance(raw, dict)
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    clean_json_path = PROCESSED_DIR / f"officers_clean_{timestamp}.json"
    clean_csv_path = PROCESSED_DIR / f"officers_clean_{timestamp}.csv"
    report_path = PROCESSED_DIR / f"officers_validation_report_{timestamp}.json"

    report = build_validation_report(
        raw_rows=raw_rows,
        clean_rows=clean_rows,
        source_file=input_file,
    )

    # Save timestamped outputs
    write_json(
        clean_json_path,
        {
            "metadata": {
                "source_file": input_file.name,
                "source_api": "https://rtionline.cg.gov.in/rti/api/Pio/GetListOfEmployees",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "record_count": len(clean_rows),
            },
            "records": clean_rows,
        },
    )
    write_csv(clean_csv_path, clean_rows)
    write_json(report_path, report)

    # Save stable "latest" copies for later PostgreSQL/Qdrant scripts
    shutil.copy2(clean_json_path, PROCESSED_DIR / "officers_clean_latest.json")
    shutil.copy2(clean_csv_path, PROCESSED_DIR / "officers_clean_latest.csv")

    print("\n" + "=" * 70)
    print("CLEANING COMPLETED")
    print("=" * 70)
    print(f"Raw records:              {len(raw_rows)}")
    print(f"Clean records:            {len(clean_rows)}")
    print(f"Unique record IDs:        {report['unique_officer_record_ids']}")
    print(f"Duplicate record IDs:     {report['duplicate_officer_record_ids']}")
    print("\nRole counts:")
    for role, count in report["role_counts"].items():
        print(f"  {role}: {count}")

    print("\nSaved files:")
    print(f"  Clean JSON: {clean_json_path}")
    print(f"  Clean CSV : {clean_csv_path}")
    print(f"  Report    : {report_path}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()