#!/usr/bin/env python3
"""
Import cleaned CG RTI officer registry data into PostgreSQL.

Reads:
    data/processed/officers_clean_latest.json

Writes:
    officer_registry_staging
    ingestion_runs
    departments
    districts
    offices
    officers
    officer_assignments
"""

from __future__ import annotations

import getpass
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import sys
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR

RAG_ROOT = SCRIPT_DIR.parent
WEBUI_DIR = RAG_ROOT / "FG" / "05_webui"

if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

from services.officer_name_normalizer import build_name_keys

# Script location: rti-rag/Scraper/import_officers_to_postgres.py
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR

RAW_DIR = PROJECT_ROOT 
PROCESSED_DIR = PROJECT_ROOT / "processed"
REPORT_DIR = PROJECT_ROOT / "reports"

CLEAN_FILE = PROCESSED_DIR / "officers_clean_latest.json"


def sha256_file(path: Path) -> str | None:
    """Create hash of raw file for audit tracking."""
    if not path.exists():
        return None

    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def text(value: Any) -> str:
    """Return safe stripped text."""
    return str(value or "").strip()


def identity_fingerprint(record: dict[str, Any]) -> str:
    """
    Create a stable identity key for an officer.

    For normal records:
        name + email + designation

    For unnamed officers:
        use office + role + designation so different unknown people
        do not accidentally become one person.
    """
    name = text(record.get("officer_name")).casefold()
    email = text(record.get("email")).casefold()
    designation_code = text(record.get("designation_code")).casefold()
    designation = text(record.get("designation")).casefold()

    if name or email:
        raw = f"person|{name}|{email}|{designation_code}|{designation}"
    else:
        office_code = text(record.get("office_code"))
        role = text(record.get("rti_role"))
        raw = f"unknown|{office_code}|{role}|{designation_code}|{designation}"

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_clean_records() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not CLEAN_FILE.exists():
        raise FileNotFoundError(
            f"Cleaned file not found:\n{CLEAN_FILE}\n"
            "Run clean_officers.py first."
        )

    payload = json.loads(CLEAN_FILE.read_text(encoding="utf-8"))
    metadata = payload.get("metadata", {})
    records = payload.get("records", [])

    if not isinstance(records, list) or not records:
        raise ValueError("No valid records found in officers_clean_latest.json")

    return metadata, records


