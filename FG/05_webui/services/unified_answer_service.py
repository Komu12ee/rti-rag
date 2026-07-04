from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from services.hybrid_retriever import UnifiedRetrievalResult
from services.llm_provider import LLMProviderError, generate_text
from services.retrieval_plan import Route


@dataclass(frozen=True)
class UnifiedAnswer:
    answer: str
    used_llm: bool
    needs_clarification: bool
    sources: list[dict[str, Any]]


def _contains_hindi(text: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", text or ""))


def _safe_text(value: Any, fallback: str = "Not listed") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _safe_join(value: Any, fallback: str = "Not listed") -> str:
    if isinstance(value, list):
        joined = ", ".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )
        return joined or fallback
    return _safe_text(value, fallback)


def _build_sources(result: UnifiedRetrievalResult) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []

    for item in result.combined_evidence:
        metadata = item.get("metadata") or {}
        sources.append(
            {
                "source_type": item.get("source_type", "Unknown source"),
                "mode": item.get("mode", ""),
                "source": metadata.get("source", ""),
                "case_number": metadata.get("case_number", ""),
                "office_code": metadata.get("office_code", ""),
                "officer_name": metadata.get("officer_name", ""),
                "email": metadata.get("email", ""),
            }
        )

    return sources


def _general_rti_knowledge_answer(query: str) -> tuple[str, bool]:
    prompt = f"""
You are the Chhattisgarh RTI Assistant.

No relevant local source was retrieved for this question. Answer from general
RTI Act knowledge and clearly avoid claiming that the answer is based on a
local database.

Keep the answer practical, concise, and safe. If the user asks about obtaining
information under RTI, explain the lawful RTI route and avoid making factual
allegations about any person.

User question:
{query}
""".strip()

    try:
        answer = generate_text(
            prompt=prompt,
            temperature=0.1,
            max_tokens=900,
            timeout_seconds=120,
            json_mode=False,
            reasoning_effort="low",
        ).strip()
    except LLMProviderError:
        answer = ""

    if answer:
        return answer, True

    if _contains_hindi(query):
        return (
            "स्थानीय स्रोतों से संबंधित सामग्री नहीं मिली। सामान्य RTI जानकारी "
            "के अनुसार आप संबंधित लोक प्राधिकरण के PIO को धारा 6 के तहत "
            "लिखित/ऑनलाइन RTI आवेदन दे सकते हैं और उपलब्ध रिकॉर्ड या दस्तावेजों "
            "की प्रमाणित प्रतियां मांग सकते हैं।",
            False,
        )

    return (
        "No local source was retrieved. In general, you can file an RTI "
        "application with the PIO of the concerned public authority and ask "
        "for existing official records or certified copies.",
        False,
    )


def _ambiguous_officer_answer(
    evidence: list[dict[str, Any]],
    query: str,
) -> str:
    query_name = (
        evidence[0].get("metadata", {}).get("_name_query", "")
    )

    if _contains_hindi(query):
        lines = [
            f'"{query_name}" नाम से एक से अधिक अधिकारी मिलते हैं।',
            "",
            "सही अधिकारी चुनने के लिए जिला, विभाग, कार्यालय, office code या email दें।",
            "",
            "मिले हुए संभावित अधिकारी:",
        ]
    else:
        lines = [
            f'I found multiple officer records close to "{query_name}".',
            "",
            "Provide the district, department, office name, office code, or email.",
            "",
            "Possible matches:",
        ]

    for index, item in enumerate(evidence[:5], start=1):
        row = item.get("metadata") or {}
        lines.extend(
            [
                f"{index}. {_safe_text(row.get('officer_name'))}",
                f"   Role: {_safe_text(row.get('rti_role'))}",
                f"   Email: {_safe_text(row.get('email'))}",
                f"   District: {_safe_text(row.get('district_name') or row.get('district'))}",
            ]
        )

    return "\n".join(lines)


