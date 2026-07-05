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


class PIOPrecedentError(RuntimeError):
    """Raised when supporting precedent retrieval cannot be completed safely."""


def _compact(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].strip()


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


def _to_frontend_result(retrieval_result: dict[str, Any], rank: int) -> dict[str, Any]:
    point = retrieval_result["point"]
    payload = dict(getattr(point, "payload", {}) or {})
    text = _compact(payload.get("text"), 6000)
    source = _payload_value(payload, "source", "file", "actual_pdf", "decision_pdf")
    actual_pdf = _payload_value(payload, "actual_pdf", "decision_pdf")
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

    return {
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
        parts.append(
            f"[REFERENCE {index}]\n"
            f"Collection: {result.get('retrieval_collection', '')}\n"
            f"Decision identifier: {case_label}\n"
            f"Decision date: {date_label}\n"
            f"Title/subject: {title_label}\n"
            f"Passage:\n{result.get('text', '')}"
        )
    return "\n\n".join(parts)


def _build_precedent_prompt(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    results: list[dict[str, Any]],
) -> str:
    language = _compact(rti_extraction.get("language"), 40).casefold()
    is_hindi = (
        language in {"hi", "hindi", "हिंदी", "हिन्दी"}
        or "hindi" in language
        or "हिंदी" in language
        or "हिन्दी" in language
    )
    issue_summary = _extract_issue_summary(rti_extraction, legal_analysis)

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

Write a self-contained supporting-reference note. Use natural professional Hindi
when the current RTI language is Hindi; otherwise write professional English.
Use this structure only:
### Relevant CIC/CGSIC Decision References
1. **Decision:** [only verified identifier/title, or collection label if none]
   **Principle:** [what the passage establishes]
   **Relevance:** [how it may assist PIO consideration of the present issues]

Include only references that have a clear connection to the stated issues.
Keep the response to at most {len(results)} numbered entries and finish with one
short caution that the final action must be taken on verified records and the
applicable RTI Act provisions.

CURRENT RTI ISSUE SUMMARY:
{json.dumps(issue_summary, ensure_ascii=False, indent=2)}

CURRENT RTI LANGUAGE:
{"Hindi" if is_hindi else "English"}

REFERENCE MATERIAL:
{_reference_context(results)}

FINAL RESPONSE:
""".strip()


def _generate_precedent_answer(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    results: list[dict[str, Any]],
) -> str:
    prompt = _build_precedent_prompt(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=results,
    )

    try:
        answer = generate_text(
            prompt=prompt,
            temperature=0.0,
            max_tokens=int(os.getenv("PIO_PRECEDENT_MAX_TOKENS", "2200")),
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
) -> Iterator[str]:
    prompt = _build_precedent_prompt(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=results,
    )
    chunks: list[str] = []

    try:
        for chunk in stream_text(
            prompt=prompt,
            temperature=0.0,
            max_tokens=int(os.getenv("PIO_PRECEDENT_MAX_TOKENS", "2200")),
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


def _retrieve_precedent_context(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    rag_module: Any,
    num_results: int = 5,
) -> dict[str, Any]:
    if not isinstance(rti_extraction, dict) or not isinstance(legal_analysis, dict):
        raise PIOPrecedentError("Saved PIO advisory context is incomplete.")

    requested_limit = max(1, min(int(num_results), 5))
    available_collections, missing_collections = _available_collections(rag_module)

    if not available_collections:
        raise PIOPrecedentError(
            "CIC and CGSIC precedent collections are currently unavailable."
        )

    search_query = build_precedent_query(rti_extraction, legal_analysis)
    if not search_query:
        raise PIOPrecedentError("A focused precedent query could not be built from the PIO advisory.")

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
            "No sufficiently relevant CIC/CGSIC decision references were found for this advisory."
        )

    frontend_results = [
        _to_frontend_result(item, rank=index)
        for index, item in enumerate(balanced, start=1)
    ]

    warnings: list[str] = []
    if missing_collections:
        warnings.append(
            "Unavailable precedent collection(s): " + ", ".join(missing_collections)
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
) -> dict[str, Any]:
    """Retrieve and summarize only CIC + CGSIC precedent collections."""
    context = _retrieve_precedent_context(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        rag_module=rag_module,
        num_results=num_results,
    )
    frontend_results = context["results"]
    answer = _generate_precedent_answer(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=frontend_results,
    )

    return {
        "answer": answer,
        "results": frontend_results,
        "result_count": len(frontend_results),
        "search_query": context["search_query"],
        "available_collections": context["available_collections"],
        "warnings": context["warnings"],
    }


def retrieve_pio_precedent_references_stream(
    *,
    rti_extraction: dict[str, Any],
    legal_analysis: dict[str, Any],
    rag_module: Any,
    num_results: int = 5,
) -> Iterator[tuple[str, Any]]:
    """Retrieve CIC + CGSIC references, then stream the final addendum."""
    context = _retrieve_precedent_context(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        rag_module=rag_module,
        num_results=num_results,
    )
    frontend_results = context["results"]
    chunks: list[str] = []

    for chunk in _stream_precedent_answer(
        rti_extraction=rti_extraction,
        legal_analysis=legal_analysis,
        results=frontend_results,
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
    }
