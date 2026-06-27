from __future__ import annotations

from dataclasses import dataclass

from services.llm_fallback_router import classify_with_llm
from services.query_router import route_query
from services.retrieval_plan import Route, RouterDecision


MIN_ROUTER_B_CONFIDENCE = 0.70


@dataclass(frozen=True)
class RouteResolution:
    router_a: RouterDecision
    final: RouterDecision
    used_llm_fallback: bool


def _make_low_confidence_unclear(
    router_b: RouterDecision,
) -> RouterDecision:
    return RouterDecision(
        route=Route.UNCLEAR,
        confidence=router_b.confidence,
        reason=(
            "Router B route was not accepted because its confidence "
            f"was below {MIN_ROUTER_B_CONFIDENCE:.2f}."
        ),
        matched_signals=(
            "router_a_fallback",
            "llm_fallback",
            "low_confidence_rejected",
        ),
    )


def resolve_route(
    query: str,
    timeout_seconds: int = 30,
) -> RouteResolution:
    """
    Router A first.

    Router B is called only when Router A is unclear or has low confidence.
    Router B never retrieves data or answers the user.
    """
    router_a = route_query(query)

    # Clear deterministic decision: do not spend an LLM call.
    if not router_a.needs_llm_fallback:
        return RouteResolution(
            router_a=router_a,
            final=router_a,
            used_llm_fallback=False,
        )

    router_b = classify_with_llm(
        query=query,
        timeout_seconds=timeout_seconds,
    )

    # Router B says unclear: preserve that decision.
    if router_b.route == Route.UNCLEAR:
        return RouteResolution(
            router_a=router_a,
            final=router_b,
            used_llm_fallback=True,
        )

    # Do not accept a weak LLM classification.
    if router_b.confidence < MIN_ROUTER_B_CONFIDENCE:
        return RouteResolution(
            router_a=router_a,
            final=_make_low_confidence_unclear(router_b),
            used_llm_fallback=True,
        )

    return RouteResolution(
        router_a=router_a,
        final=router_b,
        used_llm_fallback=True,
    )