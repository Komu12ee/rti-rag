from __future__ import annotations

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
UNCLEAR_QDRANT_DOMAIN_TERMS = (
    "rti",
    "right to information",
    "आरटीआई",
    "सूचना का अधिकार",
    "information commission",
    "state information commission",
    "chhattisgarh state information commission",
    "cic",
    "sic",
    "cg sic",
    "cgsic",
    "cgrti",
    "first appeal",
    "second appeal",
    "public information officer",
    "pio",
    "faa",
    "अपील",
    "सूचना आयोग",
    "जन सूचना अधिकारी",
    "लोक सूचना अधिकारी",
)


def _should_try_unclear_qdrant_fallback(query: str) -> bool:
    normalized = (query or "").casefold().strip()

    return bool(normalized) and any(
        term in normalized
        for term in UNCLEAR_QDRANT_DOMAIN_TERMS
    )


def _make_unclear_qdrant_fallback_decision(
    query: str,
) -> RouterDecision:
    return RouterDecision(
        route=Route.QDRANT,
        confidence=0.50,
        reason=(
            "UNCLEAR route fallback: query appears RTI-related, "
            "so Qdrant document retrieval will be attempted."
        ),
        matched_signals=(
            "unclear_qdrant_fallback",
        ),
    )

@dataclass
class UnifiedRetrievalResult:
    resolution: RouteResolution
    postgres_result: Optional[PostgresRetrievalResult] = None
    qdrant_result: Optional[LegalQdrantRetrievalResult] = None

    postgres_evidence: list[dict[str, Any]] = field(default_factory=list)
    qdrant_evidence: list[dict[str, Any]] = field(default_factory=list)

    errors: list[str] = field(default_factory=list)
    qdrant_fallback_used: bool = False
    @property
    def combined_evidence(self) -> list[dict[str, Any]]:
        return [
            *self.postgres_evidence,
            *self.qdrant_evidence,
        ]

    @property
    def has_evidence(self) -> bool:
        return bool(self.combined_evidence)


def retrieve_from_all_sources(
    query: str,
    retrieve_context_fn: Callable[..., list[dict[str, Any]]] | None,
    limit: int = 5,
    router_timeout_seconds: int = 30,
) -> UnifiedRetrievalResult:
    """
    Resolve the route and retrieve from the required source(s).

    POSTGRES:
        Officer registry only.

    QDRANT:
        Legal knowledge only.

    HYBRID:
        PostgreSQL and Qdrant independently.

    UNCLEAR:
        No retrieval. The caller should ask for clarification later.
    """
    resolution = resolve_route(
        query=query,
        timeout_seconds=router_timeout_seconds,
    )

    final_route = resolution.final.route

    result = UnifiedRetrievalResult(
        resolution=resolution,
    )

    # PostgreSQL retrieval.
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
                f"PostgreSQL retrieval failed: {type(error).__name__}: {error}"
            )

        # Qdrant retrieval.
    #
    # Normal QDRANT/HYBRID routes always retrieve from db3.
    # UNCLEAR RTI-related queries get one Route-B fallback retrieval attempt.
    unclear_qdrant_fallback = (
        final_route == Route.UNCLEAR
        and _should_try_unclear_qdrant_fallback(query)
    )

    should_retrieve_qdrant = (
        final_route in {Route.QDRANT, Route.HYBRID}
        or unclear_qdrant_fallback
    )

    if should_retrieve_qdrant:
        if retrieve_context_fn is None:
            result.errors.append(
                "Qdrant retrieval was required, but retrieve_context_fn was not provided."
            )
        else:
            try:
                qdrant_decision = resolution.final

                if unclear_qdrant_fallback:
                    result.qdrant_fallback_used = True

                    qdrant_decision = (
                        _make_unclear_qdrant_fallback_decision(query)
                    )

                    print(
                        "[Route-B Fallback] Final route is UNCLEAR, "
                        "but query appears RTI-related. Searching Qdrant."
                    )

                qdrant_result = retrieve_legal_references(
                    query=query,
                    decision=qdrant_decision,
                    retrieve_context_fn=retrieve_context_fn,
                    limit=limit,
                )

                result.qdrant_result = qdrant_result

                result.qdrant_evidence = legal_results_to_evidence(
                    qdrant_result
                )

            except Exception as error:
                result.errors.append(
                    f"Qdrant retrieval failed: {type(error).__name__}: {error}"
                )
    return result        