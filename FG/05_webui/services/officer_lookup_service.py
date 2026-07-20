from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from services.officer_query_parser import (
    OfficerSearchCriteria,
    parse_officer_query,
)
from services.postgres_officer_repository import (
    find_by_office_code,
    find_officer_profiles_by_email,
    search_active_officers,
    search_officer_directory_summaries,
    search_officer_profiles_by_name,
)


LookupMode = Literal["ASSIGNMENTS", "DIRECTORY", "PROFILE"]


@dataclass(frozen=True)
class OfficerLookupResult:
    criteria: OfficerSearchCriteria
    mode: LookupMode
    rows: list[dict[str, Any]]
    is_ambiguous: bool = False
    name_query: str | None = None


def _deduplicate_assignment_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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


def _prefer_office_name_matches(
    rows: list[dict[str, Any]],
    search_text: str | None,
) -> list[dict[str, Any]]:
    """Discard incidental address matches when an office-name match exists."""
    needle = str(search_text or "").strip().casefold()
    if not needle:
        return rows

    office_matches = [
        row
        for row in rows
        if needle in str(row.get("office_name") or "").casefold()
    ]
    return office_matches or rows


def _is_broad_directory_query(
    criteria: OfficerSearchCriteria,
) -> bool:
    has_exact_identifier = bool(
        criteria.email or criteria.office_code
    )

    has_specific_text = bool(criteria.search_text)

    return (
        not has_exact_identifier
        and not has_specific_text
        and bool(criteria.rti_role)
        and bool(criteria.district or criteria.department)
    )


def _choose_name_candidates(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """
    Returns:
        chosen profiles, is_ambiguous

    Exact match:
        return directly when only one officer matches.

    Strong fuzzy match:
        return only when clearly stronger than the next candidate.

    Similar candidates:
        ask user for district, department, office, email, or office code.
    """
    if not rows:
        return [], False

    exact_rows = [
        row
        for row in rows
        if row.get("match_type")
        in {"EXACT_NORMALIZED", "EXACT_LOOSE_KEY"}
    ]

    if len(exact_rows) == 1:
        return exact_rows[:1], False

    if len(exact_rows) > 1:
        return exact_rows[:5], True

    top = rows[0]
    top_score = float(top.get("match_score") or 0.0)

    second_score = (
        float(rows[1].get("match_score") or 0.0)
        if len(rows) > 1
        else 0.0
    )

    clearly_best = (
        top_score >= 0.86
        and (
            len(rows) == 1
            or (top_score - second_score) >= 0.10
        )
    )

    if clearly_best:
        return [top], False

    credible_candidates = [
        row
        for row in rows
        if float(row.get("match_score") or 0.0) >= 0.67
    ]

    if credible_candidates:
        return credible_candidates[:5], True

    return [], False


def lookup_officers(
    query: str,
    limit: int = 10,
    default_role: str | None = None,
) -> OfficerLookupResult:
    criteria = parse_officer_query(query)
    limit = max(1, min(int(limit), 20))

    if default_role and not criteria.rti_role:
        normalized_default_role = default_role.strip().upper()
        if normalized_default_role not in {"PIO", "FAA"}:
            raise ValueError("default_role must be PIO, FAA, or None.")
        criteria = replace(
            criteria,
            rti_role=normalized_default_role,
        )

    if criteria.is_empty():
        return OfficerLookupResult(
            criteria=criteria,
            mode="ASSIGNMENTS",
            rows=[],
        )

    # 1. Exact email: return one grouped profile.
    if criteria.email:
        rows = find_officer_profiles_by_email(
            email=criteria.email,
            rti_role=criteria.rti_role,
            limit=limit,
        )

        return OfficerLookupResult(
            criteria=criteria,
            mode="PROFILE",
            rows=rows,
        )

    # 2. Exact official office code: assignment-level result is correct.
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

    # 3. Broad directory list.
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

    # 4. Person-name search:
    # Hindi name / English transliteration / spelling variation.
    if criteria.search_text:
        candidate_rows = search_officer_profiles_by_name(
            name_query=criteria.search_text,
            rti_role=criteria.rti_role,
            district=criteria.district,
            department=criteria.department,
            limit=min(max(limit, 5), 8),
        )

        chosen_rows, is_ambiguous = _choose_name_candidates(
            candidate_rows
        )

        if chosen_rows:
            return OfficerLookupResult(
                criteria=criteria,
                mode="PROFILE",
                rows=chosen_rows,
                is_ambiguous=is_ambiguous,
                name_query=criteria.search_text,
            )

    # 5. Existing office/designation search as final fallback.
    candidate_limit = min(max(limit * 5, 20), 50)

    rows = search_active_officers(
        search_text=criteria.search_text,
        rti_role=criteria.rti_role,
        district=criteria.district,
        department=criteria.department,
        limit=candidate_limit,
    )
    rows = _prefer_office_name_matches(rows, criteria.search_text)

    return OfficerLookupResult(
        criteria=criteria,
        mode="ASSIGNMENTS",
        rows=_deduplicate_assignment_rows(rows)[:limit],
    )
