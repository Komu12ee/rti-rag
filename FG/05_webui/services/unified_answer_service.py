from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from services.hybrid_retriever import UnifiedRetrievalResult
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


def _build_sources(
    result: UnifiedRetrievalResult,
) -> list[dict[str, Any]]:
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


def _clarification_answer(query: str) -> str:
    if _contains_hindi(query):
        return (
            "कृपया अपना प्रश्न थोड़ा स्पष्ट करें।\n\n"
            "PIO/FAA जानकारी के लिए कार्यालय, स्कूल, विभाग, जिला, "
            "office code या अधिकारी का email लिखें।\n\n"
            "RTI कानूनी जानकारी के लिए धारा, appeal, time limit, "
            "exemption या प्रक्रिया से संबंधित स्पष्ट प्रश्न लिखें।"
        )

    return (
        "Please clarify your request.\n\n"
        "For PIO/FAA details, provide an office, school, department, "
        "district, office code, or officer email.\n\n"
        "For RTI legal guidance, ask a specific question about a section, "
        "appeal, time limit, exemption, or procedure."
    )


def _registry_only_answer(
    result: UnifiedRetrievalResult,
    query: str,
) -> str:
    evidence = result.postgres_evidence

    if not evidence:
        if _contains_hindi(query):
            return (
                "दिए गए विवरण के आधार पर सक्रिय CG RTI Officer Registry में "
                "कोई मिलान रिकॉर्ड नहीं मिला। कार्यालय/स्कूल का नाम, जिला, "
                "office code या email देकर पुनः खोजें।"
            )

        return (
            "No active match was found in the CG RTI Officer Registry. "
            "Try adding an office or school name, district, office code, or email."
        )

    mode = evidence[0].get("mode", "ASSIGNMENTS")

    if mode == "DIRECTORY":
        lines = ["CG RTI Officer Registry results:", ""]

        for index, item in enumerate(evidence, start=1):
            row = item.get("metadata") or {}

            lines.extend(
                [
                    f"{index}. {_safe_text(row.get('rti_role'))}: "
                    f"{_safe_text(row.get('officer_name'))}",
                    f"   Email: {_safe_text(row.get('email'))}",
                    f"   Department: {_safe_text(row.get('department_name'))}",
                    f"   District: {_safe_text(row.get('district_name'))}",
                ]
            )

        return "\n".join(lines)

    lines = ["CG RTI Officer Registry result:", ""]

    for index, item in enumerate(evidence, start=1):
        row = item.get("metadata") or {}

        lines.extend(
            [
                f"{index}. Role: {_safe_text(row.get('rti_role'))}",
                f"   Officer: {_safe_text(row.get('officer_name'))}",
                f"   Email: {_safe_text(row.get('email'))}",
                f"   Designation: {_safe_text(row.get('designation'))}",
                f"   Office: {_safe_text(row.get('office_name'))}",
                f"   Office code: {_safe_text(row.get('office_code'))}",
                f"   Department: {_safe_text(row.get('department_name'))}",
                f"   District: {_safe_text(row.get('district_name'))}",
            ]
        )

    return "\n".join(lines)


def _no_legal_context_answer(query: str) -> str:
    if _contains_hindi(query):
        return "इस प्रश्न के लिए Qdrant से कोई संबंधित कानूनी संदर्भ प्राप्त नहीं हुआ।"

    return "No related legal context was retrieved from Qdrant for this question."


def _qdrant_generation_inputs(
    query: str,
    result: UnifiedRetrievalResult,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Returns the exact legal sub-query and original raw Qdrant context results.

    These raw results are passed directly into the old rag_pipeline.generate_answer().
    """
    qdrant_result = result.qdrant_result

    if qdrant_result is None:
        return "", []

    legal_query = qdrant_result.lookup_query or query
    context_results = qdrant_result.context_results or []

    return legal_query, context_results


def _generate_legal_answer(
    query: str,
    result: UnifiedRetrievalResult,
    generate_answer_fn: Callable[[str, list[dict[str, Any]]], str] | None,
) -> tuple[str, bool]:
    """
    Reuse the original RAG answer-generation function.

    Flow:
    legal query → retrieve_context → db3 chunks → generate_answer()
    """
    legal_query, context_results = _qdrant_generation_inputs(query, result)

    if not context_results:
        return _no_legal_context_answer(query), False

    if generate_answer_fn is None:
        return (
            "Legal context was retrieved, but the existing RAG answer generator "
            "is unavailable.",
            False,
        )

    answer = str(
        generate_answer_fn(
            legal_query,
            context_results,
        )
        or ""
    ).strip()

    if not answer:
        raise RuntimeError("Existing RAG generate_answer() returned an empty answer.")

    return answer, True


def _combine_hybrid_answer(
    registry_answer: str,
    legal_answer: str,
    query: str,
) -> str:
    if _contains_hindi(query):
        return (
            "अधिकारी रजिस्ट्री जानकारी:\n"
            f"{registry_answer}\n\n"
            "RTI कानूनी जानकारी:\n"
            f"{legal_answer}"
        )

    return (
        "Officer Registry Information:\n"
        f"{registry_answer}\n\n"
        "RTI Legal Guidance:\n"
        f"{legal_answer}"
    )


def generate_unified_answer(
    query: str,
    result: UnifiedRetrievalResult,
    generate_answer_fn: Callable[[str, list[dict[str, Any]]], str] | None = None,
) -> UnifiedAnswer:
    """
    Final answer flow:

    POSTGRES:
        deterministic officer-registry answer.

    QDRANT:
        existing retrieve_context() results → old generate_answer().

    HYBRID:
        PostgreSQL officer answer + old generate_answer() for legal Qdrant part.
    """
    route = result.resolution.final.route
    sources = _build_sources(result)

    if route == Route.UNCLEAR:
        
        # Route-B fallback may have retrieved RTI-related Qdrant chunks.
        # Generate an answer only when usable context exists.
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
                    "UNCLEAR Qdrant fallback generation failed: "
                    f"{type(error).__name__}: {error}"
                )

        return UnifiedAnswer(
            answer=_clarification_answer(query),
            used_llm=False,
            needs_clarification=True,
            sources=[],
        )

    if route == Route.POSTGRES:
        return UnifiedAnswer(
            answer=_registry_only_answer(result, query),
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
            registry_answer = _registry_only_answer(result, query)

            legal_answer, used_llm = _generate_legal_answer(
                query=query,
                result=result,
                generate_answer_fn=generate_answer_fn,
            )

            return UnifiedAnswer(
                answer=_combine_hybrid_answer(
                    registry_answer=registry_answer,
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
                "Qdrant से संदर्भ सामग्री प्राप्त हुई, लेकिन पुराने RAG "
                f"answer generator में त्रुटि हुई: {type(error).__name__}"
            )
        else:
            fallback = (
                "Qdrant context was retrieved, but the existing RAG answer "
                f"generator failed: {type(error).__name__}"
            )

        return UnifiedAnswer(
            answer=fallback,
            used_llm=False,
            needs_clarification=False,
            sources=sources,
        )