from __future__ import annotations

"""Evidence-bound CIC/CGSIC precedent retrieval for an existing PIO advisory."""

import json
import os
import re
from typing import Any, Iterator

from services.llm_provider import LLMProviderError, generate_text, stream_text


PRECEDENT_COLLECTIONS = (
    "cgsic_important_decisions_v1",
    "cic",
)
MAX_RESULTS_PER_COLLECTION = 3
NOT_FOUND = "Not found in retrieved case text."
NOT_FOUND_HI = "प्राप्त निर्णय पाठ में नहीं मिला।"

CASE_FIELD_BOUNDARIES = (
    "information sought",
    "information requested",
    "rti application",
    "pio reply",
    "cpio reply",
    "spio reply",
    "faa order",
    "first appeal",
    "respondent",
    "appellant",
    "commission",
    "observations",
    "decision",
    "final decision",
    "order",
    "direction",
    "facts",
    "grounds",
    "prayer",
)


class PIOPrecedentError(RuntimeError):
    """Raised when supporting precedent retrieval cannot be completed safely."""


def _compact(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].strip()


def _normalise_answer_language(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value or "").strip().casefold()
    if text in {"hi", "hin", "hindi", "हिंदी", "हिन्दी"}:
        return "hi"
    if text in {"en", "eng", "english"}:
        return "en"
    return None


def _resolved_answer_language(
    answer_language: Any,
    rti_extraction: dict[str, Any],
) -> str:
    """Prefer the explicit UI choice, with RTI-language fallback for old callers."""
    explicit = _normalise_answer_language(answer_language)
    if explicit:
        return explicit

    extracted = _normalise_answer_language(rti_extraction.get("language"))
    return extracted or "en"


def _is_hindi_context(
    rti_extraction: dict[str, Any],
    answer_language: Any = None,
) -> bool:
    return _resolved_answer_language(answer_language, rti_extraction) == "hi"


def _unique_texts(values: list[Any], limit: int = 8, item_limit: int = 280) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = _compact(value, item_limit)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _extract_issue_summary(
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
) -> dict[str, list[str]]:
    requested = _unique_texts(
        [
            point.get("requested_information")
            for point in rti_extraction.get("information_points", [])
            if isinstance(point, dict)
        ],
        limit=6,
    )

    provisions: list[str] = []
    issues: list[str] = []
    actions: list[str] = []

    for point in legal_analysis.get("point_analysis", []):
        if not isinstance(point, dict):
            continue
        provisions.extend(point.get("applicable_provisions") or [])
        issues.extend(
            [
                point.get("request_type"),
                point.get("record_status"),
                point.get("legal_reasoning"),
            ]
        )
        actions.append(point.get("recommended_response_path"))

    for check in legal_analysis.get("case_level_checks", []):
        if not isinstance(check, dict):
            continue
        provisions.extend(check.get("legal_basis") or [])
        issues.extend([check.get("check"), check.get("status")])

    return {
        "requested_information": requested,
        "applicable_provisions": _unique_texts(provisions, limit=10, item_limit=80),
        "legal_issues": _unique_texts(issues, limit=8),
        "response_paths": _unique_texts(actions, limit=5),
    }


def build_precedent_query(
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
) -> str:
    """Build a retrieval query only from validated PIO workflow outputs."""
    summary = _extract_issue_summary(rti_extraction, legal_analysis)

    parts = [
        "RTI Commission decision precedent relevant to a PIO advisory.",
    ]
    if summary["requested_information"]:
        parts.append(
            "Information requested: " + "; ".join(summary["requested_information"])
        )
    if summary["applicable_provisions"]:
        parts.append(
            "Applicable RTI provisions: " + ", ".join(summary["applicable_provisions"])
        )
    if summary["legal_issues"]:
        parts.append("Legal issues: " + "; ".join(summary["legal_issues"]))
    if summary["response_paths"]:
        parts.append("PIO response considerations: " + "; ".join(summary["response_paths"]))

    return "\n".join(parts).strip()


def _available_collections(rag_module: Any) -> tuple[list[str], list[str]]:
    client = rag_module.ensure_qdrant_client()
    available: list[str] = []
    missing: list[str] = []

    for collection in PRECEDENT_COLLECTIONS:
        if client.collection_exists(collection):
            available.append(collection)
        else:
            missing.append(collection)

    return available, missing


def _payload_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _compact(payload.get(key), 220)
        if value:
            return value
    return ""


def _clean_case_field(value: Any, limit: int = 700) -> str:
    text = _compact(value, limit)
    text = re.sub(r"^(?:[:\-\s])+|(?:[:\-\s])+$", "", text).strip()
    return text or NOT_FOUND


def _case_text(result: dict[str, Any]) -> str:
    return str(result.get("text") or "").strip()


def _extract_after_labels(
    text: str,
    labels: tuple[str, ...],
    *,
    limit: int = 700,
) -> str:
    if not text:
        return NOT_FOUND

    label_pattern = "|".join(re.escape(label) for label in labels)
    boundary_pattern = "|".join(re.escape(label) for label in CASE_FIELD_BOUNDARIES)
    pattern = re.compile(
        rf"(?is)\b(?:{label_pattern})\b\s*(?:[:\-]\s*)?"
        rf"(.{{20,{limit * 2}}}?)(?=\b(?:{boundary_pattern})\b\s*(?:[:\-]|$)|$)"
    )

    match = pattern.search(text)
    if not match:
        return NOT_FOUND

    return _clean_case_field(match.group(1), limit)


def _extract_sentence_with_terms(
    text: str,
    terms: tuple[str, ...],
    *,
    limit: int = 700,
) -> str:
    if not text:
        return NOT_FOUND

    sentences = re.split(r"(?<=[.!?])\s+", text)
    selected: list[str] = []
    for sentence in sentences:
        lowered = sentence.casefold()
        if any(term.casefold() in lowered for term in terms):
            selected.append(_compact(sentence, 320))
        if len(" ".join(selected)) >= limit or len(selected) >= 3:
            break

    if not selected:
        return NOT_FOUND

    return _clean_case_field(" ".join(selected), limit)


