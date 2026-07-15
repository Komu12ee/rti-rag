from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .schemas import (
    EvidenceItem,
    SearchPlan,
    Section4TriggerResult,
    SearchedSource,
    SourceSearchStatus,
    VerificationResult,
    VerificationStatus,
)


def search_not_triggered_result(trigger: Section4TriggerResult | None = None) -> VerificationResult:
    return VerificationResult(
        triggered=False,
        trigger_reason=(trigger.reason if trigger else "No material Section 4(1)(b) trigger was established."),
        trigger_source=trigger.trigger_source if trigger else VerificationResult().trigger_source,
        sub_clause=trigger.sub_clause if trigger else None,
        status=VerificationStatus.SEARCH_NOT_TRIGGERED,
        verification_timestamp=datetime.now(timezone.utc).isoformat(),
    )


def source_unavailable_result(
    trigger: Section4TriggerResult,
    *,
    organisation: str | None = None,
    subject: str | None = None,
    searched_sources: Iterable[SearchedSource] = (),
    error_code: str = "VERIFICATION_FAILED",
) -> VerificationResult:
    return VerificationResult(
        triggered=True,
        trigger_reason=trigger.trigger_type or "SECTION_4_1_B",
        trigger_source=trigger.trigger_source,
        sub_clause=trigger.sub_clause,
        status=VerificationStatus.SOURCE_UNAVAILABLE,
        organisation=organisation,
        subject=subject,
        searched_sources=tuple(searched_sources),
        verification_timestamp=datetime.now(timezone.utc).isoformat(),
        warnings=(
            "Public-domain verification could not be completed; departmental records must still be checked.",
        ),
        errors=({"code": error_code, "message": "An approved source could not be verified safely."},),
    )


def merge_verification_result(
    trigger: Section4TriggerResult,
    plan: SearchPlan,
    searched_sources: Iterable[SearchedSource],
    evidence: Iterable[EvidenceItem],
    *,
    subject: str | None = None,
) -> VerificationResult:
    sources = tuple(searched_sources)
    items = tuple(item for item in evidence if item.verified and item.matched_text and item.url)
    available = tuple(sorted({field for item in items for field in item.supported_fields}))
    requested = tuple(dict.fromkeys(plan.requested_fields))
    missing = tuple(field for field in requested if field not in set(available))
    unavailable = [source for source in sources if source.status == SourceSearchStatus.UNAVAILABLE]
    successes = [source for source in sources if source.status in {SourceSearchStatus.SUCCESS, SourceSearchStatus.NO_RESULTS}]

    if items:
        status = (
            VerificationStatus.FOUND
            if not missing and not unavailable
            else VerificationStatus.PARTIALLY_FOUND
        )
    elif unavailable:
        status = VerificationStatus.SOURCE_UNAVAILABLE
    elif successes:
        status = VerificationStatus.NOT_FOUND
    else:
        status = VerificationStatus.SOURCE_UNAVAILABLE

    warnings: list[str] = []
    errors: list[dict[str, str]] = []
    if status == VerificationStatus.PARTIALLY_FOUND:
        warnings.append(
            "Only the listed fields were verified online; remaining fields require departmental record checks."
        )
    elif status == VerificationStatus.NOT_FOUND:
        warnings.append(
            "Online non-discovery does not establish that the record does not exist in departmental custody."
        )
    elif status == VerificationStatus.SOURCE_UNAVAILABLE:
        warnings.append(
            "One or more approved sources were unavailable; public-domain verification is incomplete."
        )
    if unavailable and status != VerificationStatus.SOURCE_UNAVAILABLE:
        warnings.append("Some approved sources were unavailable during an otherwise partial verification.")
    for source in unavailable:
        errors.append(
            {
                "source": source.adapter_id,
                "code": source.error_code or "SOURCE_UNAVAILABLE",
                "message": "The approved source could not be checked safely.",
            }
        )

    organisation = plan.organisation.name or plan.public_authority.name
    return VerificationResult(
        triggered=True,
        trigger_reason=trigger.trigger_type or "SECTION_4_1_B",
        trigger_source=trigger.trigger_source,
        sub_clause=trigger.sub_clause,
        status=status,
        organisation=organisation,
        subject=subject,
        searched_sources=sources,
        found_items=items,
        available_fields=available,
        missing_fields=missing,
        verification_timestamp=datetime.now(timezone.utc).isoformat(),
        warnings=tuple(dict.fromkeys(warnings)),
        errors=tuple(errors),
    )
