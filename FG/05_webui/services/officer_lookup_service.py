from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from services.officer_query_parser import (
    OfficerSearchCriteria,
    parse_officer_query,
)
from services.postgres_officer_repository import (
    find_by_email,
    find_by_office_code,
    search_active_officers,
    search_officer_directory_summaries,
)


LookupMode = Literal["ASSIGNMENTS", "DIRECTORY"]


@dataclass(frozen=True)
class OfficerLookupResult:
    criteria: OfficerSearchCriteria
    mode: LookupMode
    rows: list[dict[str, Any]]


def _deduplicate_assignment_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove exact repeated assignment rows only."""
    seen: set[tuple[Any, Any, Any]] = set()
    unique_rows: list[dict[str, Any]] = []

    for row in rows:
        key = (
            row.get("office_code"),
            row.get("officer_id"),
            row.get("rti_role"),
        )

        if key in seen:
            continue

        seen.add(key)
        unique_rows.append(row)

    return unique_rows


def _is_broad_directory_query(criteria: OfficerSearchCriteria) -> bool:
    """
    Broad query examples:
    - Show FAA in Balrampur.
    - School Education Department ke PIO dikhao.

    Exact query examples:
    - Pakradi school ka PIO kaun hai?
    - 9220043429 office ka PIO.
    - Find rr1901138@gmail.com.
    """
    has_exact_identifier = bool(criteria.email or criteria.office_code)
    has_specific_office_text = bool(criteria.search_text)

    return (
        not has_exact_identifier
        and not has_specific_office_text
        and bool(criteria.rti_role)
        and bool(criteria.district or criteria.department)
    )


def lookup_officers(
    query: str,
    limit: int = 10,
) -> OfficerLookupResult:
    """
    Natural-language officer question
        → parse filters
        → exact assignment search OR broad directory summary.
    """
    criteria = parse_officer_query(query)
    limit = max(1, min(int(limit), 20))

    if criteria.is_empty():
        return OfficerLookupResult(
            criteria=criteria,
            mode="ASSIGNMENTS",
            rows=[],
        )

    # 1. Exact email search.
    if criteria.email:
        rows = find_by_email(criteria.email)

        if criteria.rti_role:
            rows = [
                row
                for row in rows
                if row["rti_role"] == criteria.rti_role
            ]

        return OfficerLookupResult(
            criteria=criteria,
            mode="ASSIGNMENTS",
            rows=_deduplicate_assignment_rows(rows)[:limit],
        )

    # 2. Exact office-code search.
    if criteria.office_code:
        rows = find_by_office_code(
            office_code=criteria.office_code,
            rti_role=criteria.rti_role,
        )

        return OfficerLookupResult(
            criteria=criteria,
            mode="ASSIGNMENTS",
            rows=_deduplicate_assignment_rows(rows)[:limit],
        )

    # 3. Broad directory search: group repeated mappings by officer email.
    if _is_broad_directory_query(criteria):
        rows = search_officer_directory_summaries(
            rti_role=criteria.rti_role,
            district=criteria.district,
            department=criteria.department,
            limit=limit,
        )

        return OfficerLookupResult(
            criteria=criteria,
            mode="DIRECTORY",
            rows=rows,
        )

    # 4. Specific Hindi/English office or officer search.
    candidate_limit = min(max(limit * 5, 20), 50)

    rows = search_active_officers(
        search_text=criteria.search_text,
        rti_role=criteria.rti_role,
        district=criteria.district,
        department=criteria.department,
        limit=candidate_limit,
    )

    return OfficerLookupResult(
        criteria=criteria,
        mode="ASSIGNMENTS",
        rows=_deduplicate_assignment_rows(rows)[:limit],
    )