def _extract_information_sought(text: str) -> str:
    labelled = _extract_after_labels(
        text,
        (
            "Information sought",
            "Information requested",
            "RTI application",
            "Facts",
        ),
    )
    if labelled != NOT_FOUND:
        return labelled

    return _extract_sentence_with_terms(
        text,
        (
            "information sought",
            "information requested",
            "sought vide RTI",
            "requested information",
            "RTI application dated",
        ),
    )


def _extract_pio_faa_response(text: str) -> str:
    labelled = _extract_after_labels(
        text,
        (
            "PIO reply",
            "CPIO reply",
            "SPIO reply",
            "FAA order",
            "First Appeal",
            "Respondent",
        ),
    )
    if labelled != NOT_FOUND:
        return labelled

    return _extract_sentence_with_terms(
        text,
        (
            "CPIO reply",
            "PIO reply",
            "FAA order",
            "denied",
            "rejected",
            "8(1)",
            "not provided",
            "no reply",
        ),
    )


def _extract_cic_observations(text: str) -> str:
    labelled = _extract_after_labels(
        text,
        (
            "CIC observations",
            "Commission observations",
            "Commission observed",
            "Observations",
        ),
    )
    if labelled != NOT_FOUND:
        return labelled

    return _extract_sentence_with_terms(
        text,
        (
            "Commission observed",
            "Commission noted",
            "Commission found",
            "Commission is of the view",
            "the Commission",
        ),
    )


def _extract_final_decision(text: str) -> str:
    labelled = _extract_after_labels(
        text,
        (
            "Final decision",
            "Decision",
            "Order",
            "Direction",
            "Final order",
        ),
    )
    if labelled != NOT_FOUND:
        return labelled

    return _extract_sentence_with_terms(
        text,
        (
            "directed",
            "disposed of",
            "appeal is disposed",
            "complaint is disposed",
            "furnish",
            "provide information",
            "no further intervention",
        ),
    )


def _use_in_present_case(
    *,
    text: str,
    issue_summary: dict[str, list[str]],
    final_decision: str,
    observations: str,
) -> str:
    combined = " ".join(
        [
            text,
            " ".join(issue_summary.get("legal_issues", [])),
            " ".join(issue_summary.get("response_paths", [])),
        ]
    ).casefold()

    if any(term in combined for term in ("8(1)", "exemption", "denied", "rejected")):
        return (
            "Useful if records exist and the proposed denial relies on broad or "
            "unverified exemption grounds; the PIO should verify records and give "
            "section-specific reasons."
        )

    if any(term in combined for term in ("pointwise", "point-wise", "proper reply")):
        return (
            "Useful where the present application requires a clear, point-wise "
            "reply based on available records."
        )

    if any(term in combined for term in ("furnish", "provide information", "directed")):
        return (
            "Useful where the record is available and no specific RTI Act exemption "
            "is established after verification."
        )

    if final_decision == NOT_FOUND and observations == NOT_FOUND:
        return NOT_FOUND

    return (
        "Useful only to the extent the present RTI has similar verified facts, "
        "record availability, and applicable RTI Act provisions."
    )


def _case_verification_card(
    result: dict[str, Any],
    issue_summary: dict[str, list[str]],
) -> dict[str, str]:
    text = _case_text(result)
    observations = _extract_cic_observations(text)
    final_decision = _extract_final_decision(text)

    return {
        "information_sought": _extract_information_sought(text),
        "pio_faa_response": _extract_pio_faa_response(text),
        "cic_observations": observations,
        "final_decision": final_decision,
        "use_in_present_case": _use_in_present_case(
            text=text,
            issue_summary=issue_summary,
            final_decision=final_decision,
            observations=observations,
        ),
        "source_file": result.get("actual_pdf")
        or result.get("source")
        or result.get("document_id")
        or NOT_FOUND,
    }


def _decision_identity(point: Any) -> str:
    payload = dict(getattr(point, "payload", {}) or {})
    collection = _payload_value(payload, "_retrieval_collection") or "unknown"
    stable = _payload_value(
        payload,
        "decision_number",
        "case_number",
        "case_no",
        "appeal_number",
        "file_no",
        "reference_number",
        "decision_pdf",
        "actual_pdf",
        "parent_id",
        "source",
        "file",
    )
    return f"{collection}|{stable or getattr(point, 'id', '')}"


def _to_frontend_result(
    retrieval_result: dict[str, Any],
    rank: int,
    issue_summary: dict[str, list[str]],
) -> dict[str, Any]:
    point = retrieval_result["point"]
    payload = dict(getattr(point, "payload", {}) or {})
    raw_text = str(payload.get("text") or "")
    text = _compact(raw_text, 8000)
    source = _payload_value(payload, "source", "file", "actual_pdf", "decision_pdf")
    actual_pdf = _payload_value(payload, "actual_pdf", "decision_pdf", "case_file")
    document_id = _payload_value(
        payload,
        "decision_number",
        "case_number",
        "case_no",
        "appeal_number",
        "file_no",
        "parent_id",
        "source",
    ) or str(getattr(point, "id", ""))

    result = {
        "rank": rank,
        "score": float(retrieval_result.get("score", 0.0) or 0.0),
        "retrieval_collection": _payload_value(payload, "_retrieval_collection") or "precedent_qdrant",
        "source": source,
        "actual_pdf": actual_pdf,
        "document_id": document_id,
        "text": text,
        "excerpt": _compact(text, 460),
        "parent_id": _payload_value(payload, "parent_id"),
        "chunk_type": _payload_value(payload, "chunk_type", "section"),
        "case_number": _payload_value(payload, "decision_number", "case_number", "case_no", "appeal_number", "file_no"),
        "decision_date": _payload_value(payload, "decision_date", "date"),
        "title": _payload_value(payload, "title", "case_title", "subject"),
        "structured_md_available": False,
        "structured_json_available": False,
    }
    verification_input = dict(result)
    verification_input["text"] = raw_text
    result["case_verification"] = _case_verification_card(
        verification_input,
        issue_summary,
    )
    return result


