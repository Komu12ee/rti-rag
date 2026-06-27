from __future__ import annotations
from services.hybrid_query_splitter import split_hybrid_query
from dataclasses import dataclass
from typing import Any

from services.officer_lookup_service import OfficerLookupResult, lookup_officers
from services.retrieval_plan import Route, RouterDecision


@dataclass(frozen=True)
class PostgresRetrievalResult:
    decision: RouterDecision
    lookup: OfficerLookupResult
    lookup_query: str
    source_type: str = "CG RTI Officer Registry"

    @property
    def has_results(self) -> bool:
        return bool(self.lookup.rows)
def retrieve_officer_registry(
    query: str,
    decision: RouterDecision,
    limit: int = 5,
) -> PostgresRetrievalResult:
    """
    Execute PostgreSQL officer retrieval only for PostgreSQL or Hybrid routes.

    For Hybrid queries, send only the officer-related clause to PostgreSQL.
    The legal clause will later be sent to Qdrant.
    """
    if decision.route not in {Route.POSTGRES, Route.HYBRID}:
        raise ValueError(
            f"PostgreSQL retrieval cannot run for route: {decision.route.value}"
        )

    lookup_query = query

    if decision.route == Route.HYBRID:
        parts = split_hybrid_query(query)
        lookup_query = parts.registry_query

    lookup = lookup_officers(
        query=lookup_query,
        limit=limit,
    )

    return PostgresRetrievalResult(
        decision=decision,
        lookup=lookup,
        lookup_query=lookup_query,
    )

def officer_results_to_context(
    result: PostgresRetrievalResult,
) -> list[dict[str, Any]]:
    """
    Convert PostgreSQL rows into source-labelled evidence.

    Later, Flask/Qdrant/LLM can use this as grounded context.
    """
    evidence: list[dict[str, Any]] = []

    if result.lookup.mode == "DIRECTORY":
        for row in result.lookup.rows:
            content = (
                f"Role: {row.get('rti_role')}\n"
                f"Officer: {row.get('officer_name') or 'Not listed'}\n"
                f"Email: {row.get('email') or 'Not listed'}\n"
                f"Designations: {', '.join(row.get('designations') or [])}\n"
                f"Department: {row.get('department_name') or 'Not listed'}\n"
                f"District: {row.get('district_name') or 'Not listed'}\n"
                f"Active portal assignments: {row.get('assigned_office_count', 0)}\n"
                f"Sample registered offices: "
                f"{', '.join(row.get('sample_office_names') or [])}"
            )

            evidence.append(
                {
                    "source_type": result.source_type,
                    "mode": "DIRECTORY",
                    "content": content,
                    "metadata": row,
                }
            )

        return evidence

    for row in result.lookup.rows:
        content = (
            f"Role: {row.get('rti_role')}\n"
            f"Officer: {row.get('officer_name') or 'Not listed'}\n"
            f"Email: {row.get('email') or 'Not listed'}\n"
            f"Designation: {row.get('designation') or 'Not listed'}\n"
            f"Office: {row.get('office_name') or 'Not listed'}\n"
            f"Office code: {row.get('office_code') or 'Not listed'}\n"
            f"Department: {row.get('department_name') or 'Not listed'}\n"
            f"District: {row.get('district_name') or 'Not listed'}"
        )

        evidence.append(
            {
                "source_type": result.source_type,
                "mode": "ASSIGNMENTS",
                "content": content,
                "metadata": row,
            }
        )

    return evidence