def _directory_evidence_answer(
    evidence: list[dict[str, Any]],
    query: str,
    source_label: str,
) -> str:
    """
    Render both PostgreSQL and PIO-Qdrant officer records deterministically.

    No LLM is used for names, emails, office codes or addresses. This avoids
    accidental changes to official contact information.
    """
    if not evidence:
        if _contains_hindi(query):
            return (
                "दिए गए विवरण के आधार पर सक्रिय CG RTI Officer Registry में "
                "कोई मिलान रिकॉर्ड नहीं मिला। कार्यालय/स्कूल का नाम, जिला, "
                "विभाग, office code या email देकर पुनः खोजें।"
            )
        return (
            "No active match was found in the CG RTI Officer Registry. "
            "Try adding an office or school name, district, department, "
            "office code, or email."
        )

    first_metadata = evidence[0].get("metadata") or {}
    if first_metadata.get("_lookup_ambiguous"):
        return _ambiguous_officer_answer(evidence=evidence, query=query)

    is_hindi = _contains_hindi(query)
    source_is_qdrant = any(
        item.get("mode") == "PIO_QDRANT"
        for item in evidence
    )

    if is_hindi:
        heading = (
            "CG RTI अधिकारी निर्देशिका परिणाम"
            if not source_is_qdrant
            else "CG RTI अधिकारी निर्देशिका संभावित मिलान"
        )
    else:
        heading = (
            "CG RTI Officer Registry result"
            if not source_is_qdrant
            else "CG RTI Officer Directory semantic match"
        )

    lines = [heading + ":", ""]

    for index, item in enumerate(evidence[:5], start=1):
        row = item.get("metadata") or {}
        office = row.get("office_name") or row.get("sample_office_names")
        department = row.get("department_name") or row.get("department_names")
        district = row.get("district_name") or row.get("district") or row.get("district_names")
        designation = row.get("designation") or row.get("designations")
        address = row.get("office_address")

        lines.extend(
            [
                f"{index}. Role: {_safe_text(row.get('rti_role'))}",
                f"   Officer: {_safe_text(row.get('officer_name'))}",
                f"   Email: {_safe_text(row.get('email'))}",
                f"   Designation: {_safe_join(designation)}",
                f"   Office: {_safe_join(office)}",
                f"   Office code: {_safe_text(row.get('office_code'))}",
                f"   Department: {_safe_join(department)}",
                f"   District: {_safe_join(district)}",
            ]
        )

        if address:
            lines.append(f"   Address: {_safe_text(address)}")

        if source_is_qdrant:
            lines.append(
                f"   Directory data updated: "
                f"{_safe_text(row.get('source_generated_at'))}"
            )

        if index < min(len(evidence), 5):
            lines.append("")

    return "\n".join(lines)


def _officer_answer(result: UnifiedRetrievalResult, query: str) -> str:
    """
    PostgreSQL always has priority; pio_directory_v1 is only used when PG
    supplied no rows.
    """
    if result.postgres_evidence:
        return _directory_evidence_answer(
            result.postgres_evidence,
            query=query,
            source_label="postgres",
        )

    return _directory_evidence_answer(
        result.pio_qdrant_evidence,
        query=query,
        source_label="pio_qdrant",
    )


def _no_legal_context_answer(query: str) -> str:
    if _contains_hindi(query):
        return "इस प्रश्न के लिए संबंधित कानूनी संदर्भ प्राप्त नहीं हुआ।"
    return "No related legal context was retrieved for this question."


def _qdrant_generation_inputs(
    query: str,
    result: UnifiedRetrievalResult,
) -> tuple[str, list[dict[str, Any]]]:
    qdrant_result = result.qdrant_result
    if qdrant_result is None:
        return "", []
    return (
        qdrant_result.lookup_query or query,
        qdrant_result.context_results or [],
    )


