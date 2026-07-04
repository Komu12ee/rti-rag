"""
Forced test: PostgreSQL miss -> pio_directory_v1 fallback.

This does not change PostgreSQL, Qdrant, Flask files, or indexed data.
It only forces an empty PostgreSQL result inside this one test process.

Run from FG\\05_webui:
    python .\\scripts\\test_forced_pio_qdrant_fallback.py "pio of balrampur"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WEBUI_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEBUI_DIR.parent
RAG_SCRIPTS_DIR = PROJECT_ROOT / "04_embeddings_and_kg" / "scripts"

sys.path.insert(0, str(WEBUI_DIR))
sys.path.insert(0, str(RAG_SCRIPTS_DIR))

from dotenv import load_dotenv
load_dotenv(WEBUI_DIR / ".env")

import app as flask_app
import services.hybrid_retriever as hybrid_retriever
from services.officer_lookup_service import OfficerLookupResult
from services.officer_query_parser import parse_officer_query
from services.postgres_retriever import PostgresRetrievalResult


def forced_empty_postgres(query, decision, limit=5):
    """Simulate zero PostgreSQL matches in this process only."""
    lookup = OfficerLookupResult(
        criteria=parse_officer_query(query),
        mode="ASSIGNMENTS",
        rows=[],
    )
    return PostgresRetrievalResult(
        decision=decision,
        lookup=lookup,
        lookup_query=query,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Force a PostgreSQL miss and verify PIO Qdrant fallback."
    )
    parser.add_argument("query", nargs="?", default="pio of balrampur")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    original = hybrid_retriever.retrieve_officer_registry
    hybrid_retriever.retrieve_officer_registry = forced_empty_postgres

    try:
        result = hybrid_retriever.retrieve_from_all_sources(
            query=args.query,
            retrieve_context_fn=flask_app._retrieve_context_for_unified,
            retrieve_pio_directory_fn=flask_app._retrieve_pio_directory_for_unified,
            limit=max(1, min(args.limit, 10)),
        )
    finally:
        hybrid_retriever.retrieve_officer_registry = original

    print("\n" + "=" * 68)
    print("FORCED POSTGRES MISS -> PIO QDRANT FALLBACK TEST")
    print("=" * 68)
    print(f"Query: {args.query}")
    print(f"Final route: {result.resolution.final.route.value}")
    print(f"PostgreSQL evidence count (forced): {len(result.postgres_evidence)}")
    print(f"PIO Qdrant evidence count: {len(result.pio_qdrant_evidence)}")
    print(f"Legal Qdrant evidence count: {len(result.qdrant_evidence)}")
    print(f"Errors: {result.errors or 'None'}")

    if not result.pio_qdrant_evidence:
        raise SystemExit(
            "\nFAIL: PIO Qdrant fallback returned no evidence. "
            "Check pio_qdrant runtime/retriever configuration."
        )

    print("\nReturned PIO Qdrant records:")
    for index, evidence in enumerate(result.pio_qdrant_evidence, 1):
        m = evidence.get("metadata", {})
        print("-" * 68)
        print(f"#{index} | source_type={evidence.get('source_type')} | mode={evidence.get('mode')}")
        print(f"Officer: {m.get('officer_name')}")
        print(f"Role: {m.get('rti_role')}")
        print(f"Department: {m.get('department_name')}")
        print(f"District: {m.get('district')}")
        print(f"Office: {m.get('office_name')}")
        print(f"Office code: {m.get('office_code')}")
        print(f"Search mode: {m.get('_pio_qdrant_search_mode')}")

    print("\nPASS: PostgreSQL -> pio_directory_v1 fallback is connected and working.")


if __name__ == "__main__":
    main()
