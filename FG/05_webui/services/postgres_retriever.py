from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.hybrid_query_splitter import split_hybrid_query
from services.officer_lookup_service import (
    OfficerLookupResult,
    lookup_officers,
)
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
    if decision.route not in {Route.POSTGRES, Route.HYBRID}:
        raise ValueError(
            "PostgreSQL retrieval cannot run for route: "
            f"{decision.route.value}"
        )

    lookup_query = query

    if decision.route == Route.HYBRID:
        parts = split_hybrid_query(query)
        lookup_query = parts.registry_query

    lookup = lookup_officers(
        query=lookup_query,
        limit=limit,
        # In an RTI assistant, a named public-authority contact request with
        # no explicit role means its registered PIO contact. An explicit FAA
        # role parsed from the query still takes precedence.
        default_role="PIO",
    )

    return PostgresRetrievalResult(
        decision=decision,
        lookup=lookup,
        lookup_query=lookup_query,
    )


def _join_values(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )

    return str(value or "").strip()


def _with_lookup_metadata(
    row: dict[str, Any],
    result: PostgresRetrievalResult,
) -> dict[str, Any]:
    metadata = dict(row)

    metadata["_lookup_ambiguous"] = result.lookup.is_ambiguous
    metadata["_name_query"] = result.lookup.name_query or ""
    metadata["_lookup_mode"] = result.lookup.mode

    return metadata


def officer_results_to_context(
    result: PostgresRetrievalResult,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []

    if result.lookup.mode == "PROFILE":
        for row in result.lookup.rows:
            content = (
                f"Role: {row.get('rti_role')}\n"
                f"Officer: {row.get('officer_name') or 'Not listed'}\n"
                f"Email: {row.get('email') or 'Not listed'}\n"
                f"Designation: {row.get('designation') or 'Not listed'}\n"
                f"Match type: {row.get('match_type') or 'Not listed'}\n"
                f"Match confidence: {row.get('match_score') or 0}\n"
                f"Districts: {_join_values(row.get('district_names')) or 'Not listed'}\n"
                f"Departments: {_join_values(row.get('department_names')) or 'Not listed'}\n"
                f"Active portal assignments: "
                f"{row.get('assigned_office_count', 0)}\n"
                f"Sample registered offices: "
                f"{_join_values(row.get('sample_office_names')) or 'Not listed'}"
            )

            evidence.append(
                {
                    "source_type": result.source_type,
                    "mode": "PROFILE",
                    "content": content,
                    "metadata": _with_lookup_metadata(row, result),
                }
            )

        return evidence

    if result.lookup.mode == "DIRECTORY":
        for row in result.lookup.rows:
            content = (
                f"Role: {row.get('rti_role')}\n"
                f"Officer: {row.get('officer_name') or 'Not listed'}\n"
                f"Email: {row.get('email') or 'Not listed'}\n"
                f"Designations: "
                f"{_join_values(row.get('designations')) or 'Not listed'}\n"
                f"Department: {row.get('department_name') or 'Not listed'}\n"
                f"District: {row.get('district_name') or 'Not listed'}\n"
                f"Active portal assignments: "
                f"{row.get('assigned_office_count', 0)}"
            )

            evidence.append(
                {
                    "source_type": result.source_type,
                    "mode": "DIRECTORY",
                    "content": content,
                    "metadata": _with_lookup_metadata(row, result),
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
                "metadata": _with_lookup_metadata(row, result),
            }
        )

    return evidence
