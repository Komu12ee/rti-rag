from services.postgres_officer_repository import (
    search_officer_directory_summaries,
)


def main() -> None:
    rows = search_officer_directory_summaries(
        rti_role="FAA",
        district="BALRAMPUR",
        department="School Education Department",
        limit=10,
    )

    print("\n" + "=" * 90)
    print("OFFICER DIRECTORY SUMMARY SEARCH")
    print("=" * 90)
    print(f"Unique officer summaries: {len(rows)}")

    for index, row in enumerate(rows, start=1):
        print("\n" + "-" * 90)
        print(f"Result {index}")
        print(f"Role:                    {row['rti_role']}")
        print(f"Officer:                 {row['officer_name']}")
        print(f"Email:                   {row['email']}")
        print(f"Designations:            {row['designations']}")
        print(f"Department:              {row['department_name']}")
        print(f"District:                {row['district_name']}")
        print(f"Assigned office count:   {row['assigned_office_count']}")
        print(f"Sample office names:     {row['sample_office_names']}")

    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()