from __future__ import annotations

from dataclasses import dataclass

from services.query_router import route_query
from services.retrieval_plan import RouterDecision


@dataclass(frozen=True)
class RouteResolution:
    """
    Final routing result.

    ``router_a`` and ``used_llm_fallback`` are retained for response/API
    compatibility. Router A is now the LLM router, and there is no second
    fallback classification call.
    """

    router_a: RouterDecision
    final: RouterDecision
    used_llm_fallback: bool

    @property
    def used_llm_router(self) -> bool:
        return self.used_llm_fallback


def resolve_route(
    query: str,
    timeout_seconds: int = 30,
) -> RouteResolution:
    """Resolve a query with one authoritative LLM routing call."""
    decision = route_query(
        query=query,
        timeout_seconds=timeout_seconds,
    )
    used_llm = "llm_router" in decision.matched_signals

    return RouteResolution(
        router_a=decision,
        final=decision,
        used_llm_fallback=used_llm,
    )
