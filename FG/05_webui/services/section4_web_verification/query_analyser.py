from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from .schemas import EntityRef, SearchPlan, Section4TriggerResult, TenderIntent
from .trigger_detector import detect_tender_intent


_REQUESTED_FIELD_PHRASES: dict[str, tuple[str, ...]] = {
    "tender_number": ("tender number", "tender no", "निविदा क्रमांक"),
    "selected_agency": ("selected agency", "selected bidder", "चयनित एजेंसी"),
    "contract_value": ("contract value", "अनुबंध मूल्य"),
    "payment_details": ("payment details", "payments made", "भुगतान विवरण"),
    "monthly_payments": ("monthly payment", "मासिक भुगतान"),
    "block_wise_payments": ("block-wise", "block wise", "ब्लॉक-वार"),
    "deductions": ("deduction", "कटौती"),
    "outstanding_amount": ("outstanding", "unpaid balance", "बकाया"),
    "budget_allocation": ("budget allocation", "बजट आवंटन"),
    "expenditure": ("expenditure", "व्यय"),
    "officer_directory": ("directory of officers", "अधिकारी निर्देशिका"),
    "monthly_remuneration": ("monthly remuneration", "मासिक पारिश्रमिक"),
    "pio_details": ("pio details", "public information officer", "लोक सूचना अधिकारी"),
}

_KNOWN_ALIASES: dict[str, tuple[str, ...]] = {
    "chips": ("CHiPS", "CHIPS", "Chhattisgarh Infotech Promotion Society"),
    "chhattisgarh infotech promotion society": (
        "Chhattisgarh Infotech Promotion Society",
        "CHiPS",
        "CHIPS",
    ),
    "tata projects limited": ("Tata Projects Limited", "Tata Projects", "TPL"),
    "bharatnet phase-ii": ("BharatNet Phase-II", "BharatNet Phase 2", "Bharat Net Phase II"),
}


