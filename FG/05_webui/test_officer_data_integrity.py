from services.postgres_db import get_connection


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    (SELECT COUNT(*) FROM officer_registry_staging) AS staging_records,
                    (SELECT COUNT(*) FROM officer_assignments) AS total_assignments,
                    (
                        SELECT COUNT(*)
                        FROM officer_assignments
                        WHERE is_active = TRUE
                    ) AS active_assignments;
            """)
            summary = cur.fetchone()

            cur.execute("""
                SELECT
                    s.source_serial_no,
                    s.officer_record_id,
                    s.officer_name,
                    s.email,
                    s.office_code,
                    s.office_name,
                    s.rti_role
                FROM officer_registry_staging s
                LEFT JOIN officer_assignments oa
                    ON oa.source_record_id = s.officer_record_id
                WHERE oa.assignment_id IS NULL
                ORDER BY s.source_serial_no;
            """)
            missing_rows = cur.fetchall()

    print("\n" + "=" * 75)
    print("OFFICER REGISTRY INTEGRITY CHECK")
    print("=" * 75)
    print(f"Staging records:    {summary['staging_records']}")
    print(f"Total assignments:  {summary['total_assignments']}")
    print(f"Active assignments: {summary['active_assignments']}")

    print("\nRecords present in staging but missing from assignments:")
    if not missing_rows:
        print("None")
    else:
        for row in missing_rows:
            print("-" * 75)
            for key, value in row.items():
                print(f"{key}: {value}")

    print("=" * 75)


if __name__ == "__main__":
    main()