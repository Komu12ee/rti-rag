from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from services.legal_qdrant_retriever import (
    LegalQdrantRetrievalResult,
    legal_results_to_evidence,
    retrieve_legal_references,
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
    qdrant_result: Optional[LegalQdrantRetrievalResult] = None

    postgres_evidence: list[dict[str, Any]] = field(default_factory=list)
    qdrant_evidence: list[dict[str, Any]] = field(default_factory=list)

    # Only relevant when the visible route remains UNCLEAR.
    qdrant_fallback_used: bool = False
    qdrant_relevance_accepted: bool | None = None
    qdrant_top_dense_score: float | None = None
    qdrant_relevance_threshold: float | None = None

    errors: list[str] = field(default_factory=list)

    @property
    def combined_evidence(self) -> list[dict[str, Any]]:
        return [
            *self.postgres_evidence,
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
        score = float(
            os.getenv(
                "UNCLEAR_QDRANT_MIN_DENSE_SCORE",
                "0.60",
            )
        )
    except ValueError:
        score = 0.60

    return max(0.0, min(score, 1.0))


def _raw_qdrant_score(item: dict[str, Any]) -> float | None:
    """
    Use point.score: the original Qdrant dense similarity score.

    Do not use item["score"] here because it is your later
    hybrid/RRF ranking score, not raw similarity.
    """
    point = item.get("point")
    raw_score = getattr(point, "score", None)

    try:
        return float(raw_score)
    except (TypeError, ValueError):
        return None


def _top_raw_qdrant_score(
    context_results: list[dict[str, Any]] | None,
) -> float | None:
    scores = []

    for item in context_results or []:
        score = _raw_qdrant_score(item)

        if score is not None:
            scores.append(score)

    return max(scores) if scores else None


def _make_unclear_qdrant_decision(
    original_decision: RouterDecision,
) -> RouterDecision:
    """
    Internal retrieval-only decision.

    The browser still sees UNCLEAR as the final route.
    This QDRANT decision exists only so the existing legal retriever
    can perform one fallback search.
    """
    return RouterDecision(
        route=Route.QDRANT,
        confidence=original_decision.confidence,
        reason=(
            "UNCLEAR fallback: Qdrant was searched before "
            "returning a Suchna Aayog not-found answer."
        ),
        matched_signals=(
            *original_decision.matched_signals,
            "unclear_qdrant_fallback",
        ),
    )


def retrieve_from_all_sources(
    query: str,
    retrieve_context_fn: Callable[..., list[dict[str, Any]]] | None,
    limit: int = 5,
    router_timeout_seconds: int = 30,
) -> UnifiedRetrievalResult:
    """
    POSTGRES:
        Officer registry only.

    QDRANT:
        Legal / FAQ / portal corpus.

    HYBRID:
        PostgreSQL + Qdrant.

    UNCLEAR:
        Always try Qdrant once.
        Generate an answer only if raw Qdrant similarity passes
        UNCLEAR_QDRANT_MIN_DENSE_SCORE.
    """
    resolution = resolve_route(
        query=query,
        timeout_seconds=router_timeout_seconds,
    )

    final_route = resolution.final.route

    result = UnifiedRetrievalResult(
        resolution=resolution,
    )

    # PostgreSQL retrieval
    if final_route in {Route.POSTGRES, Route.HYBRID}:
        try:
            postgres_result = retrieve_officer_registry(
                query=query,
                decision=resolution.final,
                limit=limit,
            )

            result.postgres_result = postgres_result
            result.postgres_evidence = officer_results_to_context(
                postgres_result
            )

        except Exception as error:
            result.errors.append(
                "PostgreSQL retrieval failed: "
                f"{type(error).__name__}: {error}"
            )

    unclear_fallback_enabled = (
        final_route == Route.UNCLEAR
        and _env_flag("UNCLEAR_QDRANT_FALLBACK", True)
    )

    should_retrieve_qdrant = (
        final_route in {Route.QDRANT, Route.HYBRID}
        or unclear_fallback_enabled
    )

    if should_retrieve_qdrant:
        if retrieve_context_fn is None:
            result.errors.append(
                "Qdrant retrieval was required, but "
                "retrieve_context_fn was not provided."
            )
            return result

        qdrant_decision = resolution.final

        if unclear_fallback_enabled:
            result.qdrant_fallback_used = True
            qdrant_decision = _make_unclear_qdrant_decision(
                resolution.final
            )

        try:
            qdrant_result = retrieve_legal_references(
                query=query,
                decision=qdrant_decision,
                retrieve_context_fn=retrieve_context_fn,
                limit=limit,
            )

            result.qdrant_result = qdrant_result

            # Normal QDRANT/HYBRID routes use their evidence directly.
            if not unclear_fallback_enabled:
                result.qdrant_evidence = legal_results_to_evidence(
                    qdrant_result
                )
                return result

            # UNCLEAR fallback must pass a relevance gate.
            top_score = _top_raw_qdrant_score(
                qdrant_result.context_results
            )

            threshold = _unclear_qdrant_threshold()

            result.qdrant_top_dense_score = top_score
            result.qdrant_relevance_threshold = threshold

            accepted = (
                top_score is not None
                and top_score >= threshold
            )

            result.qdrant_relevance_accepted = accepted

            print(
                "[UNCLEAR → QDRANT] "
                f"top_dense_score={top_score} "
                f"threshold={threshold} "
                f"accepted={accepted}"
            )

            if accepted:
                result.qdrant_evidence = legal_results_to_evidence(
                    qdrant_result
                )

        except Exception as error:
            result.errors.append(
                "Qdrant retrieval failed: "
                f"{type(error).__name__}: {error}"
            )

    return result