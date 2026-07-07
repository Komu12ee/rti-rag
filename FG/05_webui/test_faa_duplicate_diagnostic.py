from services.officer_lookup_service import lookup_officers


QUERY = "Who is the FAA for School Education Department in Balrampur?"


def main() -> None:
    criteria, rows = lookup_officers(QUERY, limit=20)

    print("\n" + "=" * 100)
    print("FAA DUPLICATE DIAGNOSTIC")
    print("=" * 100)

    print(f"\nQuery: {QUERY}")
    print(f"Criteria: {criteria}")
    print(f"Returned rows: {len(rows)}")

    for index, row in enumerate(rows, start=1):
        print("\n" + "-" * 100)
        print(f"Result {index}")
        print(f"assignment_id:       {row.get('assignment_id')}")
        print(f"officer_id:          {row.get('officer_id')}")
        print(f"office_code:         {row.get('office_code')}")
        print(f"rti_role:            {row.get('rti_role')}")
        print(f"officer_name:        {row.get('officer_name')!r}")
        print(f"email:               {row.get('email')!r}")
        print(f"designation:         {row.get('designation')!r}")
        print(f"office_name:         {row.get('office_name')!r}")
        print(f"office_address:      {row.get('office_address')!r}")
        print(f"office_section_name: {row.get('office_section_name')!r}")
        print(f"department_name:     {row.get('department_name')!r}")
        print(f"district_name:       {row.get('district_name')!r}")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()