def _generate_legal_answer(
    query: str,
    result: UnifiedRetrievalResult,
    generate_answer_fn: Callable[[str, list[dict[str, Any]]], str] | None,
) -> tuple[str, bool]:
    legal_query, context_results = _qdrant_generation_inputs(query, result)

    if not context_results:
        return _no_legal_context_answer(query), False

    if generate_answer_fn is None:
        return (
            "Legal context was retrieved, but the existing RAG answer generator "
            "is unavailable.",
            False,
        )

    answer = str(generate_answer_fn(legal_query, context_results) or "").strip()
    if not answer:
        raise RuntimeError("Existing RAG generate_answer() returned an empty answer.")

    return answer, True


def _combine_hybrid_answer(
    officer_answer: str,
    legal_answer: str,
    query: str,
) -> str:
    if _contains_hindi(query):
        return (
            "अधिकारी जानकारी:\n"
            f"{officer_answer}\n\n"
            "RTI कानूनी जानकारी:\n"
            f"{legal_answer}"
        )

    return (
        "Officer information:\n"
        f"{officer_answer}\n\n"
        "RTI legal guidance:\n"
        f"{legal_answer}"
    )


def generate_unified_answer(
    query: str,
    result: UnifiedRetrievalResult,
    generate_answer_fn: Callable[[str, list[dict[str, Any]]], str] | None = None,
) -> UnifiedAnswer:
    """
    POSTGRES:
        PostgreSQL result, then pio_directory_v1 fallback when PG had no rows.

    QDRANT:
        Legal-document RAG only.

    HYBRID:
        Officer result (PG -> PIO Qdrant fallback) plus legal RAG.
    """
    route = result.resolution.final.route
    sources = _build_sources(result)

    if route == Route.UNCLEAR:
        if result.qdrant_evidence:
            try:
                answer, used_llm = _generate_legal_answer(
                    query=query,
                    result=result,
                    generate_answer_fn=generate_answer_fn,
                )
                if used_llm:
                    return UnifiedAnswer(
                        answer=answer,
                        used_llm=True,
                        needs_clarification=False,
                        sources=sources,
                    )
            except Exception as error:
                result.errors.append(
                    "UNCLEAR legal-Qdrant generation failed: "
                    f"{type(error).__name__}: {error}"
                )

        answer, used_llm = _general_rti_knowledge_answer(query)
        return UnifiedAnswer(
            answer=answer,
            used_llm=used_llm,
            needs_clarification=False,
            sources=[],
        )

    if route == Route.POSTGRES:
        return UnifiedAnswer(
            answer=_officer_answer(result, query),
            used_llm=False,
            needs_clarification=False,
            sources=sources,
        )

    try:
        if route == Route.QDRANT:
            answer, used_llm = _generate_legal_answer(
                query=query,
                result=result,
                generate_answer_fn=generate_answer_fn,
            )
            return UnifiedAnswer(
                answer=answer,
                used_llm=used_llm,
                needs_clarification=False,
                sources=sources,
            )

        if route == Route.HYBRID:
            officer_answer = _officer_answer(result, query)
            legal_answer, used_llm = _generate_legal_answer(
                query=query,
                result=result,
                generate_answer_fn=generate_answer_fn,
            )

            return UnifiedAnswer(
                answer=_combine_hybrid_answer(
                    officer_answer=officer_answer,
                    legal_answer=legal_answer,
                    query=query,
                ),
                used_llm=used_llm,
                needs_clarification=False,
                sources=sources,
            )

        return UnifiedAnswer(
            answer="No supported route was selected.",
            used_llm=False,
            needs_clarification=True,
            sources=sources,
        )

    except Exception as error:
        if _contains_hindi(query):
            fallback = (
                "कानूनी संदर्भ प्राप्त हुआ, लेकिन उत्तर बनाने में त्रुटि हुई: "
                f"{type(error).__name__}"
            )
        else:
            fallback = (
                "Legal context was retrieved, but the answer generator failed: "
                f"{type(error).__name__}"
            )

        return UnifiedAnswer(
            answer=fallback,
            used_llm=False,
            needs_clarification=False,
            sources=sources,
        )
