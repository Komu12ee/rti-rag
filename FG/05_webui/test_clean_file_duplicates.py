import json
from collections import defaultdict
from pathlib import Path


WEBUI_DIR = Path(__file__).resolve().parent
RTI_RAG_ROOT = WEBUI_DIR.parent.parent

CLEAN_FILE = (
    RTI_RAG_ROOT
    / "Scraper"
    / "processed"
    / "officers_clean_latest.json"
)


def main() -> None:
    if not CLEAN_FILE.exists():
        raise FileNotFoundError(f"Clean file not found:\n{CLEAN_FILE}")

    payload = json.loads(CLEAN_FILE.read_text(encoding="utf-8"))

    metadata = payload.get("metadata", {})
    records = payload.get("records", [])

    records_by_id = defaultdict(list)

    for record in records:
        record_id = record.get("officer_record_id", "").strip()
        records_by_id[record_id].append(record)

    duplicate_groups = {
        record_id: grouped_records
        for record_id, grouped_records in records_by_id.items()
        if record_id and len(grouped_records) > 1
    }

    empty_ids = sum(
        1
        for record in records
        if not record.get("officer_record_id", "").strip()
    )

    print("\n" + "=" * 80)
    print("CLEAN OFFICER FILE DUPLICATE CHECK")
    print("=" * 80)

    print(f"Clean file:                 {CLEAN_FILE.name}")
    print(f"Metadata record_count:      {metadata.get('record_count')}")
    print(f"Actual records in JSON:     {len(records)}")
    print(f"Unique officer_record_ids:  {len(records_by_id)}")
    print(f"Empty officer_record_ids:   {empty_ids}")
    print(f"Duplicate ID groups:        {len(duplicate_groups)}")

    if duplicate_groups:
        print("\nDuplicate record details:")

        for record_id, grouped_records in duplicate_groups.items():
            print("\n" + "-" * 80)
            print(f"officer_record_id: {record_id}")
            print(f"Duplicate count:   {len(grouped_records)}")

            for index, row in enumerate(grouped_records, start=1):
                print(f"\nRecord {index}:")
                print(f"  serial:      {row.get('source_serial_no')}")
                print(f"  role:        {row.get('rti_role')}")
                print(f"  name:        {row.get('officer_name')}")
                print(f"  email:       {row.get('email')}")
                print(f"  office_code: {row.get('office_code')}")
                print(f"  office_name: {row.get('office_name')}")
                print(f"  designation: {row.get('designation')}")
                print(f"  department:  {row.get('department_name')}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()