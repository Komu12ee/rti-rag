from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from typing import Any

from .schemas import Section4TriggerResult, TenderIntent, TriggerSource


ROMAN_SUBCLAUSES = (
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
    "xv",
    "xvi",
    "xvii",
)

SUBCLAUSE_CATEGORIES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "i": ("organisation_functions_duties", ("organisation", "functions", "duties"), ("संगठन", "कार्य", "कर्तव्य")),
    "ii": ("powers_duties_officers", ("powers", "duties of officers"), ("शक्तियां", "अधिकारियों के कर्तव्य")),
    "iii": ("decision_making_procedure", ("decision making", "decision-making", "procedure"), ("निर्णय प्रक्रिया",)),
    "iv": ("norms_for_functions", ("norms", "discharge of functions"), ("मानदंड", "कार्यों का निर्वहन")),
    "v": ("rules_regulations_manuals", ("rules", "regulations", "manuals", "instructions"), ("नियम", "विनियम", "मैनुअल", "निर्देश")),
    "vi": ("categories_of_documents", ("categories of documents", "documents held"), ("दस्तावेजों की श्रेणी", "अभिलेख")),
    "vii": ("public_consultation", ("public consultation", "consultative arrangement"), ("परामर्श व्यवस्था", "जन परामर्श")),
    "viii": ("boards_councils_committees", ("board", "council", "committee", "meetings"), ("बोर्ड", "परिषद", "समिति", "बैठक")),
    "ix": ("officer_employee_directory", ("directory of officers", "employee directory"), ("अधिकारियों की निर्देशिका", "कर्मचारियों की निर्देशिका")),
    "x": ("monthly_remuneration", ("monthly remuneration", "salary", "pay scale"), ("मासिक पारिश्रमिक", "वेतन")),
    "xi": ("budget_allocation_expenditure", ("budget allocation", "expenditure", "budget"), ("बजट", "व्यय", "आवंटन")),
    "xii": ("subsidy_programmes", ("subsidy", "beneficiaries"), ("सब्सिडी", "लाभार्थी")),
    "xiii": ("concessions_permits_authorisations", ("concession", "permit", "authorisation", "authorization"), ("रियायत", "परमिट", "प्राधिकार")),
    "xiv": ("information_available_electronically", ("electronic form", "available electronically", "online information"), ("इलेक्ट्रॉनिक रूप", "ऑनलाइन सूचना")),
    "xv": ("facilities_for_obtaining_information", ("facilities for obtaining information", "reading room", "library"), ("सूचना प्राप्त करने की सुविधा", "वाचनालय", "पुस्तकालय")),
    "xvi": ("pio_details", ("pio details", "public information officer", "cpio", "spio"), ("लोक सूचना अधिकारी", "पीआईओ")),
    "xvii": ("other_prescribed_information", ("other prescribed information",), ("अन्य विहित सूचना",)),
}

_EXPLICIT_PATTERNS = (
    re.compile(
        r"\b(?:section|sec\.?)\s*4\s*\(\s*1\s*\)\s*\(\s*b\s*\)"
        r"(?:\s*\(\s*(?P<sub>xvii|xvi|xv|xiv|xiii|xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i)\s*\))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<!\d)4\s*\(\s*1\s*\)\s*\(\s*b\s*\)"
        r"(?:\s*\(\s*(?P<sub>xvii|xvi|xv|xiv|xiii|xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i)\s*\))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:धारा\s*)?4\s*\(\s*1\s*\)\s*\(\s*(?:b|ख)\s*\)"
        r"(?:\s*\(\s*(?P<sub>xvii|xvi|xv|xiv|xiii|xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i)\s*\))?",
        re.IGNORECASE,
    ),
)

_DISCLOSURE_PATTERNS = (
    re.compile(r"\bproactive\s+disclosure\b", re.IGNORECASE),
    re.compile(r"\bsuo[\s-]+motu\s+(?:publication|disclosure)\b", re.IGNORECASE),
    re.compile(r"स्व\s*-?\s*प्रेरणा\s+से\s+(?:प्रकटीकरण|प्रकाशन)"),
    re.compile(r"सार्वजनिक\s+प्रकटीकरण"),
)

