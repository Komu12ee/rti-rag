from services.postgres_officer_repository import (
    find_by_email,
    find_by_office_code,
    search_active_officers,
)


def print_results(title: str, rows: list[dict]) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    print(f"Results: {len(rows)}")

    for index, row in enumerate(rows[:5], start=1):
        print(f"\n--- Result {index} ---")
        print(f"Role:       {row['rti_role']}")
        print(f"Officer:    {row['officer_name']}")
        print(f"Email:      {row['email']}")
        print(f"Office:     {row['office_name']}")
        print(f"Department: {row['department_name']}")
        print(f"District:   {row['district_name']}")


def main() -> None:
    email_rows = find_by_email("rr1901138@gmail.com")
    print_results("1. Exact Email Search", email_rows)

    office_rows = find_by_office_code(
        office_code="9220043429",
        rti_role="PIO",
    )
    print_results("2. Office Code + PIO Search", office_rows)

    hindi_office_rows = search_active_officers(
        search_text="पकराड़ी",
        rti_role="PIO",
        limit=5,
    )
    print_results("3. Hindi Office Name Search", hindi_office_rows)

    balrampur_rows = search_active_officers(
        rti_role="PIO",
        district="BALRAMPUR",
        limit=5,
    )
    print_results("4. District + PIO Search", balrampur_rows)


if __name__ == "__main__":
    main()