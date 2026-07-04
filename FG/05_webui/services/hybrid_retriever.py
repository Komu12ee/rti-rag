from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from services.legal_qdrant_retriever import (
    LegalQdrantRetrievalResult,
    legal_results_to_evidence,
    retrieve_legal_references,
)
from services.pio_qdrant_retriever import (
    PioDirectoryQdrantRetrievalResult,
    pio_directory_results_to_evidence,
    retrieve_pio_directory_references,
)
from services.postgres_retriever import (
    PostgresRetrievalResult,
    officer_results_to_context,
    retrieve_officer_registry,
)
from services.retrieval_plan import Route, RouterDecision
from services.route_resolver import RouteResolution, resolve_route


@dataclass
class UnifiedRetrievalResult:
    resolution: RouteResolution
    postgres_result: Optional[PostgresRetrievalResult] = None
    pio_qdrant_result: Optional[PioDirectoryQdrantRetrievalResult] = None
    qdrant_result: Optional[LegalQdrantRetrievalResult] = None

    postgres_evidence: list[dict[str, Any]] = field(default_factory=list)
    pio_qdrant_evidence: list[dict[str, Any]] = field(default_factory=list)
    qdrant_evidence: list[dict[str, Any]] = field(default_factory=list)

    # Only relevant when visible route remains UNCLEAR.
    qdrant_fallback_used: bool = False
    qdrant_relevance_accepted: bool | None = None
    qdrant_top_dense_score: float | None = None
    qdrant_relevance_threshold: float | None = None

    errors: list[str] = field(default_factory=list)

    @property
    def officer_evidence(self) -> list[dict[str, Any]]:
        """
        PostgreSQL is canonical. PIO Qdrant is a fallback only, therefore
        PostgreSQL rows always take precedence when present.
        """
        return (
            self.postgres_evidence
            if self.postgres_evidence
            else self.pio_qdrant_evidence
        )

    @property
    def combined_evidence(self) -> list[dict[str, Any]]:
        return [
            *self.postgres_evidence,
            *self.pio_qdrant_evidence,
            *self.qdrant_evidence,
        ]

    @property
    def has_evidence(self) -> bool:
        return bool(self.combined_evidence)


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name, str(default)).strip().casefold()
    return value in {"1", "true", "yes", "on"}


def _unclear_qdrant_threshold() -> float:
    try:
        score = float(os.getenv("UNCLEAR_QDRANT_MIN_DENSE_SCORE", "0.60"))
    except ValueError:
        score = 0.60
    return max(0.0, min(score, 1.0))


def _raw_qdrant_score(item: dict[str, Any]) -> float | None:
    point = item.get("point")
    raw_score = getattr(point, "score", None)
    try:
        return float(raw_score)
    except (TypeError, ValueError):
        return None


def _top_raw_qdrant_score(
    context_results: list[dict[str, Any]] | None,
) -> float | None:
    scores = [
        score
        for item in (context_results or [])
        if (score := _raw_qdrant_score(item)) is not None
    ]
    return max(scores) if scores else None


def _make_unclear_qdrant_decision(
    original_decision: RouterDecision,
) -> RouterDecision:
    """
    Internal legal-Qdrant fallback. It remains separate from PIO/FAA retrieval.
    """
    return RouterDecision(
        route=Route.QDRANT,
        confidence=original_decision.confidence,
        reason=(
            "UNCLEAR fallback: legal Qdrant was searched before returning "
            "a general RTI response."
        ),
        matched_signals=(
            *original_decision.matched_signals,
            "unclear_legal_qdrant_fallback",
        ),
    )


