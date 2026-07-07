import app as web_app

from services.hybrid_retriever import retrieve_from_all_sources
from services.unified_answer_service import generate_unified_answer


TEST_QUERIES = [
    "पकराड़ी स्कूल का PIO कौन है?",
    "RTI Act में धारा 8(1)(j) क्या है?",
    "बलरामपुर के PIO का नाम और RTI reply की time limit बताओ",
    "मुझे RTI के बारे में कुछ बताओ",
]


def main() -> None:
    print("\n" + "=" * 100)
    print("UNIFIED ANSWER SERVICE TEST")
    print("=" * 100)

    if web_app._load_rag_module() is None or web_app.retrieve_context is None:
        raise RuntimeError(
            f"RAG module could not load: {web_app._rag_import_error}"
        )

    for query in TEST_QUERIES:
        retrieval = retrieve_from_all_sources(
            query=query,
            retrieve_context_fn=web_app.retrieve_context,
            limit=3,
        )

        answer = generate_unified_answer(
            query=query,
            result=retrieval,
            generate_answer_fn=web_app.generate_answer,
        )

        print("\n" + "#" * 100)
        print(f"Query: {query}")
        print(f"Route: {retrieval.resolution.final.route.value}")
        print(f"Used LLM: {answer.used_llm}")
        print(f"Needs clarification: {answer.needs_clarification}")
        print("\nAnswer:")
        print(answer.answer)
        print(f"\nSources attached: {len(answer.sources)}")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()