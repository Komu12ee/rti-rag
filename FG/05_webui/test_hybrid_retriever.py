import app as web_app

from services.hybrid_retriever import retrieve_from_all_sources


TEST_QUERIES = [
    "पकराड़ी स्कूल का PIO कौन है?",
    "RTI Act में धारा 8(1)(j) क्या है?",
    "बलरामपुर के PIO का नाम और RTI reply की time limit बताओ",
    "मुझे RTI के बारे में कुछ बताओ",
]


def print_evidence(title: str, evidence: list[dict]) -> None:
    print(f"\n{title}: {len(evidence)}")

    for index, item in enumerate(evidence, start=1):
        content = item.get("content", "")
        source = item.get("source_type", "Unknown source")

        print("\n" + "-" * 85)
        print(f"Evidence {index}")
        print(f"Source: {source}")
        print(f"Preview: {content[:450]}")


def main() -> None:
    print("\n" + "=" * 100)
    print("UNIFIED RETRIEVAL ORCHESTRATOR TEST")
    print("=" * 100)

    if web_app._load_rag_module() is None or web_app.retrieve_context is None:
        raise RuntimeError(
            f"RAG module could not load: {web_app._rag_import_error}"
        )

    for query in TEST_QUERIES:
        result = retrieve_from_all_sources(
            query=query,
            retrieve_context_fn=web_app.retrieve_context,
            limit=3,
        )

        resolution = result.resolution

        print("\n" + "#" * 100)
        print(f"Query: {query}")
        print(f"Router A route: {resolution.router_a.route.value}")
        print(f"Final route: {resolution.final.route.value}")
        print(f"LLM fallback used: {resolution.used_llm_fallback}")
        print(f"Route reason: {resolution.final.reason}")

        print_evidence(
            "PostgreSQL evidence",
            result.postgres_evidence,
        )

        print_evidence(
            "Qdrant evidence",
            result.qdrant_evidence,
        )

        print(f"\nCombined evidence: {len(result.combined_evidence)}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"- {error}")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()