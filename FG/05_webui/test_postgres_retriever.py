from services.postgres_retriever import (
    officer_results_to_context,
    retrieve_officer_registry,
)
from services.query_router import route_query


TEST_QUERIES = [
    "पकराड़ी स्कूल का PIO कौन है?",
    "बलरामपुर जिले के PIO का email दिखाइए",
    "rr1901138@gmail.com का officer record दिखाओ",
    "RTI Act में धारा 8(1)(j) क्या है?",
    "बलरामपुर के PIO का नाम और RTI reply की time limit बताओ",
]


def main() -> None:
    print("\n" + "=" * 100)
    print("ROUTER A + POSTGRES RETRIEVER TEST")
    print("=" * 100)

    for query in TEST_QUERIES:
        decision = route_query(query)

        print(f"\nQuery: {query}")
        print(f"Route: {decision.route.value}")
        print(f"Confidence: {decision.confidence}")
        print(f"Reason: {decision.reason}")
        
        if decision.route.value not in {"POSTGRES", "HYBRID"}:
            print("PostgreSQL retrieval: skipped")
            continue

        result = retrieve_officer_registry(
            query=query,
            decision=decision,
            limit=5,
        )
        print(f"PostgreSQL lookup query: {result.lookup_query}")
        evidence = officer_results_to_context(result)

        print(f"Lookup mode: {result.lookup.mode}")
        print(f"Evidence count: {len(evidence)}")

        for index, item in enumerate(evidence, start=1):
            print("\n" + "-" * 80)
            print(f"Evidence {index}")
            print(f"Source: {item['source_type']}")
            print(item["content"])

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()