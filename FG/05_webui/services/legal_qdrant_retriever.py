from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services.hybrid_query_splitter import split_hybrid_query
from services.retrieval_plan import Route, RouterDecision


@dataclass(frozen=True)
class LegalQdrantRetrievalResult:
    decision: RouterDecision
    lookup_query: str
    context_results: list[dict[str, Any]]
    source_type: str = "RTI Legal References (Qdrant)"

    @property
    def has_results(self) -> bool:
        return bool(self.context_results)


def retrieve_legal_references(
    query: str,
    decision: RouterDecision,
    retrieve_context_fn: Callable[..., list[dict[str, Any]]],
    limit: int = 5,
) -> LegalQdrantRetrievalResult:
    """
    Retrieve legal references from the existing Qdrant RAG pipeline.

    QDRANT route:
        full question goes to Qdrant.

    HYBRID route:
        only legal clause goes to Qdrant.
    """
    if decision.route not in {Route.QDRANT, Route.HYBRID}:
        raise ValueError(
            f"Qdrant legal retrieval cannot run for route: {decision.route.value}"
        )

    lookup_query = query

    if decision.route == Route.HYBRID:
        parts = split_hybrid_query(query)
        lookup_query = parts.legal_query

    limit = max(1, min(int(limit), 20))

    context_results = retrieve_context_fn(
        lookup_query,
        num_context=limit,
    ) or []

    return LegalQdrantRetrievalResult(
        decision=decision,
        lookup_query=lookup_query,
        context_results=context_results,
    )


def legal_results_to_evidence(
    result: LegalQdrantRetrievalResult,
) -> list[dict[str, Any]]:
    """
    Convert current Qdrant result objects into source-labelled evidence.

    This keeps Qdrant evidence separate from PostgreSQL registry evidence.
    """
    evidence: list[dict[str, Any]] = []

    for item in result.context_results:
        point = item.get("point")
        payload = getattr(point, "payload", {}) if point is not None else {}

        evidence.append(
            {
                "source_type": result.source_type,
                "mode": "LEGAL",
                "content": payload.get("text", ""),
                "metadata": {
                    "rank": item.get("rank"),
                    "score": item.get("score"),
                    "source": payload.get("source", ""),
                    "case_number": payload.get("case_number", ""),
                    "chunk_type": payload.get("chunk_type", ""),
                    "outcome": payload.get("outcome", ""),
                },
            }
        )

    return evidence