_AMBIGUOUS_ONLINE_REQUEST = re.compile(
    r"(?:rti|pio|सूचना|आरटीआई).{0,120}(?:website|online|published|वेबसाइट|ऑनलाइन|प्रकाशित)",
    re.IGNORECASE | re.DOTALL,
)

_TENDER_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "PAYMENT_SEARCH": (
        re.compile(r"\b(?:payment|invoice|deduction|outstanding\s+amount|milestone\s+payment)\b", re.IGNORECASE),
        re.compile(r"(?:भुगतान|किश्त|कटौती|बकाया)"),
    ),
    "CONTRACT_SEARCH": (
        re.compile(r"\b(?:contract|work\s+order|purchase\s+order|vendor|contractor|contract\s+value)\b", re.IGNORECASE),
        re.compile(r"(?:संविदा|अनुबंध|कार्यादेश|एजेंसी|ठेकेदार)"),
    ),
    "TENDER_SEARCH": (
        re.compile(r"\b(?:tender|procurement|bid|rfp|eoi|nit|boq|gem)\b", re.IGNORECASE),
        re.compile(r"(?:निविदा|क्रय|खरीद|बोली)"),
    ),
}

_FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "monthly_payments": ("monthly payment", "मासिक भुगतान"),
    "block_wise_payments": ("block-wise", "block wise", "ब्लॉक-वार"),
    "deductions": ("deduction", "कटौती"),
    "outstanding_amount": ("outstanding", "बकाया"),
    "invoice_details": ("invoice", "बीजक"),
    "contract_value": ("contract value", "अनुबंध मूल्य"),
    "selected_agency": ("selected agency", "selected bidder", "चयनित एजेंसी"),
    "tender_number": ("tender number", "tender no", "निविदा क्रमांक"),
}

_PROVISION_KEYS = frozenset(
    {
        "applicable_provisions",
        "legal_basis",
        "selected_provision_ids",
        "legal_reasoning",
        "pio_verification_required",
        "mandatory_response_elements",
        "recommended_response_path",
    }
)