def _select_balanced_results(
    retrieved: list[dict[str, Any]],
    requested_limit: int,
) -> list[dict[str, Any]]:
    """Keep the strongest decisions while preventing one collection from dominating."""
    selected: list[dict[str, Any]] = []
    collection_counts: dict[str, int] = {}
    seen: set[str] = set()

    for item in sorted(retrieved, key=lambda value: float(value.get("score", 0.0) or 0.0), reverse=True):
        point = item.get("point")
        if point is None:
            continue

        payload = dict(getattr(point, "payload", {}) or {})
        collection = _payload_value(payload, "_retrieval_collection") or "unknown"
        identity = _decision_identity(point)

        if identity in seen:
            continue
        if collection_counts.get(collection, 0) >= MAX_RESULTS_PER_COLLECTION:
            continue

        seen.add(identity)
        collection_counts[collection] = collection_counts.get(collection, 0) + 1
        selected.append(item)

        if len(selected) >= requested_limit:
            break

    return selected


def _reference_context(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, result in enumerate(results, start=1):
        case_label = result.get("case_number") or "Not stated in indexed passage"
        date_label = result.get("decision_date") or "Not stated in indexed passage"
        title_label = result.get("title") or "Not stated in indexed passage"
        verification = result.get("case_verification") or {}
        parts.append(
            f"[REFERENCE {index}]\n"
            f"Collection: {result.get('retrieval_collection', '')}\n"
            f"Decision identifier: {case_label}\n"
            f"Decision date: {date_label}\n"
            f"Title/subject: {title_label}\n"
            f"Extracted information sought: {verification.get('information_sought', NOT_FOUND)}\n"
            f"Extracted PIO/FAA response: {verification.get('pio_faa_response', NOT_FOUND)}\n"
            f"Extracted CIC observations: {verification.get('cic_observations', NOT_FOUND)}\n"
            f"Extracted final decision: {verification.get('final_decision', NOT_FOUND)}\n"
            f"Extracted present-case use: {verification.get('use_in_present_case', NOT_FOUND)}\n"
            f"Source file: {verification.get('source_file') or result.get('actual_pdf') or NOT_FOUND}\n"
            f"Passage:\n{result.get('text', '')}"
        )
    return "\n\n".join(parts)


def _build_precedent_prompt(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    results: list[dict[str, Any]],
    answer_language: Any = None,
) -> str:
    language = _resolved_answer_language(answer_language, rti_extraction)
    is_hindi = language == "hi"
    issue_summary = _extract_issue_summary(rti_extraction, legal_analysis)
    if is_hindi:
        language_instruction = (
            "Write every visible heading, field label, explanation, and caution "
            "in natural professional Hindi using Devanagari script. Keep official "
            "case identifiers, file names, Act/section numbers, and quoted source "
            "terms unchanged."
        )
        title = "### CIC/CGSIC निर्णय सत्यापन कार्ड"
        labels = {
            "decision": "निर्णय",
            "information": "मांगी गई सूचना",
            "response": "PIO/FAA उत्तर",
            "observations": "CIC टिप्पणियां",
            "final": "अंतिम निर्णय",
            "use": "वर्तमान प्रकरण में उपयोग",
            "source": "स्रोत",
        }
        not_found = NOT_FOUND_HI
    else:
        language_instruction = (
            "Write every visible heading, field label, explanation, and caution "
            "in professional English. Keep official case identifiers, file names, "
            "Act/section numbers, and quoted source terms unchanged."
        )
        title = "### CIC/CGSIC Decision Verification Cards"
        labels = {
            "decision": "Decision",
            "information": "Information sought",
            "response": "PIO/FAA response",
            "observations": "CIC observations",
            "final": "Final decision",
            "use": "Use in present case",
            "source": "Source",
        }
        not_found = NOT_FOUND

    return f"""
You are preparing a concise PIO advisory addendum containing only relevant
CIC and CGSIC decision references.

Use only the REFERENCE MATERIAL below. Do not invent or complete a case title,
decision number, date, authority, section, holding, direction, or factual detail.
If an identifier is absent from the reference material, do not supply one.
Do not claim a decision is binding unless the reference material expressly says so.
Do not state or imply that a final decision has been made in the present RTI matter.
Do not mention chat history, previous PIO responses, prompts, retrieval, databases,
or that this content was generated from earlier material.

Write self-contained case verification cards.
{language_instruction}
Use this structure only:
{title}
1. **{labels['decision']}:** [only verified identifier/title, or collection label if none]
   **{labels['information']}:** [what the applicant sought in that CIC/CGSIC case; if absent write "{not_found}"]
   **{labels['response']}:** [PIO/FAA reply, denial ground, exemption, no-reply status, or "{not_found}"]
   **{labels['observations']}:** [what the Commission found/observed; if absent write "{not_found}"]
   **{labels['final']}:** [final direction/order/disposal in that case; if absent write "{not_found}"]
   **{labels['use']}:** [how this decision may assist the present PIO analysis, stated conditionally]
   **{labels['source']}:** [source file name]

Include only references that have a clear connection to the stated issues.
Keep the response to at most {len(results)} numbered entries and finish with one
short caution that these are precedent indicators only; final action must be
taken on verified records and the applicable RTI Act provisions.

CURRENT RTI ISSUE SUMMARY:
{json.dumps(issue_summary, ensure_ascii=False, indent=2)}

REQUIRED ANSWER LANGUAGE:
{"Hindi (Devanagari)" if is_hindi else "English"}

REFERENCE MATERIAL:
{_reference_context(results)}

FINAL RESPONSE:
""".strip()


def _generate_precedent_answer(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    results: list[dict[str, Any]],
    answer_language: Any = None,
) -> str:
    prompt = _build_precedent_prompt(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=results,
        answer_language=answer_language,
    )

    try:
        answer = generate_text(
            prompt=prompt,
            temperature=0.0,
            max_tokens=int(os.getenv("PIO_PRECEDENT_MAX_TOKENS", "3600")),
            timeout_seconds=int(os.getenv("PIO_PRECEDENT_LLM_TIMEOUT_SECONDS", "180")),
            reasoning_effort="low",
        )
    except LLMProviderError as error:
        raise PIOPrecedentError(f"Precedent reference generation failed: {error}") from error

    answer = str(answer or "").strip()
    if not answer:
        raise PIOPrecedentError("Precedent reference generation returned an empty answer.")
    if answer.startswith(("{", "[")):
        raise PIOPrecedentError("Precedent reference generation returned structured data instead of a readable answer.")
    return answer


def _stream_precedent_answer(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    results: list[dict[str, Any]],
    answer_language: Any = None,
) -> Iterator[str]:
    prompt = _build_precedent_prompt(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=results,
        answer_language=answer_language,
    )
    chunks: list[str] = []

    try:
        for chunk in stream_text(
            prompt=prompt,
            temperature=0.0,
            max_tokens=int(os.getenv("PIO_PRECEDENT_MAX_TOKENS", "3600")),
            timeout_seconds=int(os.getenv("PIO_PRECEDENT_LLM_TIMEOUT_SECONDS", "180")),
            reasoning_effort="low",
        ):
            chunks.append(chunk)
            yield chunk
    except LLMProviderError as error:
        raise PIOPrecedentError(f"Precedent reference generation failed: {error}") from error

    answer = str("".join(chunks) or "").strip()
    if not answer:
        raise PIOPrecedentError("Precedent reference generation returned an empty answer.")
    if answer.startswith(("{", "[")):
        raise PIOPrecedentError("Precedent reference generation returned structured data instead of a readable answer.")


def _build_precedent_informed_advisory_prompt(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    original_advisory: str,
    precedent_result: dict[str, Any],
    answer_language: Any = None,
) -> str:
    results = precedent_result.get("results") or []
    resolved_language = _resolved_answer_language(answer_language, rti_extraction)
    reference_language = _normalise_answer_language(
        precedent_result.get("answer_language")
    )
    reference_note = (
        _compact(precedent_result.get("answer"), 6000)
        if reference_language in {None, resolved_language}
        else ""
    )
    is_hindi = resolved_language == "hi"
    if is_hindi:
        language_instruction = (
            "Write the entire visible advisory in natural professional Hindi "
            "using Devanagari script. Keep official decision identifiers, file "
            "names, Act/section numbers, and quoted source terms unchanged."
        )
        citation_label = "संदर्भ"
        title = "## पूर्वनिर्णय-आधारित PIO सलाह"
        signal_examples = (
            "आयोग ने कहा है / आयोग ने स्पष्ट किया है / निर्णय के अनुसार / "
            "इस सिद्धांत के आधार पर"
        )
        correct_example = (
            "...धारा 8(1)(j) के अंतर्गत सामान्यतः संरक्षित होती है। "
            "*(संदर्भ: CIC/AB/A/2016/001101)*"
        )
        transition_example = "यदि ... तो ..."
        hedge_examples = "सामान्यतः, प्रथम दृष्टया, इस सीमा तक"
        conditional_examples = """- यदि अभिलेख उपलब्ध हैं...
- यदि तृतीय-पक्ष हित प्रभावित होते हैं...
- यदि सूचना व्यक्तिगत विवरण रखती है...
- यदि आवेदन पर्याप्त रूप से विशिष्ट नहीं है...
- यदि कोई वैधानिक अपवाद लागू नहीं होता...
- यदि सूचना का पृथक्करण संभव है..."""
    else:
        language_instruction = (
            "Write the entire visible advisory in professional English. Keep "
            "official decision identifiers, file names, Act/section numbers, "
            "and quoted source terms unchanged."
        )
        citation_label = "Reference"
        title = "## Precedent-informed PIO Advisory"
        signal_examples = (
            "the Commission held / the Commission clarified / according to the "
            "decision / applying that principle"
        )
        correct_example = (
            "...is generally protected under Section 8(1)(j). "
            "*(Reference: CIC/AB/A/2016/001101)*"
        )
        transition_example = "if ... then ..."
        hedge_examples = "generally, prima facie, to this limited extent"
        conditional_examples = """- If the records are available...
- If third-party interests are affected...
- If the information contains personal details...
- If the application is not sufficiently specific...
- If no statutory exemption applies...
- If severance of exempt material is possible..."""

    citation_format = f"*({citation_label}: <decision number>)*"

    return f"""
You are drafting a revised, precedent-informed PIO advisory for the same RTI
application. Produce one integrated, practical, record-based advisory for the
PIO, written as continuous formal legal-advisory prose -- not a
case-note, research summary, checklist, or reference list.

{language_instruction}

CRITICAL, NON-NEGOTIABLE RULE -- READ FIRST:
Any time you state a legal principle, test, or holding that comes from one of
the RETRIEVED CIC/CGSIC DECISION PASSAGES below -- whether you quote it,
paraphrase it, or simply rely on its substance -- you must place its citation,
in the exact format {citation_format}, immediately after that
sentence, before moving on to the next point. Do this in real time as you
write each sentence, not as something to add afterward. A sentence that
relies on a decision's reasoning and has no citation attached at that exact
point is a defect in your output, even if the format elsewhere is otherwise
correct.

Watch for these signals that you are drawing on a decision -- if a sentence
contains reasoning like this, the citation must follow immediately:
{signal_examples}

Correct pattern:
  {correct_example}
Incorrect -- do not do this:
  State the precedent-based proposition but place its citation later, at the
  end of another paragraph, or omit it entirely.

AUTHORITY PRIORITY (highest to lowest):
1. Verified RTI facts and verified record-status limitations.
2. RTI Act legal analysis.
3. Retrieved CIC/CGSIC decision passages and verified holdings.
4. Original advisory wording -- style/background aid only, lowest priority.

MANDATORY SAFEGUARDS:
- Do not write "based on the previous advisory" or similar wording.
- Do not state that any record exists unless the supplied context verifies it.
- Do not state a final disclosure or rejection decision as certain.
- Keep every conclusion conditional, fact-specific, and record-based.
- Use only the supplied RTI facts, legal analysis, and decision evidence.
- Do not invent decision numbers, parties, dates, holdings, sections, facts,
  procedural requirements, or public-interest findings.
- Do not merely list decisions or create a separate "References", "Case Law",
  "CIC/SIC Decisions", or bibliography section at the end.
- Do not mention prompts, retrieval, databases, embeddings, chat history,
  cached context, or source ranking.
- Do not render the advisory as a bulleted checklist. Write it as connected
  paragraphs in the same flowing conditional-legal-drafting style as a formal
  PIO order -- one paragraph per legal issue, issues linked with conditional
  transitions ({transition_example}).
- When a conclusion is drawn from precedent, phrase it narrowly and with an
  appropriate hedge ({hedge_examples}) rather than as an
  absolute, unqualified rule -- the precedent supports a specific proposition,
  not a blanket outcome.

OPENING PARAGRAPH:
- If the RTI extraction contains identifiable case facts (applicant name,
  application number, subject-matter or scheme, nature of information
  sought), open with one concise factual-synthesis paragraph stating them and
  giving a preliminary classification of the request under Section
  2(f)/"information".
- If such facts are not identifiable from the supplied extraction, begin
  directly with the conditional legal analysis -- do not fabricate case
  facts to manufacture an opening paragraph.

RECOMMENDED ANALYTICAL SEQUENCE (adapt to the facts; skip any step the facts
do not raise -- do not force a step that isn't relevant):
1. Record verification -- whether the department holds the records and whether
   they are already available through proactive disclosure under Section 4(1)(b).
2. Characterisation -- whether the requested material is third-party, personal,
   or commercial information.
3. Exemption analysis -- which Section 8 exemption may actually apply, its
   fact-specific test, and the Section 8(2) public-interest test where relevant.
4. Third-party procedure -- where third-party interests are affected, address
   the Section 11 notice and representation procedure without treating it as a veto.
5. Severability -- consider disclosing non-exempt portions under Section 10.
6. Procedure/timeline -- address Section 7(1), or Section 6(3) transfer to the
   competent public authority where relevant.
7. Closing direction -- give one integrated, reasoned, record-based direction
   without adding a separate citation list.

INLINE CITATION RULE -- mandatory (full specification):
- Whenever a conclusion, legal principle, or procedural direction is drawn
  from a CIC/CGSIC decision, place its citation immediately after that exact
  sentence or paragraph, in italics, using this format exactly:
  {citation_format}
- Cite only a decision number that appears in the supplied decision passages
  below -- copy it exactly as written there, character for character.
- Do not attach a citation to a statement unless the supplied passage
  supports it.
- Do not combine unrelated decisions in one citation.
- If a decision supports only a limited proposition, state that proposition
  narrowly; do not overstate the holding.
- Do not repeat the same decision citation unless it supports a separate,
  distinct conclusion elsewhere in the advisory.
- Do not place all citations together in the final paragraph, and do not
  collect them at the end of a section -- each one sits right next to the
  sentence it supports.
- RTI Act sections may be cited in the normal legal text, but decision
  citations must remain inline with the corresponding conclusion, never
  grouped at the end.
- If you find yourself with zero citations in a draft that discusses
  RETRIEVED CIC/CGSIC DECISION PASSAGES content, that is a sign you have
  summarised the passages without attributing them -- go back and attach the
  citations before finalising.

FORMATTING:
- Bold the first mention of each RTI Act section reference in a paragraph
  (e.g., **Section 8(1)(j)**) and each decision number the first time it appears
  (e.g., **CIC/AB/A/2016/001101**).
- No headings inside the body other than the required opening title below.
- No separate "References" / "Case Law" section.

The advisory must directly address, where applicable:
- which facts and records must be verified;
- what information may be disclosed;
- what information may be withheld and on which statutory basis;
- whether the information is third-party, personal, or commercial;
- Sections 8, 10, 11, 6(3), 7(1), or any other applicable provision;
- whether the application is sufficiently specific;
- whether this department or another public authority holds the information;
- whether public interest and partial disclosure must be assessed.

Where the record status is unverified, clearly state that verification is
required before taking a decision.
Where an exemption may apply, require a reasoned, section-specific
assessment; do not recommend blanket denial.
Where severability may apply, address disclosure of non-exempt portions
under Section 10.
Where third-party information may be involved, address Section 11 only if
the supplied legal analysis or decision passages support its applicability.
Integrate applicable CIC/CGSIC principles directly into the relevant legal
analysis -- never as a standalone summary of "what the cases say" -- and
remember every such integration needs its inline citation at that point.
End with a concise, single record-based action direction, without adding a
separate citation list.

Use conditional language such as:
{conditional_examples}

Start exactly with:
{title}

CURRENT RTI EXTRACTION:
{json.dumps(rti_extraction, ensure_ascii=False, indent=2)}

ORIGINAL PIO LEGAL ANALYSIS:
{json.dumps(legal_analysis, ensure_ascii=False, indent=2)}

RETRIEVED CIC/CGSIC REFERENCE NOTE:
{reference_note}

RETRIEVED CIC/CGSIC DECISION PASSAGES:
{_reference_context(results)}

ORIGINAL ADVISORY WORDING, LOWEST PRIORITY:
{_compact(original_advisory, 5000)}

FINAL CHECK BEFORE YOU WRITE YOUR ANSWER:
You are about to write the advisory below. As you write each paragraph that
uses a principle, test, or holding from the RETRIEVED CIC/CGSIC DECISION
PASSAGES above, attach {citation_format} immediately after that
sentence, using only decision numbers that actually appear in those passages.
Do not produce a paragraph that relies on a decision's reasoning without its
citation sitting right next to it.

FINAL REVISED ADVISORY:
""".strip()
    

#     return f"""
# You are drafting a revised, precedent-informed PIO advisory for the same RTI
# application. Produce one integrated, practical, record-based advisory for the
# PIO, written as continuous formal legal-advisory prose -- not a
# case-note, research summary, checklist, or reference list.

# AUTHORITY PRIORITY (highest to lowest):
# 1. Verified RTI facts and verified record-status limitations.
# 2. RTI Act legal analysis.
# 3. Retrieved CIC/CGSIC decision passages and verified holdings.
# 4. Original advisory wording -- style/background aid only, lowest priority.

# MANDATORY SAFEGUARDS:
# - Do not write "based on the previous advisory" or similar wording.
# - Do not state that any record exists unless the supplied context verifies it.
# - Do not state a final disclosure or rejection decision as certain.
# - Keep every conclusion conditional, fact-specific, and record-based.
# - Use only the supplied RTI facts, legal analysis, and decision evidence.
# - Do not invent decision numbers, parties, dates, holdings, sections, facts,
#   procedural requirements, or public-interest findings.
# - Do not merely list decisions or create a separate "References", "Case Law",
#   "CIC/SIC Decisions", or bibliography section at the end.
# - Do not mention prompts, retrieval, databases, embeddings, chat history,
#   cached context, or source ranking.
# - Do not render the advisory as a bulleted checklist. Write it as connected
#   paragraphs in the same flowing conditional-legal-drafting style as a formal
#   PIO order -- one paragraph per legal issue, issues linked with conditional
#   transitions (यदि ... तो ...).
# - When a conclusion is drawn from precedent, phrase it narrowly and with an
#   appropriate hedge (सामान्यतः, प्रथम दृष्टया, इस सीमा तक) rather than as an
#   absolute, unqualified rule -- the precedent supports a specific proposition,
#   not a blanket outcome.

# OPENING PARAGRAPH:
# - If the RTI extraction contains identifiable case facts (applicant name,
#   application number, subject-matter or scheme, nature of information
#   sought), open with one concise factual-synthesis paragraph stating them and
#   giving a preliminary classification of the request under Section
#   2(f)/"सूचना".
# - If such facts are not identifiable from the supplied extraction, begin
#   directly with the conditional legal analysis -- do not fabricate case
#   facts to manufacture an opening paragraph.

# RECOMMENDED ANALYTICAL SEQUENCE (adapt to the facts; skip any step the facts
# do not raise -- do not force a step that isn't relevant):
# 1. Record verification -- क्या अभिलेख विभाग के पास उपलब्ध है, तथा क्या यह पहले से
#    धारा 4(1)(ख) के अंतर्गत स्वप्रेरणा प्रकटीकरण के रूप में उपलब्ध है।
# 2. Characterisation -- क्या मांगी गई सूचना तृतीय-पक्ष, व्यक्तिगत, अथवा वाणिज्यिक
#    प्रकृति की है।
# 3. Exemption analysis -- कौन-सा धारा 8 अपवाद वास्तव में प्रयोज्य हो सकता है,
#    प्रत्येक अपवाद का तथ्य-विशिष्ट परीक्षण, तथा प्रयोज्य होने पर व्यापक लोकहित की
#    जांच (धारा 8(2))।
# 4. Third-party procedure -- यदि तृतीय-पक्ष हित प्रभावित होते हैं, तो धारा 11 की
#    अनिवार्य नोटिस एवं अभ्यावेदन प्रक्रिया, तथा यह कि तृतीय-पक्ष को निषेधाधिकार
#    नहीं बल्कि सुनवाई का अधिकार प्राप्त है।
# 5. Severability -- धारा 10 के अंतर्गत अपवादयुक्त अंश पृथक कर शेष सूचना उपलब्ध
#    कराने की संभावना।
# 6. Procedure/timeline -- धारा 7(1) की समय-सीमा, अथवा धारा 6(3) के अंतर्गत सक्षम
#    प्राधिकरण को स्थानांतरण, यदि प्रासंगिक हो।
# 7. Closing direction -- एक समेकित अनुच्छेद जिसमें अभिलेखों के सत्यापन, तृतीय-पक्ष
#    की प्रकृति, तथा प्रासंगिक धाराओं एवं उपर्युक्त सिद्धांतों के अनुरूप कारणयुक्त
#    आदेश पारित करने का निर्देश दिया जाए -- बिना अलग से उद्धरण-सूची जोड़े।

# INLINE CITATION RULE -- mandatory:
# - Whenever a conclusion, legal principle, or procedural direction is drawn
#   from a CIC/CGSIC decision, place its citation immediately after that exact
#   sentence or paragraph, in italics, using this format exactly:
#   *(संदर्भ: <decision number>)*
# - Cite only a decision number that appears in the supplied decision passages.
# - Do not attach a citation to a statement unless the supplied passage
#   supports it.
# - Do not combine unrelated decisions in one citation.
# - If a decision supports only a limited proposition, state that proposition
#   narrowly; do not overstate the holding.
# - Do not repeat the same decision citation unless it supports a separate,
#   distinct conclusion elsewhere in the advisory.
# - Do not place all citations together in the final paragraph.
# - RTI Act sections may be cited in the normal legal text, but decision
#   citations must remain inline with the corresponding conclusion, never
#   grouped at the end.

# FORMATTING:
# - Bold the first mention of each RTI Act section reference in a paragraph
#   (e.g., **धारा 8(1)(j)**) and each decision number the first time it appears
#   (e.g., **CIC/AB/A/2016/001101**).
# - No headings inside the body other than the required opening title below.
# - No separate "References" / "Case Law" section.

# The advisory must directly address, where applicable:
# - क्या तथ्य एवं अभिलेख सत्यापित करना है
# - क्या सूचना उपलब्ध कराई जा सकती है
# - क्या सूचना रोकी जा सकती है और किस वैधानिक आधार पर
# - क्या सूचना तृतीय-पक्ष / व्यक्तिगत / वाणिज्यिक प्रकृति की है
# - धारा 8, धारा 10, धारा 11, धारा 6(3), धारा 7(1), अथवा अन्य लागू प्रावधान
# - क्या आवेदन पर्याप्त रूप से विशिष्ट है
# - क्या सूचना विभाग के पास उपलब्ध है या किसी अन्य लोक प्राधिकरण के पास है
# - क्या व्यापक लोकहित और आंशिक प्रकटीकरण का परीक्षण आवश्यक है

# Where the record status is unverified, clearly state that verification is
# required before taking a decision.
# Where an exemption may apply, require a reasoned, section-specific
# assessment; do not recommend blanket denial.
# Where severability may apply, address disclosure of non-exempt portions
# under Section 10.
# Where third-party information may be involved, address Section 11 only if
# the supplied legal analysis or decision passages support its applicability.
# Integrate applicable CIC/CGSIC principles directly into the relevant legal
# analysis -- never as a standalone summary of "what the cases say".
# End with a concise, single record-based action direction, without adding a
# separate citation list.

# Use conditional language such as:
# - यदि अभिलेख उपलब्ध हैं...
# - यदि तृतीय-पक्ष हित प्रभावित होते हैं...
# - यदि सूचना व्यक्तिगत विवरण रखती है...
# - यदि आवेदन पर्याप्त रूप से विशिष्ट नहीं है...
# - यदि कोई वैधानिक अपवाद लागू नहीं होता...
# - यदि सूचना का पृथक्करण संभव है...

# {language_instruction}

# Start exactly with:
# ## Precedent-informed PIO Advisory

# CURRENT RTI EXTRACTION:
# {json.dumps(rti_extraction, ensure_ascii=False, indent=2)}

# ORIGINAL PIO LEGAL ANALYSIS:
# {json.dumps(legal_analysis, ensure_ascii=False, indent=2)}

# RETRIEVED CIC/CGSIC REFERENCE NOTE:
# {reference_note}

# RETRIEVED CIC/CGSIC DECISION PASSAGES:
# {_reference_context(results)}

# ORIGINAL ADVISORY WORDING, LOWEST PRIORITY:
# {_compact(original_advisory, 5000)}

# FINAL REVISED ADVISORY:
# """.strip()


#     return f"""
# You are drafting a revised, precedent-informed PIO advisory for the same RTI
# application. Produce one integrated, practical, record-based advisory for the
# PIO. This is not a case-note, research summary, or reference list.

# Use this authority priority:
# 1. Verified RTI facts and verified record-status limitations.
# 2. RTI Act legal analysis.
# 3. Retrieved CIC/CGSIC decision passages and verified holdings.
# 4. Original advisory wording only as a low-priority style/background aid.

# Mandatory safeguards:
# - Do not write “based on the previous advisory” or similar wording.
# - Do not state that any record exists unless the supplied context verifies it.
# - Do not state a final disclosure or rejection decision as certain.
# - Keep every conclusion conditional, fact-specific, and record-based.
# - Use only the supplied RTI facts, legal analysis, and decision evidence.
# - Do not invent decision numbers, parties, dates, holdings, sections, facts,
#   procedural requirements, or public-interest findings.
# - Do not merely list decisions or create a separate “References”, “Case Law”,
#   “CIC/SIC Decisions”, or bibliography section at the end.
# - Do not mention prompts, retrieval, databases, embeddings, chat history,
#   cached context, or source ranking.

# Inline citation rule — mandatory:
# - Whenever a conclusion, legal principle, or procedural direction is drawn from
#   a CIC/CGSIC decision, place its citation immediately after that exact sentence
#   or paragraph.
# - Use this format exactly:
#   (संदर्भ: <decision number>)
# - Cite only a decision number that appears in the supplied decision passages.
# - Do not attach a citation to a statement unless the supplied passage supports it.
# - Do not combine unrelated decisions in one citation.
# - If a decision supports only a limited proposition, state that proposition
#   narrowly; do not overstate the holding.
# - RTI Act sections may be cited in the normal legal text, but decision citations
#   must remain inline with the corresponding conclusion.

# The advisory must directly address, where applicable:
# - क्या तथ्य एवं अभिलेख सत्यापित करना है
# - क्या सूचना उपलब्ध कराई जा सकती है
# - क्या सूचना रोकी जा सकती है और किस वैधानिक आधार पर
# - क्या सूचना तृतीय-पक्ष / व्यक्तिगत / वाणिज्यिक प्रकृति की है
# - धारा 8, धारा 10, धारा 11, धारा 6(3), धारा 7(1), अथवा अन्य लागू प्रावधान
# - क्या आवेदन पर्याप्त रूप से विशिष्ट है
# - क्या सूचना विभाग के पास उपलब्ध है या किसी अन्य लोक प्राधिकरण के पास है
# - क्या व्यापक लोकहित और आंशिक प्रकटीकरण का परीक्षण आवश्यक है

# Drafting requirements:
# - Write in a formal PIO advisory style.
# - Integrate applicable CIC/CGSIC principles into the relevant legal analysis.
# - Do not place all citations together in the final paragraph.
# - Do not repeat the same decision citation unless it supports a separate,
#   distinct conclusion.
# - Where the record status is unverified, clearly state that verification is
#   required before taking a decision.
# - Where an exemption may apply, require a reasoned, section-specific assessment;
#   do not recommend blanket denial.
# - Where severability may apply, address disclosure of non-exempt portions under
#   Section 10.
# - Where third-party information may be involved, address Section 11 only if the
#   supplied legal analysis or decision passages support its applicability.
# - End with a concise record-based action direction, without adding a separate
#   citation list.

# Use conditional language such as:
# - यदि अभिलेख उपलब्ध हैं...
# - यदि तृतीय-पक्ष हित प्रभावित होते हैं...
# - यदि सूचना व्यक्तिगत विवरण रखती है...
# - यदि आवेदन पर्याप्त रूप से विशिष्ट नहीं है...
# - यदि कोई वैधानिक अपवाद लागू नहीं होता...
# - यदि सूचना का पृथक्करण संभव है...

# {language_instruction}

# Start exactly with:
# ## Precedent-informed PIO Advisory

# CURRENT RTI EXTRACTION:
# {json.dumps(rti_extraction, ensure_ascii=False, indent=2)}

# ORIGINAL PIO LEGAL ANALYSIS:
# {json.dumps(legal_analysis, ensure_ascii=False, indent=2)}

# RETRIEVED CIC/CGSIC REFERENCE NOTE:
# {reference_note}

# RETRIEVED CIC/CGSIC DECISION PASSAGES:
# {_reference_context(results)}

# ORIGINAL ADVISORY WORDING, LOWEST PRIORITY:
# {_compact(original_advisory, 5000)}

# FINAL REVISED ADVISORY:
# """.strip()

def stream_precedent_informed_advisory(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    original_advisory: str,
    precedent_result: dict[str, Any],
    answer_language: Any = None,
) -> Iterator[str]:
    """Stream a revised PIO advisory using cached CIC/CGSIC references."""
    if not isinstance(precedent_result, dict) or not precedent_result.get("results"):
        raise PIOPrecedentError("CIC/CGSIC references must be generated before the revised advisory.")

    prompt = _build_precedent_informed_advisory_prompt(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        original_advisory=original_advisory,
        precedent_result=precedent_result,
        answer_language=answer_language,
    )

    chunks: list[str] = []

    try:
        for chunk in stream_text(
            prompt=prompt,
            temperature=0.0,
            max_tokens=int(os.getenv("PIO_PRECEDENT_ADVISORY_MAX_TOKENS", "3200")),
            timeout_seconds=int(os.getenv("PIO_PRECEDENT_ADVISORY_TIMEOUT_SECONDS", "240")),
            reasoning_effort="low",
        ):
            chunks.append(chunk)
            yield chunk
    except LLMProviderError as error:
        raise PIOPrecedentError(f"Precedent-informed advisory generation failed: {error}") from error

    answer = str("".join(chunks) or "").strip()
    if not answer:
        raise PIOPrecedentError("Precedent-informed advisory generation returned an empty answer.")
    if answer.startswith(("{", "[")):
        raise PIOPrecedentError("Precedent-informed advisory generation returned structured data instead of a readable answer.")


def _retrieve_precedent_context(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    rag_module: Any,
    num_results: int = 5,
    answer_language: Any = None,
) -> dict[str, Any]:
    if not isinstance(rti_extraction, dict) or not isinstance(legal_analysis, dict):
        message = (
            "सहेजी गई PIO सलाह का संदर्भ अधूरा है।"
            if _normalise_answer_language(answer_language) == "hi"
            else "Saved PIO advisory context is incomplete."
        )
        raise PIOPrecedentError(message)

    language = _resolved_answer_language(answer_language, rti_extraction)
    is_hindi = language == "hi"

    requested_limit = max(1, min(int(num_results), 5))
    available_collections, missing_collections = _available_collections(rag_module)

    if not available_collections:
        raise PIOPrecedentError(
            "CIC और CGSIC पूर्वनिर्णय संग्रह अभी उपलब्ध नहीं हैं।"
            if is_hindi
            else "CIC and CGSIC precedent collections are currently unavailable."
        )

    search_query = build_precedent_query(rti_extraction, legal_analysis)
    if not search_query:
        raise PIOPrecedentError(
            "PIO सलाह से केंद्रित पूर्वनिर्णय खोज प्रश्न नहीं बनाया जा सका।"
            if is_hindi
            else "A focused precedent query could not be built from the PIO advisory."
        )
    issue_summary = _extract_issue_summary(rti_extraction, legal_analysis)

    candidate_limit = max(8, requested_limit * 2)
    retrieved = rag_module.retrieve_context(
        search_query,
        num_context=candidate_limit * len(available_collections),
        use_kg=False,
        collection_names=available_collections,
        per_collection_limit=candidate_limit,
    ) or []

    balanced = _select_balanced_results(retrieved, requested_limit)
    if not balanced:
        raise PIOPrecedentError(
            "इस सलाह के लिए पर्याप्त रूप से संबंधित CIC/CGSIC निर्णय संदर्भ नहीं मिले।"
            if is_hindi
            else "No sufficiently relevant CIC/CGSIC decision references were found for this advisory."
        )

    frontend_results = [
        _to_frontend_result(item, rank=index, issue_summary=issue_summary)
        for index, item in enumerate(balanced, start=1)
    ]

    warnings: list[str] = []
    if missing_collections:
        warnings.append(
            (
                "अनुपलब्ध पूर्वनिर्णय संग्रह: "
                if is_hindi
                else "Unavailable precedent collection(s): "
            )
            + ", ".join(missing_collections)
        )

    return {
        "results": frontend_results,
        "search_query": search_query,
        "available_collections": available_collections,
        "warnings": warnings,
    }


def retrieve_pio_precedent_references(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    rag_module: Any,
    num_results: int = 5,
    answer_language: Any = None,
) -> dict[str, Any]:
    """Retrieve and summarize only CIC + CGSIC precedent collections."""
    context = _retrieve_precedent_context(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        rag_module=rag_module,
        num_results=num_results,
        answer_language=answer_language,
    )
    frontend_results = context["results"]
    answer = _generate_precedent_answer(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=frontend_results,
        answer_language=answer_language,
    )

    return {
        "answer": answer,
        "results": frontend_results,
        "result_count": len(frontend_results),
        "search_query": context["search_query"],
        "available_collections": context["available_collections"],
        "warnings": context["warnings"],
        "answer_language": _resolved_answer_language(answer_language, rti_extraction),
    }


def retrieve_pio_precedent_references_stream(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    rag_module: Any,
    num_results: int = 5,
    answer_language: Any = None,
) -> Iterator[tuple[str, Any]]:
    """Retrieve CIC + CGSIC references, then stream the final addendum."""
    context = _retrieve_precedent_context(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        rag_module=rag_module,
        num_results=num_results,
        answer_language=answer_language,
    )
    frontend_results = context["results"]
    chunks: list[str] = []

    for chunk in _stream_precedent_answer(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=frontend_results,
        answer_language=answer_language,
    ):
        chunks.append(chunk)
        yield "token", chunk

    answer = str("".join(chunks) or "").strip()
    yield "result", {
        "answer": answer,
        "results": frontend_results,
        "result_count": len(frontend_results),
        "search_query": context["search_query"],
        "available_collections": context["available_collections"],
        "warnings": context["warnings"],
        "answer_language": _resolved_answer_language(answer_language, rti_extraction),
    }
