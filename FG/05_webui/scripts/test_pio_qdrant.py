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

from services.officer_query_parser import parse_officer_query
from services.pio_qdrant_runtime import retrieve_pio_directory_context


def main() -> None:
    parser = argparse.ArgumentParser(description="Direct test for pio_directory_v1 search.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    criteria = parse_officer_query(args.query)
    filters = {
        # Qdrant payload stores exact uppercase PIO / FAA.
        "rti_role": (criteria.rti_role or "").upper() or None,
        "district_key": (criteria.district or "").casefold() or None,
        "department_key": (criteria.department or "").casefold() or None,
        "office_code": criteria.office_code,
        "email": criteria.email,
    }

    print("Parsed criteria:")
    print(criteria)
    print("Filters:")
    print(filters)

    hits = retrieve_pio_directory_context(
        query_text=args.query,
        num_context=args.limit,
        filters=filters,
    )

    print(f"\nResults: {len(hits)}")
    for hit in hits:
        p = hit["payload"]
        print("-" * 60)
        print(f"Rank: {hit['rank']} | score: {hit['score']:.4f} | {hit['search_mode']}")
        print(f"Role: {p.get('rti_role')}")
        print(f"Officer: {p.get('officer_name') or 'Not listed'}")
        print(f"Department: {p.get('department_name')}")
        print(f"District: {p.get('district')}")
        print(f"Office: {p.get('office_name')}")
        print(f"Email: {p.get('email')}")
        print(f"Office code: {p.get('office_code')}")


if __name__ == "__main__":
    main()
