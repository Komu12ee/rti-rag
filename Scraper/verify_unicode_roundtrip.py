import getpass
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPORT_DIR = PROJECT_ROOT / "data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

password = getpass.getpass("PostgreSQL password: ")

with psycopg.connect(
    host="localhost",
    port=5432,
    dbname="cg_rti_registry",
    user="postgres",
    password=password,
    row_factory=dict_row,
) as conn:

    with conn.cursor() as cur:
        cur.execute("SET client_encoding TO 'UTF8';")

        cur.execute("""
            SELECT
                o.officer_name,
                o.email,
                ofc.office_name,
                ofc.office_address,
                oa.rti_role
            FROM officer_assignments oa
            JOIN officers o ON o.officer_id = oa.officer_id
            JOIN offices ofc ON ofc.office_code = oa.office_code
            WHERE o.email = %s
              AND oa.is_active = TRUE
            LIMIT 1;
        """, ("rr1901138@gmail.com",))

        row = cur.fetchone()

if not row:
    raise RuntimeError("Test officer record was not found.")

print("\nUnicode-safe escaped output:")
print(json.dumps(row, ensure_ascii=True, indent=2))

print("\nCorrect Hindi check:")
print("Officer name equals 'राजा राम':", row["officer_name"] == "राजा राम")

output_file = REPORT_DIR / "unicode_db_check.json"
output_file.write_text(
    json.dumps(row, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"\nSaved UTF-8 file: {output_file}")