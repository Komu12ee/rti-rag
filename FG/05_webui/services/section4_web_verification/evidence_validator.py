from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date
from urllib.parse import urlsplit

from .config import Section4Config
from .schemas import EntityRef, EvidenceItem, RetrievedDocument, SearchPlan
from .security import SecurityError, normalize_hostname


_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "tender_number": ("tender no", "tender number", "reference no", "निविदा क्रमांक", "निविदा संख्या"),
    "selected_agency": ("selected bidder", "successful bidder", "selected agency", "awarded to", "चयनित एजेंसी"),
    "contract_value": ("contract value", "awarded value", "agreement value", "अनुबंध मूल्य"),
    "payment_details": ("payment made", "amount paid", "payment details", "भुगतान किया", "भुगतान विवरण"),
    "monthly_payments": ("monthly payment", "month-wise payment", "मासिक भुगतान", "माहवार भुगतान"),
    "block_wise_payments": ("block-wise payment", "block wise payment", "ब्लॉक-वार भुगतान"),
    "deductions": ("deduction", "amount deducted", "कटौती"),
    "outstanding_amount": ("outstanding amount", "unpaid balance", "amount due", "बकाया राशि"),
    "invoice_details": ("invoice no", "invoice number", "invoice date", "बीजक"),
    "budget_allocation": ("budget allocation", "budget provision", "बजट आवंटन"),
    "expenditure": ("actual expenditure", "expenditure incurred", "व्यय"),
    "officer_directory": ("directory of officers", "name and designation", "अधिकारी निर्देशिका"),
    "monthly_remuneration": ("monthly remuneration", "pay scale", "मासिक पारिश्रमिक"),
    "pio_details": ("public information officer", "central public information officer", "state public information officer", "लोक सूचना अधिकारी"),
}

_PAYMENT_FIELDS = frozenset(
    {"payment_details", "monthly_payments", "block_wise_payments", "deductions", "outstanding_amount", "invoice_details"}
)
_EXECUTION_PAYMENT_MARKERS = (
    "payment made",
    "amount paid",
    "paid on",
    "invoice paid",
    "payment voucher",
    "ledger",
    "running account bill",
    "भुगतान किया",
    "भुगतान दिनांक",
    "भुगतान वाउचर",
    "लेखा बही",
)
_TENDER_MARKERS = (
    "tender",
    "notice inviting tender",
    "request for proposal",
    "expression of interest",
    "bid document",
    "boq",
    "निविदा",
    "बोली",
)
_NAVIGATION_TITLES = ("sitemap", "site map", "search", "home page", "index of")
_TEXT_DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-/.]([01]?\d)[-/.]([0-3]?\d)\b"),
    re.compile(r"\b([0-3]?\d)[-/.]([01]?\d)[-/.](20\d{2})\b"),
)


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[^\W_]{2,}", _normalise(value), flags=re.UNICODE)
        if token not in {"the", "and", "for", "with", "from", "this", "that", "का", "के", "की", "और"}
    }


def _entity_groups(plan: SearchPlan) -> list[tuple[str, tuple[str, ...]]]:
    groups: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for entity in (
        plan.organisation,
        plan.public_authority,
        plan.department,
        plan.company,
        plan.project,
        plan.scheme,
        plan.district,
    ):
        if not isinstance(entity, EntityRef) or not entity.name:
            continue
        key = _normalise(entity.name)
        if key in seen:
            continue
        seen.add(key)
        aliases = tuple(dict.fromkeys(item for item in (entity.name, *entity.aliases) if item))
        groups.append((entity.name, aliases))
    for label, identifier in (("tender number", plan.tender_number), ("contract number", plan.contract_number)):
        if identifier:
            groups.append((identifier, (identifier, f"{label} {identifier}")))
    return groups


def _alias_present(text: str, aliases: Iterable[str]) -> bool:
    normalised = _normalise(text)
    text_tokens = _tokens(normalised)
    for alias in aliases:
        candidate = _normalise(alias)
        if len(candidate) >= 3 and candidate in normalised:
            return True
        alias_tokens = _tokens(candidate)
        if alias_tokens and len(alias_tokens & text_tokens) / len(alias_tokens) >= 0.8:
            return True
    return False


def _parse_date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    iso = re.search(r"\b(20\d{2})-([01]\d)-([0-3]\d)\b", raw)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    for index, pattern in enumerate(_TEXT_DATE_PATTERNS):
        match = pattern.search(raw)
        if not match:
            continue
        parts = tuple(int(item) for item in match.groups())
        year, month, day = parts if index == 0 else (parts[2], parts[1], parts[0])
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _document_dates(document: RetrievedDocument, text: str) -> tuple[date, ...]:
    values: list[date] = []
    publication_date = _parse_date(document.publication_date)
    if publication_date is not None:
        values.append(publication_date)
    for pattern_index, pattern in enumerate(_TEXT_DATE_PATTERNS):
        for match in pattern.finditer(text):
            parts = tuple(int(item) for item in match.groups())
            year, month, day = (
                parts if pattern_index == 0 else (parts[2], parts[1], parts[0])
            )
            try:
                parsed = date(year, month, day)
            except ValueError:
                continue
            if parsed not in values:
                values.append(parsed)
            if len(values) >= 100:
                return tuple(values)
    return tuple(values)


def _requested_date_matches(
    document: RetrievedDocument,
    text: str,
    plan: SearchPlan,
) -> bool:
    date_from = _parse_date(plan.date_from)
    date_to = _parse_date(plan.date_to)
    if date_from is None and date_to is None:
        return True
    lower = date_from or date.min
    upper = date_to or date.max
    if lower > upper:
        return False
    return any(lower <= candidate <= upper for candidate in _document_dates(document, text))