def main() -> None:
    metadata, records = load_clean_records()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    source_file = text(metadata.get("source_file")) or "unknown_raw_file.json"
    source_api = text(metadata.get("source_api"))
    raw_file_path = RAW_DIR / source_file
    raw_hash = sha256_file(raw_file_path)

    db_password = getpass.getpass("PostgreSQL password for user postgres: ")

    connection_config = {
        "host": "localhost",
        "port": 5432,
        "dbname": "cg_rti_registry",
        "user": "postgres",
        "password": db_password,
    }

    skipped_no_office_code = 0
    skipped_unknown_role = 0

    try:
        with psycopg.connect(**connection_config) as conn:
            with conn.cursor() as cur:
                # ------------------------------------------------------
                # 1. Create one ingestion run
                # ------------------------------------------------------
                cur.execute(
                    """
                    INSERT INTO ingestion_runs (
                        source_name,
                        source_api,
                        source_file,
                        raw_file_sha256,
                        fetched_at,
                        source_record_count,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'RUNNING')
                    RETURNING ingestion_run_id;
                    """,
                    (
                        "CG RTI Officer Registry API",
                        source_api,
                        source_file,
                        raw_hash,
                        datetime.now(timezone.utc),
                        len(records),
                    ),
                )

                ingestion_run_id = cur.fetchone()[0]

                # ------------------------------------------------------
                # 2. Load staging table
                # ------------------------------------------------------
                staging_columns = [
                    "officer_record_id",
                    "office_id",
                    "source_serial_no",
                    "officer_name",
                    "email",
                    "designation_code",
                    "designation",
                    "rti_role",
                    "rti_role_original",
                    "office_code",
                    "office_name",
                    "office_address",
                    "office_section_name",
                    "office_level",
                    "department_code",
                    "department_name",
                    "department_key",
                    "district",
                    "district_key",
                    "source_api",
                    "source_file",
                    "is_active",
                    "ingestion_run_id",
                ]

                placeholders = ", ".join(["%s"] * len(staging_columns))
                update_columns = [
                    col for col in staging_columns
                    if col != "officer_record_id"
                ]

                staging_sql = f"""
                    INSERT INTO officer_registry_staging (
                        {", ".join(staging_columns)}
                    )
                    VALUES ({placeholders})
                    ON CONFLICT (officer_record_id)
                    DO UPDATE SET
                        {", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)},
                        updated_at = CURRENT_TIMESTAMP;
                """

                staging_rows = []

                for record in records:
                    staging_rows.append(
                        (
                            record["officer_record_id"],
                            record.get("office_id"),
                            record.get("source_serial_no"),
                            record.get("officer_name"),
                            record.get("email"),
                            record.get("designation_code"),
                            record.get("designation"),
                            record.get("rti_role"),
                            record.get("rti_role_original"),
                            record.get("office_code"),
                            record.get("office_name"),
                            record.get("office_address"),
                            record.get("office_section_name"),
                            record.get("office_level"),
                            record.get("department_code"),
                            record.get("department_name"),
                            record.get("department_key"),
                            record.get("district"),
                            record.get("district_key"),
                            record.get("source_api"),
                            record.get("source_file"),
                            record.get("is_active", True),
                            ingestion_run_id,
                        )
                    )

                cur.executemany(staging_sql, staging_rows)

                # ------------------------------------------------------
                # 3. Departments
                # ------------------------------------------------------
                departments: dict[str, tuple[str, str, str]] = {}

                for record in records:
                    code = text(record.get("department_code"))

                    if code:
                        name = text(record.get("department_name")) or code
                        key = text(record.get("department_key")) or name.casefold()
                        departments[code] = (code, name, key)

                cur.executemany(
                    """
                    INSERT INTO departments (
                        department_code,
                        department_name,
                        department_key
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (department_code)
                    DO UPDATE SET
                        department_name = EXCLUDED.department_name,
                        department_key = EXCLUDED.department_key,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    list(departments.values()),
                )

                # ------------------------------------------------------
                # 4. Districts
                # ------------------------------------------------------
                districts: dict[str, tuple[str, str]] = {}

                for record in records:
                    district_name = text(record.get("district"))
                    district_key = text(record.get("district_key"))

                    if district_name and district_key:
                        districts[district_key] = (district_name, district_key)

                cur.executemany(
                    """
                    INSERT INTO districts (
                        district_name,
                        district_key
                    )
                    VALUES (%s, %s)
                    ON CONFLICT (district_key)
                    DO UPDATE SET
                        district_name = EXCLUDED.district_name,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    list(districts.values()),
                )

                cur.execute(
                    """
                    SELECT district_id, district_key
                    FROM districts;
                    """
                )

                district_id_by_key = {
                    district_key: district_id
                    for district_id, district_key in cur.fetchall()
                }

                # ------------------------------------------------------
                # 5. Offices
                # ------------------------------------------------------
                offices: dict[str, tuple[Any, ...]] = {}

                for record in records:
                    office_code = text(record.get("office_code"))

                    if not office_code:
                        skipped_no_office_code += 1
                        continue

                    office_name = text(record.get("office_name")) or "Unknown Office"
                    department_code = text(record.get("department_code")) or None
                    district_key = text(record.get("district_key"))

                    offices[office_code] = (
                        office_code,
                        office_name,
                        text(record.get("office_address")) or None,
                        text(record.get("office_section_name")) or None,
                        text(record.get("office_level")) or None,
                        department_code,
                        district_id_by_key.get(district_key),
                        ingestion_run_id,
                        ingestion_run_id,
                    )

                cur.executemany(
                    """
                    INSERT INTO offices (
                        office_code,
                        office_name,
                        office_address,
                        office_section_name,
                        office_level,
                        department_code,
                        district_id,
                        first_seen_run_id,
                        last_seen_run_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (office_code)
                    DO UPDATE SET
                        office_name = EXCLUDED.office_name,
                        office_address = COALESCE(
                            NULLIF(EXCLUDED.office_address, ''),
                            offices.office_address
                        ),
                        office_section_name = COALESCE(
                            NULLIF(EXCLUDED.office_section_name, ''),
                            offices.office_section_name
                        ),
                        office_level = COALESCE(
                            NULLIF(EXCLUDED.office_level, ''),
                            offices.office_level
                        ),
                        department_code = EXCLUDED.department_code,
                        district_id = EXCLUDED.district_id,
                        last_seen_run_id = EXCLUDED.last_seen_run_id,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    list(offices.values()),
                )

                # ------------------------------------------------------
                # 6. Officers
                # ------------------------------------------------------
                officers: dict[str, tuple[Any, ...]] = {}
                for record in records:
                    fingerprint = identity_fingerprint(record)
                
                    official_name = text(record.get("officer_name"))
                    name_keys = build_name_keys(official_name)
                
                    officers[fingerprint] = (
                        fingerprint,
                        official_name or None,
                        name_keys.latin or None,
                        name_keys.normalized or None,
                        name_keys.search_key or None,
                        text(record.get("email")) or None,
                        text(record.get("designation_code")) or None,
                        text(record.get("designation")) or None,
                        ingestion_run_id,
                        ingestion_run_id,
                    )
                    cur.executemany(
                    """
                    INSERT INTO officers (
                        identity_fingerprint,
                        officer_name,
                        officer_name_latin,
                        officer_name_latin_normalized,
                        officer_name_search_key,
                        email,
                        designation_code,
                        designation,
                        first_seen_run_id,
                        last_seen_run_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (identity_fingerprint)
                    DO UPDATE SET
                        officer_name = COALESCE(
                            NULLIF(EXCLUDED.officer_name, ''),
                            officers.officer_name
                        ),
                        officer_name_latin = COALESCE(
                            NULLIF(EXCLUDED.officer_name_latin, ''),
                            officers.officer_name_latin
                        ),
                        officer_name_latin_normalized = COALESCE(
                            NULLIF(EXCLUDED.officer_name_latin_normalized, ''),
                            officers.officer_name_latin_normalized
                        ),
                        officer_name_search_key = COALESCE(
                            NULLIF(EXCLUDED.officer_name_search_key, ''),
                            officers.officer_name_search_key
                        ),
                        email = COALESCE(
                            NULLIF(EXCLUDED.email, ''),
                            officers.email
                        ),
                        designation_code = COALESCE(
                            NULLIF(EXCLUDED.designation_code, ''),
                            officers.designation_code
                        ),
                        designation = COALESCE(
                            NULLIF(EXCLUDED.designation, ''),
                            officers.designation
                        ),
                        last_seen_run_id = EXCLUDED.last_seen_run_id,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    list(officers.values()),
                )
                
                cur.execute(
                    """
                    SELECT officer_id, identity_fingerprint
                    FROM officers;
                    """
                )

                officer_id_by_fingerprint = {
                    fingerprint: officer_id
                    for officer_id, fingerprint in cur.fetchall()
                }

                # ------------------------------------------------------
                # 7. Officer assignments: PIO / FAA for each office
                # ------------------------------------------------------
                assignment_rows = []

                for record in records:
                    office_code = text(record.get("office_code"))
                    role = text(record.get("rti_role"))

                    if not office_code:
                        continue

                    if role not in {"PIO", "FAA"}:
                        skipped_unknown_role += 1
                        continue

                    fingerprint = identity_fingerprint(record)
                    officer_id = officer_id_by_fingerprint[fingerprint]

                    assignment_rows.append(
                        (
                            record["officer_record_id"],
                            officer_id,
                            office_code,
                            role,
                            text(record.get("rti_role_original")) or None,
                            ingestion_run_id,
                            ingestion_run_id,
                        )
                    )

                cur.executemany(
                    """
                    INSERT INTO officer_assignments (
                        source_record_id,
                        officer_id,
                        office_code,
                        rti_role,
                        rti_role_original,
                        first_seen_run_id,
                        last_seen_run_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_record_id)
                    DO UPDATE SET
                        officer_id = EXCLUDED.officer_id,
                        office_code = EXCLUDED.office_code,
                        rti_role = EXCLUDED.rti_role,
                        rti_role_original = EXCLUDED.rti_role_original,
                        is_active = TRUE,
                        valid_to = NULL,
                        last_seen_run_id = EXCLUDED.last_seen_run_id,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    assignment_rows,
                )

                # Mark records missing from the latest full snapshot inactive.
                cur.execute(
                    """
                    UPDATE officer_assignments
                    SET
                        is_active = FALSE,
                        valid_to = CURRENT_DATE,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE is_active = TRUE
                      AND last_seen_run_id IS DISTINCT FROM %s;
                    """,
                    (ingestion_run_id,),
                )

                # ------------------------------------------------------
                # 8. Mark run successful
                # ------------------------------------------------------
                cur.execute(
                    """
                    UPDATE ingestion_runs
                    SET status = 'SUCCESS'
                    WHERE ingestion_run_id = %s;
                    """,
                    (ingestion_run_id,),
                )

                # Summary counts before connection commits.
                cur.execute("SELECT COUNT(*) FROM officer_registry_staging;")
                staging_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM departments;")
                department_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM districts;")
                district_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM offices;")
                office_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM officers;")
                officer_count = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT rti_role, COUNT(*)
                    FROM officer_assignments
                    WHERE is_active = TRUE
                    GROUP BY rti_role
                    ORDER BY rti_role;
                    """
                )
                role_counts = dict(cur.fetchall())

            conn.commit()

    except Exception as exc:
        raise RuntimeError(f"Database import failed: {exc}") from exc

    report = {
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "clean_file": str(CLEAN_FILE),
        "source_file": source_file,
        "ingestion_run_id": ingestion_run_id,
        "input_clean_records": len(records),
        "staging_records": staging_count,
        "departments": department_count,
        "districts": district_count,
        "offices": office_count,
        "officers": officer_count,
        "active_assignment_role_counts": role_counts,
        "skipped_no_office_code": skipped_no_office_code,
        "skipped_unknown_role": skipped_unknown_role,
    }

    report_path = REPORT_DIR / (
        f"officer_postgres_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 65)
    print("POSTGRESQL IMPORT COMPLETED")
    print("=" * 65)
    print(f"Ingestion run ID: {ingestion_run_id}")
    print(f"Input records:    {len(records)}")
    print(f"Staging records:  {staging_count}")
    print(f"Departments:      {department_count}")
    print(f"Districts:        {district_count}")
    print(f"Offices:          {office_count}")
    print(f"Officer profiles: {officer_count}")
    print("Active assignments:")

    for role, count in role_counts.items():
        print(f"  {role}: {count}")

    print(f"\nReport saved: {report_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()