def _retrieve_postgres_then_pio_qdrant(
    *,
    query: str,
    decision: RouterDecision,
    limit: int,
    retrieve_pio_directory_fn: Callable[..., list[dict[str, Any]]] | None,
    result: UnifiedRetrievalResult,
) -> None:
    """
    Required fallback order for officer directory requests:

        PostgreSQL (canonical structured registry)
              ↓ no rows
        pio_directory_v1 (semantic / multilingual recovery)
              ↓ no rows
        existing not-found answer

    Legal Qdrant is never used as the fallback for an officer lookup.
    """
    try:
        postgres_result = retrieve_officer_registry(
            query=query,
            decision=decision,
            limit=limit,
        )
        result.postgres_result = postgres_result
        result.postgres_evidence = officer_results_to_context(postgres_result)
    except Exception as error:
        result.errors.append(
            "PostgreSQL retrieval failed: "
            f"{type(error).__name__}: {error}"
        )

    # PostgreSQL returned an actual result. Keep canonical result only.
    if result.postgres_evidence:
        return

    if retrieve_pio_directory_fn is None:
        result.errors.append(
            "PIO Qdrant fallback was required, but "
            "retrieve_pio_directory_fn was not provided."
        )
        return

    try:
        pio_qdrant_result = retrieve_pio_directory_references(
            query=query,
            retrieve_pio_directory_fn=retrieve_pio_directory_fn,
            limit=limit,
        )
        result.pio_qdrant_result = pio_qdrant_result
        result.pio_qdrant_evidence = pio_directory_results_to_evidence(
            pio_qdrant_result
        )

        print(
            "[POSTGRES → PIO_QDRANT] "
            f"postgres_rows=0 pio_qdrant_rows="
            f"{len(result.pio_qdrant_evidence)}"
        )

    except Exception as error:
        result.errors.append(
            "PIO Qdrant fallback failed: "
            f"{type(error).__name__}: {error}"
        )


def retrieve_from_all_sources(
    query: str,
    retrieve_context_fn: Callable[..., list[dict[str, Any]]] | None,
    retrieve_pio_directory_fn: Callable[..., list[dict[str, Any]]] | None = None,
    limit: int = 5,
    router_timeout_seconds: int = 30,
) -> UnifiedRetrievalResult:
    """
    Route execution:

    POSTGRES:
        PostgreSQL officer lookup → PIO Qdrant fallback only when PG has no rows.

    QDRANT:
        Legal / FAQ / precedent corpus only.

    HYBRID:
        Officer lookup (PG → PIO Qdrant fallback) plus legal corpus.

    UNCLEAR:
        Existing legal-Qdrant fallback remains for generic RTI questions.
    """
    resolution = resolve_route(
        query=query,
        timeout_seconds=router_timeout_seconds,
    )
    final_route = resolution.final.route
    result = UnifiedRetrievalResult(resolution=resolution)

    if final_route in {Route.POSTGRES, Route.HYBRID}:
        _retrieve_postgres_then_pio_qdrant(
            query=query,
            decision=resolution.final,
            limit=limit,
            retrieve_pio_directory_fn=retrieve_pio_directory_fn,
            result=result,
        )

    unclear_fallback_enabled = (
        final_route == Route.UNCLEAR
        and _env_flag("UNCLEAR_QDRANT_FALLBACK", True)
    )

    should_retrieve_legal_qdrant = (
        final_route in {Route.QDRANT, Route.HYBRID}
        or unclear_fallback_enabled
    )

    if not should_retrieve_legal_qdrant:
        return result

    if retrieve_context_fn is None:
        result.errors.append(
            "Legal Qdrant retrieval was required, but "
            "retrieve_context_fn was not provided."
        )
        return result

    qdrant_decision = resolution.final
    if unclear_fallback_enabled:
        result.qdrant_fallback_used = True
        qdrant_decision = _make_unclear_qdrant_decision(resolution.final)

    try:
        qdrant_result = retrieve_legal_references(
            query=query,
            decision=qdrant_decision,
            retrieve_context_fn=retrieve_context_fn,
            limit=limit,
        )
        result.qdrant_result = qdrant_result

        if not unclear_fallback_enabled:
            result.qdrant_evidence = legal_results_to_evidence(qdrant_result)
            return result

        top_score = _top_raw_qdrant_score(qdrant_result.context_results)
        threshold = _unclear_qdrant_threshold()

        result.qdrant_top_dense_score = top_score
        result.qdrant_relevance_threshold = threshold
        result.qdrant_relevance_accepted = bool(qdrant_result.context_results)

        print(
            "[UNCLEAR → LEGAL_QDRANT] "
            f"top_dense_score={top_score} "
            f"threshold={threshold} "
            f"accepted={result.qdrant_relevance_accepted}"
        )

        if result.qdrant_relevance_accepted:
            result.qdrant_evidence = legal_results_to_evidence(qdrant_result)

    except Exception as error:
        result.errors.append(
            "Legal Qdrant retrieval failed: "
            f"{type(error).__name__}: {error}"
        )

    return result