def _field_matches(text: str, *, tender_document: bool) -> set[str]:
    normalised = _normalise(text)
    fields = {
        field_name
        for field_name, terms in _FIELD_TERMS.items()
        if any(_normalise(term) in normalised for term in terms)
    }
    # A tender's payment schedule/terms are not evidence that an actual payment,
    # deduction, invoice settlement, or outstanding balance exists.
    if tender_document and not any(_normalise(marker) in normalised for marker in _EXECUTION_PAYMENT_MARKERS):
        fields.difference_update(_PAYMENT_FIELDS)
    return fields


def _is_tender_document(document: RetrievedDocument, text: str) -> bool:
    haystack = _normalise(f"{document.title} {document.final_url} {text[:8000]}")
    return any(_normalise(marker) in haystack for marker in _TENDER_MARKERS)


def _best_passage(page_text: str, needles: Iterable[str], *, limit: int = 520) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in page_text.splitlines() if line.strip()]
    if not lines:
        return ""
    normalised_needles = [_normalise(item) for item in needles if _normalise(item)]
    best_index = 0
    best_score = -1
    for index, line in enumerate(lines):
        folded = _normalise(line)
        score = sum(2 if needle in folded else 0 for needle in normalised_needles)
        score += min(4, len(_tokens(line) & set().union(*(_tokens(item) for item in normalised_needles))) if normalised_needles else 0)
        if score > best_score:
            best_score = score
            best_index = index
    start = max(0, best_index - 1)
    end = min(len(lines), best_index + 2)
    passage = " ".join(lines[start:end])
    return passage[:limit].rstrip()


def _approved_document_url(document: RetrievedDocument, config: Section4Config) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(document.final_url or document.url)
        if parsed.scheme.casefold() != "https" or parsed.username or parsed.password or not parsed.hostname:
            return None
        hostname = normalize_hostname(parsed.hostname)
    except (ValueError, SecurityError):
        return None
    if hostname not in config.allowed_domains:
        return None
    return parsed.geturl(), hostname


def validate_document_evidence(
    document: RetrievedDocument,
    plan: SearchPlan,
    config: Section4Config,
) -> list[EvidenceItem]:
    """Return only deterministic, passage-backed evidence from an approved document."""
    approved = _approved_document_url(document, config)
    if approved is None or not document.title or not document.retrieved_at:
        return []
    url, hostname = approved
    entity_groups = _entity_groups(plan)
    output: list[EvidenceItem] = []

    for page in document.pages:
        text = page.text.strip()
        if not text:
            continue
        tender_document = _is_tender_document(document, text)
        fields = _field_matches(text, tender_document=tender_document)
        entity_haystack = f"{document.title}\n{text}"
        matched_entities = tuple(
            name
            for name, aliases in entity_groups
            if _alias_present(entity_haystack, aliases)
        )

        # Every entity/identifier carried into the plan is material. Requiring
        # all groups prevents a document about the right organisation/vendor
        # but the wrong project, scheme, tender, or contract from becoming
        # verified evidence.
        if entity_groups and len(matched_entities) != len(entity_groups):
            continue
        if not _requested_date_matches(document, text, plan):
            continue

        requested = set(plan.requested_fields)
        supported_requested = requested & fields
        generic_supported = False
        if not requested:
            concepts = (*plan.search_concepts, "section 4(1)(b)", "proactive disclosure", "4(1)(b)")
            generic_supported = any(_normalise(item) in _normalise(text) for item in concepts if item)
            if generic_supported:
                fields.add(plan.category or "section_4_1_b_disclosure")

        # Keep a tender/award as partial evidence even when the requested
        # payment fields are absent, but never label those fields supported.
        tender_identity = tender_document and bool(fields & {"tender_number", "selected_agency", "contract_value"})
        if requested and not supported_requested and not tender_identity:
            continue
        if not requested and not generic_supported and not fields:
            continue

        title_folded = _normalise(document.title)
        if any(marker in title_folded for marker in _NAVIGATION_TITLES) and not supported_requested and not tender_identity:
            continue

        needles: list[str] = []
        for name, aliases in entity_groups:
            if name in matched_entities:
                needles.extend(aliases)
        for field in fields:
            needles.extend(_FIELD_TERMS.get(field, (field.replace("_", " "),)))
        needles.extend(plan.search_concepts)
        passage = _best_passage(text, needles)
        if not passage:
            continue

        entity_ratio = len(matched_entities) / max(1, len(entity_groups)) if entity_groups else 1.0
        requested_ratio = len(supported_requested) / max(1, len(requested)) if requested else 1.0
        relevance = round(min(1.0, 0.35 + 0.35 * entity_ratio + 0.30 * requested_ratio), 4)
        document_type = "tender" if tender_document else document.source_type
        output.append(
            EvidenceItem(
                title=document.title[:300],
                url=url,
                domain=hostname,
                document_type=document_type,
                publication_date=document.publication_date,
                page_number=page.page_number,
                section_heading=page.section_headings[0][:240] if page.section_headings else None,
                matched_text=passage,
                matched_entities=matched_entities,
                supported_fields=tuple(sorted(fields)),
                relevance_score=relevance,
                verified=True,
                document_hash=document.document_hash,
            )
        )

    return output


def validate_evidence_set(
    documents: Iterable[RetrievedDocument],
    plan: SearchPlan,
    config: Section4Config,
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    seen: set[tuple[str, int | None, tuple[str, ...]]] = set()
    for document in documents:
        for item in validate_document_evidence(document, plan, config):
            key = (item.document_hash or item.url, item.page_number, item.supported_fields)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(item)
    evidence.sort(key=lambda item: item.relevance_score, reverse=True)
    return evidence[: config.max_verified_results]
