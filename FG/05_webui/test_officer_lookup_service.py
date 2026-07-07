from services.officer_lookup_service import lookup_officers


TEST_QUERIES = [
    "पकराड़ी स्कूल का PIO कौन है?",
    "Who is the FAA for School Education Department in Balrampur?",
    "Find officer using email rr1901138@gmail.com",
    "बलरामपुर जिले के PIO का email दिखाइए",
    "9220043429 office का PIO कौन है?",
    "कार्यालय पुलिस अधीक्षक मुंगेली का FAA कौन है?",
]


def print_assignment_rows(rows: list[dict]) -> None:
    for index, row in enumerate(rows, start=1):
        print(f"\n--- Assignment {index} ---")
        print(f"Role:       {row['rti_role']}")
        print(f"Officer:    {row['officer_name']}")
        print(f"Email:      {row['email']}")
        print(f"Office:     {row['office_name']}")
        print(f"Department: {row['department_name']}")
        print(f"District:   {row['district_name']}")


def print_directory_rows(rows: list[dict]) -> None:
    for index, row in enumerate(rows, start=1):
        print(f"\n--- Officer Summary {index} ---")
        print(f"Role:                    {row['rti_role']}")
        print(f"Officer:                 {row['officer_name']}")
        print(f"Email:                   {row['email']}")
        print(f"Designations:            {row['designations']}")
        print(f"Department:              {row['department_name']}")
        print(f"District:                {row['district_name']}")
        print(f"Portal assignments:      {row['assigned_office_count']}")
        print(f"Sample office names:     {row['sample_office_names']}")


def main() -> None:
    print("\n" + "=" * 90)
    print("END-TO-END OFFICER LOOKUP TEST")
    print("=" * 90)

    for query in TEST_QUERIES:
        result = lookup_officers(query, limit=5)

        print(f"\nQuery: {query}")
        print(f"Mode: {result.mode}")
        print(f"Parsed criteria: {result.criteria}")
        print(f"Results: {len(result.rows)}")

        if result.mode == "DIRECTORY":
            print_directory_rows(result.rows)
        else:
            print_assignment_rows(result.rows)

    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()