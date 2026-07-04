from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services.officer_query_parser import parse_officer_query


@dataclass(frozen=True)
class PioDirectoryQdrantRetrievalResult:
    lookup_query: str
    criteria: Any
    results: list[dict[str, Any]]
    source_type: str = "CG RTI Officer Directory (Qdrant)"

    @property
    def has_results(self) -> bool:
        return bool(self.results)


def _normalise_keyword_filter(value: object) -> str | None:
    """district_key and department_key were indexed in lowercase."""
    text = str(value or "").strip().casefold()
    return text or None


def _normalise_role_filter(value: object) -> str | None:
    """
    Qdrant payload stores rti_role as uppercase PIO / FAA.
    Qdrant keyword filters are exact and case-sensitive.
    """
    role = str(value or "").strip().upper()
    return role if role in {"PIO", "FAA"} else None


def retrieve_pio_directory_references(
    query: str,
    retrieve_pio_directory_fn: Callable[..., list[dict[str, Any]]],
    limit: int = 5,
) -> PioDirectoryQdrantRetrievalResult:
    criteria = parse_officer_query(query)
    limit = max(1, min(int(limit), 10))

    filters = {
        "rti_role": _normalise_role_filter(criteria.rti_role),
        "district_key": _normalise_keyword_filter(criteria.district),
        "department_key": _normalise_keyword_filter(criteria.department),
        "office_code": str(criteria.office_code or "").strip() or None,
        "email": str(criteria.email or "").strip() or None,
    }

    results = retrieve_pio_directory_fn(
        query_text=query,
        num_context=limit,
        filters=filters,
    ) or []

    return PioDirectoryQdrantRetrievalResult(
        lookup_query=query,
        criteria=criteria,
        results=results,
    )


def pio_directory_results_to_evidence(
    result: PioDirectoryQdrantRetrievalResult,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []

    for index, item in enumerate(result.results, start=1):
        payload = dict(item.get("payload") or {})
        score = float(item.get("score", 0.0) or 0.0)

        content = "\n".join(
            [
                f"Role: {payload.get('rti_role') or 'Not listed'}",
                f"Officer: {payload.get('officer_name') or 'Not listed'}",
                f"Email: {payload.get('email') or 'Not listed'}",
                f"Designation: {payload.get('designation') or 'Not listed'}",
                f"Office: {payload.get('office_name') or 'Not listed'}",
                f"Office code: {payload.get('office_code') or 'Not listed'}",
                f"Department: {payload.get('department_name') or 'Not listed'}",
                f"District: {payload.get('district') or 'Not listed'}",
                f"Address: {payload.get('office_address') or 'Not listed'}",
                f"Directory source updated: "
                f"{payload.get('source_generated_at') or 'Not listed'}",
            ]
        )

        metadata = {
            **payload,
            "rank": item.get("rank", index),
            "score": score,
            "source": "pio_directory_v1",
            "_lookup_mode": "PIO_QDRANT",
            "_lookup_ambiguous": False,
            "_name_query": "",
            "_pio_qdrant_search_mode": item.get("search_mode", ""),
        }

        evidence.append(
            {
                "source_type": result.source_type,
                "mode": "PIO_QDRANT",
                "content": content,
                "metadata": metadata,
            }
        )

    return evidence
