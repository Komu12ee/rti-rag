from services.officer_query_parser import parse_officer_query


TEST_QUERIES = [
    "पकराड़ी स्कूल का PIO कौन है?",
    "Who is the FAA for School Education Department in Balrampur?",
    "Find officer using email rr1901138@gmail.com",
    "बलरामपुर जिले के PIO का email दिखाइए",
    "9220043429 office का PIO कौन है?",
    "कार्यालय पुलिस अधीक्षक मुंगेली का FAA कौन है?",
    "xyz totally unknown office ka PIO kaun hai?",
    "Champa school ka PIO kaun hai?",
]


def main() -> None:
    print("\n" + "=" * 85)
    print("OFFICER QUERY PARSER TEST")
    print("=" * 85)

    for query in TEST_QUERIES:
        criteria = parse_officer_query(query)

        print(f"\nQuery: {query}")
        print(f"  email:       {criteria.email}")
        print(f"  office_code: {criteria.office_code}")
        print(f"  rti_role:    {criteria.rti_role}")
        print(f"  district:    {criteria.district}")
        print(f"  department:  {criteria.department}")
        print(f"  search_text: {criteria.search_text}")

    print("\n" + "=" * 85)


if __name__ == "__main__":
    main()