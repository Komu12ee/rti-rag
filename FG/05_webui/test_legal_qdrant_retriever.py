import app as web_app

from services.legal_qdrant_retriever import (
    legal_results_to_evidence,
    retrieve_legal_references,
)
from services.query_router import route_query


TEST_QUERIES = [
    "RTI Act में धारा 8(1)(j) क्या है?",
    "बलरामपुर के PIO का नाम और RTI reply की time limit बताओ",
]


def main() -> None:
    print("\n" + "=" * 100)
    print("ROUTER A + QDRANT LEGAL RETRIEVER TEST")
    print("=" * 100)

    if web_app._load_rag_module() is None or web_app.retrieve_context is None:
        raise RuntimeError(
            f"RAG module could not load: {web_app._rag_import_error}"
        )

    for query in TEST_QUERIES:
        decision = route_query(query)

        print(f"\nQuery: {query}")
        print(f"Route: {decision.route.value}")
        print(f"Reason: {decision.reason}")

        if decision.route.value not in {"QDRANT", "HYBRID"}:
            print("Qdrant legal retrieval: skipped")
            continue

        result = retrieve_legal_references(
            query=query,
            decision=decision,
            retrieve_context_fn=web_app.retrieve_context,
            limit=3,
        )

        evidence = legal_results_to_evidence(result)

        print(f"Qdrant lookup query: {result.lookup_query}")
        print(f"Evidence count: {len(evidence)}")

        for index, item in enumerate(evidence, start=1):
            metadata = item["metadata"]

            print("\n" + "-" * 80)
            print(f"Evidence {index}")
            print(f"Source file: {metadata.get('source')}")
            print(f"Score: {metadata.get('score')}")
            print(f"Case number: {metadata.get('case_number')}")
            print(f"Text preview: {item['content'][:500]}")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()