def _normalise(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def _category_for_text(text: str, explicit_sub_clause: str | None) -> tuple[str | None, str | None, tuple[str, ...]]:
    if explicit_sub_clause in SUBCLAUSE_CATEGORIES:
        category, english, hindi = SUBCLAUSE_CATEGORIES[explicit_sub_clause]
        return explicit_sub_clause, category, tuple((*english, *hindi))

    folded = _normalise(text).casefold()
    best: tuple[int, str, str, tuple[str, ...]] | None = None
    for sub_clause, (category, english, hindi) in SUBCLAUSE_CATEGORIES.items():
        concepts = tuple((*english, *hindi))
        score = sum(1 for concept in concepts if concept.casefold() in folded)
        if score and (best is None or score > best[0]):
            best = (score, sub_clause, category, concepts)

    if best is None:
        return None, None, ("proactive disclosure", "official website")
    return best[1], best[2], best[3]


def _legal_provision_values(value: Any, key: str | None = None):
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            yield from _legal_provision_values(child_value, str(child_key))
        return
    if isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _legal_provision_values(child, key)
        return
    if key in _PROVISION_KEYS and value is not None:
        text = _normalise(value)
        if not re.search(
            r"(?:section\s*)?4\s*\(\s*1\s*\)\s*\(\s*(?:b|ख)\s*\).{0,50}"
            r"(?:not\s+applicable|not\s+relevant|irrelevant|लागू\s+नहीं)",
            text,
            flags=re.IGNORECASE,
        ):
            yield text


def _explicit_reference(text: str) -> tuple[bool, str | None, str]:
    for pattern in _EXPLICIT_PATTERNS:
        match = pattern.search(text)
        if match:
            sub_clause = (match.groupdict().get("sub") or "").casefold() or None
            return True, sub_clause, "Explicit Section 4(1)(b) reference."
    for pattern in _DISCLOSURE_PATTERNS:
        if pattern.search(text):
            return True, None, "Explicit proactive-disclosure reference."
    return False, None, ""


def detect_tender_intent(text: str) -> TenderIntent:
    normalised = _normalise(text)
    matched_type: str | None = None
    for intent_type in ("PAYMENT_SEARCH", "CONTRACT_SEARCH", "TENDER_SEARCH"):
        if any(pattern.search(normalised) for pattern in _TENDER_PATTERNS[intent_type]):
            matched_type = intent_type
            break

    fields = tuple(
        field_name
        for field_name, phrases in _FIELD_PATTERNS.items()
        if any(phrase.casefold() in normalised.casefold() for phrase in phrases)
    )
    return TenderIntent(
        tender_intent=matched_type is not None,
        intent_type=matched_type,
        requested_fields=fields,
    )


SemanticClassifier = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def detect_section4_trigger(
    query: str,
    legal_analysis: Mapping[str, Any] | None = None,
    *,
    semantic_classifier: SemanticClassifier | None = None,
) -> Section4TriggerResult:
    text = _normalise(query)
    tender = detect_tender_intent(text)

    matched, explicit_sub_clause, reason = _explicit_reference(text)
    if matched:
        sub_clause, category, concepts = _category_for_text(text, explicit_sub_clause)
        return Section4TriggerResult(
            triggered=True,
            trigger_type="SECTION_4_1_B",
            trigger_source=TriggerSource.EXPLICIT_REFERENCE,
            sub_clause=sub_clause,
            confidence=1.0,
            reason=reason,
            tender_intent=tender.tender_intent,
            category=category,
            search_concepts=concepts,
        )

    legal_values = tuple(_legal_provision_values(legal_analysis or {}))
    legal_text = "\n".join(legal_values)
    legal_match, legal_sub_clause, _ = _explicit_reference(legal_text)
    if legal_match:
        sub_clause, category, concepts = _category_for_text(text, legal_sub_clause)
        return Section4TriggerResult(
            triggered=True,
            trigger_type="SECTION_4_1_B",
            trigger_source=TriggerSource.LEGAL_ANALYSIS,
            sub_clause=sub_clause,
            confidence=0.95,
            reason="Validated legal analysis cites Section 4(1)(b).",
            tender_intent=tender.tender_intent,
            category=category,
            search_concepts=concepts,
        )

    if semantic_classifier is not None and _AMBIGUOUS_ONLINE_REQUEST.search(text):
        try:
            classified = dict(semantic_classifier(text, legal_analysis or {}))
            confidence = float(classified.get("confidence", 0.0))
            is_section4 = (
                classified.get("triggered") is True
                and classified.get("trigger_type") == "SECTION_4_1_B"
                and confidence >= 0.70
            )
            if is_section4:
                raw_sub_clause = str(classified.get("sub_clause") or "").casefold()
                sub_clause = raw_sub_clause if raw_sub_clause in ROMAN_SUBCLAUSES else None
                sub_clause, category, concepts = _category_for_text(text, sub_clause)
                return Section4TriggerResult(
                    triggered=True,
                    trigger_type="SECTION_4_1_B",
                    trigger_source=TriggerSource.SEMANTIC_CLASSIFIER,
                    sub_clause=sub_clause,
                    confidence=min(1.0, max(0.0, confidence)),
                    reason="Structured classifier identified material Section 4(1)(b) relevance.",
                    tender_intent=tender.tender_intent,
                    category=category,
                    search_concepts=concepts,
                )
        except (TypeError, ValueError, RuntimeError):
            pass

    return Section4TriggerResult(
        triggered=False,
        trigger_type=None,
        trigger_source=TriggerSource.NONE,
        confidence=0.0,
        reason="No material Section 4(1)(b) trigger was established.",
        tender_intent=False,
    )