def _clean(value: Any, *, limit: int = 240) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _first(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _clean(mapping.get(key))
        if value:
            return value
    return None


def _aliases(name: str | None) -> tuple[str, ...]:
    if not name:
        return ()
    known = _KNOWN_ALIASES.get(name.casefold())
    if known:
        return known
    return (name,)


def _entity(name: str | None) -> EntityRef:
    return EntityRef(name=name, aliases=_aliases(name))


def _information_text(extraction: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    parts: list[str] = []
    record_types: list[str] = []
    points = extraction.get("information_points")
    if isinstance(points, list):
        for point in points:
            if not isinstance(point, Mapping):
                continue
            requested = _clean(point.get("requested_information"), limit=800)
            if requested:
                parts.append(requested)
            values = point.get("record_types_requested")
            if isinstance(values, list):
                record_types.extend(_clean(item) for item in values if _clean(item))
    return " ".join(parts), tuple(dict.fromkeys(record_types))


def _extract_company(text: str) -> str | None:
    known = re.search(r"\bTata\s+Projects(?:\s+Limited)?\b", text, re.IGNORECASE)
    if known:
        return "Tata Projects Limited"
    match = re.search(
        r"\b([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,5}\s+"
        r"(?:Private\s+Limited|Pvt\.?\s+Ltd\.?|Limited|Ltd\.?))\b",
        text,
    )
    return _clean(match.group(1)) if match else None


def _extract_project(text: str) -> str | None:
    match = re.search(
        r"\bBharat\s*Net\s+Phase\s*[- ]?(?:II|2)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return "BharatNet Phase-II"
    match = re.search(
        r"\b([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Za-z0-9&.'-]+){0,7}\s+(?:Project|Scheme))\b",
        text,
    )
    return _clean(match.group(1)) if match else None


def _identifier(text: str, label: str) -> str | None:
    match = re.search(
        rf"\b{label}\s*(?:number|no\.?|id|क्रमांक|संख्या)?\s*[:#-]?\s*"
        r"([A-Za-z0-9][A-Za-z0-9_./-]{2,60})",
        text,
        re.IGNORECASE,
    )
    return _clean(match.group(1), limit=64) if match else None


def _requested_fields(text: str) -> tuple[str, ...]:
    folded = text.casefold()
    matched = [
        field_name
        for field_name, phrases in _REQUESTED_FIELD_PHRASES.items()
        if any(phrase.casefold() in folded for phrase in phrases)
    ]
    # Hindi commonly separates the cadence from the noun, for example
    # "मासिक और ब्लॉक-वार भुगतान". Treat it as monthly payment only when both
    # words are present; "मासिक" alone is not enough.
    if "monthly_payments" not in matched and "मासिक" in folded and "भुगतान" in folded:
        matched.append("monthly_payments")
    return tuple(matched)


def _quote(value: str) -> str:
    return '"' + value.replace('"', " ").strip() + '"'


def _search_queries(
    entities: tuple[str, ...],
    fields: tuple[str, ...],
    *,
    tender: bool,
    fallback_text: str,
) -> tuple[str, ...]:
    base = " ".join(_quote(item) for item in entities if item)
    if not base:
        base = _clean(fallback_text, limit=160)
    if not base:
        return ()

    queries = [base]
    for field_name in fields[:4]:
        queries.append(f"{base} {field_name.replace('_', ' ')}")
    if tender:
        queries.extend((f"{base} tender", f"{base} contract", f"{base} payment"))
    return tuple(dict.fromkeys(query for query in queries if query.strip()))[:8]


def build_search_plan(
    query: str,
    rti_extraction: Mapping[str, Any] | None = None,
    trigger: Section4TriggerResult | None = None,
) -> SearchPlan:
    extraction = rti_extraction or {}
    extracted_text, record_types = _information_text(extraction)
    combined = _clean(f"{query} {extracted_text}", limit=4000)

    public_authority = _first(extraction, "public_authority", "organisation", "organization")
    if public_authority and public_authority.casefold() in {"chips", "chips society"}:
        public_authority = "Chhattisgarh Infotech Promotion Society"

    department = _first(extraction, "department")
    if not department:
        match = re.search(r"\b([A-Z][A-Za-z &-]{2,70}\s+Department)\b", combined)
        department = _clean(match.group(1)) if match else None

    organisation = public_authority
    if not organisation and re.search(r"\bCHiPS\b", combined, re.IGNORECASE):
        organisation = "Chhattisgarh Infotech Promotion Society"

    company = _first(extraction, "company", "vendor") or _extract_company(combined)
    project = _first(extraction, "project") or _extract_project(combined)
    district = _first(extraction, "district")
    scheme = _first(extraction, "scheme")
    tender_number = _first(extraction, "tender_number") or _identifier(combined, "tender|निविदा")
    contract_number = _first(extraction, "contract_number") or _identifier(combined, "contract|अनुबंध")

    period = extraction.get("period")
    period = period if isinstance(period, Mapping) else {}
    date_from = _first(period, "from")
    date_to = _first(period, "to")

    fields = _requested_fields(combined)
    detected_tender = detect_tender_intent(combined)
    tender_enabled = bool((trigger and trigger.tender_intent) or detected_tender.tender_intent)
    tender = TenderIntent(
        tender_intent=tender_enabled,
        intent_type=detected_tender.intent_type if tender_enabled else None,
        organisation=organisation,
        company=company,
        project=project,
        tender_number=tender_number,
        contract_number=contract_number,
        date_from=date_from,
        date_to=date_to,
        requested_fields=fields,
    )

    entity_names = tuple(
        item for item in (organisation, company, project, tender_number, contract_number) if item
    )
    queries = _search_queries(
        entity_names,
        fields,
        tender=tender_enabled,
        fallback_text=extracted_text or query,
    )

    return SearchPlan(
        organisation=_entity(organisation),
        public_authority=_entity(public_authority),
        department=_entity(department),
        company=_entity(company),
        project=_entity(project),
        district=_entity(district),
        scheme=_entity(scheme),
        tender_number=tender_number,
        contract_number=contract_number,
        date_from=date_from,
        date_to=date_to,
        requested_record_types=record_types,
        requested_fields=fields,
        sub_clause=trigger.sub_clause if trigger else None,
        category=trigger.category if trigger else None,
        search_concepts=trigger.search_concepts if trigger else (),
        search_queries=queries,
        tender=tender,
    )
