#!/usr/bin/env python3
from __future__ import annotations

import getpass
import sys
from pathlib import Path

import psycopg


SCRIPT_DIR = Path(__file__).resolve().parent
RAG_ROOT = SCRIPT_DIR.parent
WEBUI_DIR = RAG_ROOT / "FG" / "05_webui"

if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

from services.officer_name_normalizer import build_name_keys


def main() -> None:
    password = getpass.getpass(
        "PostgreSQL password for user postgres: "
    )

    connection_config = {
        "host": "localhost",
        "port": 5432,
        "dbname": "cg_rti_registry",
        "user": "postgres",
        "password": password,
    }

    with psycopg.connect(**connection_config) as conn:
        with conn.cursor() as cur:
            print("Creating name-search columns...")

            cur.execute(
                "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
            )

            cur.execute(
                """
                ALTER TABLE officers
                    ADD COLUMN IF NOT EXISTS officer_name_latin TEXT,
                    ADD COLUMN IF NOT EXISTS officer_name_latin_normalized TEXT,
                    ADD COLUMN IF NOT EXISTS officer_name_search_key TEXT;
                """
            )

            cur.execute(
                """
                SELECT officer_id, officer_name
                FROM officers
                ORDER BY officer_id;
                """
            )

            records = cur.fetchall()
            updates = []

            for officer_id, officer_name in records:
                keys = build_name_keys(officer_name)

                updates.append(
                    (
                        keys.latin or None,
                        keys.normalized or None,
                        keys.search_key or None,
                        officer_id,
                    )
                )

            print(f"Backfilling {len(updates)} officer profiles...")

            cur.executemany(
                """
                UPDATE officers
                SET
                    officer_name_latin = %s,
                    officer_name_latin_normalized = %s,
                    officer_name_search_key = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE officer_id = %s;
                """,
                updates,
            )

            print("Creating search indexes...")

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_officers_name_latin_normalized_trgm
                ON officers
                USING gin (
                    officer_name_latin_normalized gin_trgm_ops
                )
                WHERE officer_name_latin_normalized IS NOT NULL
                  AND officer_name_latin_normalized <> '';
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_officers_name_search_key_trgm
                ON officers
                USING gin (
                    officer_name_search_key gin_trgm_ops
                )
                WHERE officer_name_search_key IS NOT NULL
                  AND officer_name_search_key <> '';
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_officers_name_search_key_exact
                ON officers (officer_name_search_key)
                WHERE officer_name_search_key IS NOT NULL
                  AND officer_name_search_key <> '';
                """
            )

            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_officers,
                    COUNT(officer_name_latin_normalized)
                        AS searchable_officers
                FROM officers;
                """
            )

            total_officers, searchable_officers = cur.fetchone()

        conn.commit()

    print("\n" + "=" * 65)
    print("OFFICER NAME SEARCH MIGRATION COMPLETED")
    print("=" * 65)
    print(f"Officer profiles:     {total_officers}")
    print(f"Searchable profiles:  {searchable_officers}")
    print("=" * 65)


if __name__ == "__main__":
    main()