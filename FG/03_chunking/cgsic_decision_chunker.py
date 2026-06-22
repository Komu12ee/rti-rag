#!/usr/bin/env python3
"""Production-oriented chunker for the CGSIC important-decisions corpus.

Input:
    Stage 2 structured.json files, one directory per split decision PDF.

Output:
    Per-decision legal_chunks.jsonl and chunk_quality_report.json files, plus
    aggregate JSONL and quality reports suitable for review before indexing.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
FG_ROOT = SCRIPT_DIR.parent
DEFAULT_INPUT = FG_ROOT / "01_preprocessing" / "cg-imp-dics-ocr-op"
DEFAULT_OUTPUT = SCRIPT_DIR / "cgsic_output"
DEFAULT_MANIFEST = (
    FG_ROOT
    / "cg-imp-decision"
    / "artifacts"
    / "decision_manifest.json"
)

SOURCE_COMPILATION = "Imp_Dicisions_CGSIC.pdf"
SOURCE_DOCUMENT_ID = "CGSIC_IMPORTANT_DECISIONS_2022"
CORPUS = "CGSIC_IMPORTANT_DECISIONS_2022"
COMMISSION = "CG_SIC"
JURISDICTION = "CHHATTISGARH"

RETRIEVAL_PRIORITY = {
    "LEGAL_REASONING": 100,
    "COMMISSION_FINDINGS": 98,
    "FINAL_DIRECTION": 95,
    "PENALTY_OR_SHOW_CAUSE": 92,
    "PRECEDENT_SUMMARY": 90,
    "CITED_PROVISION": 85,
    "INFORMATION_REQUESTED": 75,
    "CPIO_RESPONSE": 70,
    "FIRST_APPEAL_HISTORY": 65,
    "CASE_NARRATIVE": 55,
    "CASE_METADATA": 40,
}

LEGAL_CHUNK_TYPES = set(RETRIEVAL_PRIORITY)

APPEAL_PATTERN = re.compile(
    r"(?:द्वितीय\s+)?(?:अपील|शिकायत)\s*प्रकरण\s*क्रमांक\s*[:\-]?\s*"
    r"((?:[A-Z]|[\u0900-\u097f]{1,3})?\s*[/\-]?\s*"
    r"\d{1,6}\s*[/\-]\s*\d{2,4})",
    re.IGNORECASE,
)
BOUNDARY_APPEAL_PATTERN = re.compile(
    r"(?im)^\s*#*\s*(?:द्वितीय\s+)?(?:अपील|शिकायत)\s*"
    r"प्रकरण\s*क्रमांक\s*[:\-]?\s*"
    r"((?:[A-Z]|[\u0900-\u097f]{1,3})?\s*[/\-]?\s*"
    r"\d{1,6}\s*[/\-]\s*\d{2,4})"
)
ORDER_DATE_PATTERN = re.compile(
    r"(?:आदेश|निर्णय)\s*दिनांक\s*[:\-]?\s*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})"
)
RTI_SECTION_PATTERN = re.compile(
    r"धारा\s*[0-9०-९]+(?:\s*\([^)]+\))*",
    re.IGNORECASE,
)
SIGNATURE_PATTERN = re.compile(
    r"(?:सही\s*[-/]|हस्ताक्षर|राज्य\s+सूचना\s+आयुक्त|मुख्य\s+राज्य\s+सूचना\s+आयुक्त)",
    re.IGNORECASE,
)
FINAL_DIRECTION_PATTERN = re.compile(
    r"(?:निर्देशित\s+किया\s+जाता|आदेशित\s+किया\s+जाता|"
    r"प्रदान\s+करने\s+के\s+आदेश|अपील\s+निराकृत|प्रकरण\s+समाप्त|"
    r"अपील\s+समाप्त|आदेश\s+पारित|अभिलेखबद्ध\s+किया\s+जाता)",
    re.IGNORECASE,
)

MARKERS = {
    "PENALTY_OR_SHOW_CAUSE": (
        "कारण बताओ",
        "कारण दर्शाओ",
        "शास्ति",
        "जुर्माना",
        "धारा 20",
        "धारा २०",
    ),
    "FINAL_DIRECTION": (
        "निर्देशित किया जाता",
        "आदेशित किया जाता",
        "प्रदान करने के आदेश",
        "उपलब्ध कराने के आदेश",
        "अपील निराकृत",
        "प्रकरण समाप्त",
        "अपील समाप्त",
        "आदेश पारित",
    ),
    "COMMISSION_FINDINGS": (
        "आयोग ने यह पाया",
        "आयोग यह पाता",
        "आयोग का निष्कर्ष",
        "आयोग का अभिमत",
        "आयोग का मत",
        "आयोग द्वारा अवलोकन",
        "अतः आयोग",
    ),
    "FIRST_APPEAL_HISTORY": (
        "प्रथम अपील",
        "प्रथम अपीलीय",
        "अपीलीय अधिकारी",
    ),
    "CPIO_RESPONSE": (
        "जनसूचना अधिकारी के द्वारा",
        "जन सूचना अधिकारी के द्वारा",
        "लोक सूचना अधिकारी के द्वारा",
        "उत्तर दिया",
        "जवाब प्रस्तुत",
        "आवेदन अस्वीकार",
    ),
    "INFORMATION_REQUESTED": (
        "जानकारी चाही",
        "सूचना चाही",
        "सूचना मांगी",
        "मांगी गई जानकारी",
        "प्रमाणित प्रति चाही",
        "आवेदन पत्र दिया",
    ),
}

REASONING_SUBJECTS = (
    "आयोग",
    "राज्य सूचना आयोग",
)
REASONING_ACTIONS = (
    "पाया",
    "पाता है",
    "मत है",
    "अभिमत",
    "अवलोकन",
    "निष्कर्ष",
    "स्पष्ट है",
    "व्याख्या",
    "विचार",
)
REASONING_LEGAL_SIGNALS = (
    "धारा",
    "अधिनियम",
    "न्यायालय",
    "न्याय दृष्टांत",
    "निर्णय",
    "प्रावधान",
)


@dataclass
class DecisionMetadata:
    appeal_number: str = ""
    decision_date: str = ""
    appellant: str = ""
    public_authority: str = ""
    rti_sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "appeal_number": self.appeal_number,
            "case_number": self.appeal_number,
            "decision_date": self.decision_date,
            "appellant": self.appellant,
            "public_authority": self.public_authority,
            "rti_sections": self.rti_sections,
        }


def normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_value(value: str) -> str:
    value = re.sub(r"^#+\s*", "", normalize_text(value))
    value = re.sub(r"\s+", " ", value)
    return value.strip(" :|-")


def unique(values: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        key = clean_value(value).lower()
        if key and key not in seen:
            seen.add(key)
            output.append(clean_value(value))
    return output


def extract_between(
    text: str,
    starts: Iterable[str],
    ends: Iterable[str],
    limit: int = 500,
) -> str:
    start_match = None
    for marker in starts:
        start_match = re.search(re.escape(marker), text, re.IGNORECASE)
        if start_match:
            break
    if not start_match:
        return ""

    remainder = text[start_match.end() :]
    end_positions = []
    for marker in ends:
        match = re.search(re.escape(marker), remainder, re.IGNORECASE)
        if match:
            end_positions.append(match.start())
    value = remainder[: min(end_positions)] if end_positions else remainder[:limit]
    return clean_value(value)[:limit]


def extract_metadata(text: str) -> DecisionMetadata:
    head = text[:6000]
    appeal = APPEAL_PATTERN.search(head)
    order_date = ORDER_DATE_PATTERN.search(head)
    return DecisionMetadata(
        appeal_number=clean_value(appeal.group(1)) if appeal else "",
        decision_date=order_date.group(1) if order_date else "",
        appellant=extract_between(
            head,
            ("अपीलार्थी", "अपीलकर्ता"),
            ("विरुद्ध", "विरूद्ध", "बनाम"),
        ),
        public_authority=extract_between(
            head,
            ("विरुद्ध", "विरूद्ध", "बनाम"),
            ("आदेश दिनांक", "निर्णय दिनांक", "\nनिर्णय", "\nआदेश"),
        ),
        rti_sections=unique(match.group(0) for match in RTI_SECTION_PATTERN.finditer(text)),
    )


def validate_split_boundary(text: str, page_count: int) -> dict[str, Any]:
    appeal_numbers = unique(
        match.group(1) for match in BOUNDARY_APPEAL_PATTERN.finditer(text)
    )
    order_dates = unique(match.group(1) for match in ORDER_DATE_PATTERN.finditer(text))
    header_order_dates = unique(
        match.group(1)
        for match in ORDER_DATE_PATTERN.finditer(text[:1600])
    )
    signature_count = len(SIGNATURE_PATTERN.findall(text))
    final_direction_count = len(FINAL_DIRECTION_PATTERN.findall(text))

    reasons = []
    if len(appeal_numbers) != 1:
        reasons.append(f"expected 1 appeal number, found {len(appeal_numbers)}")
    if not header_order_dates:
        reasons.append("order date missing from decision header")
    if signature_count == 0:
        reasons.append("signature/commissioner marker missing")
    elif signature_count > 2:
        reasons.append(f"multiple signature markers found ({signature_count})")
    if final_direction_count == 0:
        reasons.append("final direction marker missing")
    if page_count <= 0:
        reasons.append("document has no pages")

    return {
        "split_quality": "suspect" if reasons else "good",
        "review_required": bool(reasons),
        "reasons": reasons,
        "signals": {
            "appeal_number_count": len(appeal_numbers),
            "appeal_numbers": appeal_numbers,
            "order_date_count": len(order_dates),
            "order_dates": order_dates,
            "header_order_date_count": len(header_order_dates),
            "header_order_dates": header_order_dates,
            "signature_count": signature_count,
            "final_direction_count": final_direction_count,
            "page_count": page_count,
        },
    }


def split_paragraphs(text: str) -> list[str]:
    blocks = [
        normalize_text(block)
        for block in re.split(r"\n\s*\n|(?=\n\s*\d+\s*[./)])", text)
        if normalize_text(block)
    ]
    if len(blocks) <= 1:
        blocks = [
            clean_value(block)
            for block in re.split(r"(?<=[।.!?])\s+", text)
            if clean_value(block)
        ]
    return blocks


def contains_any(text: str, markers: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def legal_reasoning_score(text: str) -> int:
    score = 0
    if contains_any(text, REASONING_SUBJECTS):
        score += 2
    if contains_any(text, REASONING_ACTIONS):
        score += 2
    if contains_any(text, REASONING_LEGAL_SIGNALS):
        score += 2
    if contains_any(text, ("अतः", "फलतः", "इसलिए", "जिससे स्पष्ट")):
        score += 1
    return score


def classify_paragraph(text: str) -> tuple[str, dict[str, int]]:
    scores = {chunk_type: 0 for chunk_type in LEGAL_CHUNK_TYPES}

    for chunk_type, markers in MARKERS.items():
        scores[chunk_type] = sum(
            marker.lower() in text.lower() for marker in markers
        )

    reasoning = legal_reasoning_score(text)
    scores["LEGAL_REASONING"] = reasoning
    scores["COMMISSION_FINDINGS"] += reasoning if contains_any(
        text, MARKERS["COMMISSION_FINDINGS"]
    ) else 0
    section_count = len(RTI_SECTION_PATTERN.findall(text))
    scores["CITED_PROVISION"] = section_count * 2

    precedence = (
        "PENALTY_OR_SHOW_CAUSE",
        "FINAL_DIRECTION",
        "COMMISSION_FINDINGS",
        "LEGAL_REASONING",
        "CITED_PROVISION",
        "INFORMATION_REQUESTED",
        "CPIO_RESPONSE",
        "FIRST_APPEAL_HISTORY",
    )
    thresholds = {
        "PENALTY_OR_SHOW_CAUSE": 1,
        "FINAL_DIRECTION": 1,
        "COMMISSION_FINDINGS": 4,
        "LEGAL_REASONING": 5,
        "CITED_PROVISION": 2,
        "INFORMATION_REQUESTED": 1,
        "CPIO_RESPONSE": 1,
        "FIRST_APPEAL_HISTORY": 1,
    }
    for chunk_type in precedence:
        if scores[chunk_type] >= thresholds[chunk_type]:
            return chunk_type, scores
    return "CASE_NARRATIVE", scores


def page_units(
    pages: list[dict[str, Any]],
    manifest_entry: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    units = []
    for fallback_index, page in enumerate(pages, 1):
        relative_page = int(page.get("page_num") or fallback_index)
        physical_page = None
        printed_page = None
        if manifest_entry:
            physical_page = (
                manifest_entry["physical_page_start"] + relative_page - 1
            )
            printed_page = (
                manifest_entry["printed_page_start"] + relative_page - 1
            )

        for paragraph in split_paragraphs(page.get("text", "")):
            chunk_type, scores = classify_paragraph(paragraph)
            units.append(
                {
                    "text": paragraph,
                    "chunk_type": chunk_type,
                    "classification_scores": scores,
                    "decision_page_numbers": [relative_page],
                    "physical_page_numbers": (
                        [physical_page] if physical_page is not None else []
                    ),
                    "printed_page_numbers": (
                        [printed_page] if printed_page is not None else []
                    ),
                    "ocr_confidences": (
                        [float(page["confidence"])]
                        if page.get("confidence") is not None
                        else []
                    ),
                }
            )
    return units


def merge_values(units: list[dict[str, Any]], field: str) -> list[Any]:
    return sorted({value for unit in units for value in unit.get(field, [])})


def pack_units(
    units: list[dict[str, Any]],
    target_words: int = 350,
    hard_max_words: int = 600,
) -> list[dict[str, Any]]:
    packed = []
    current: list[dict[str, Any]] = []
    current_type = ""

    def flush() -> None:
        nonlocal current, current_type
        if not current:
            return
        packed.append(
            {
                "text": "\n\n".join(unit["text"] for unit in current),
                "chunk_type": current_type,
                "decision_page_numbers": merge_values(
                    current, "decision_page_numbers"
                ),
                "physical_page_numbers": merge_values(
                    current, "physical_page_numbers"
                ),
                "printed_page_numbers": merge_values(
                    current, "printed_page_numbers"
                ),
                "ocr_confidences": [
                    value
                    for unit in current
                    for value in unit.get("ocr_confidences", [])
                ],
                "classification_scores": dict(
                    Counter(
                        {
                            key: sum(
                                unit["classification_scores"].get(key, 0)
                                for unit in current
                            )
                            for key in LEGAL_CHUNK_TYPES
                        }
                    )
                ),
            }
        )
        current = []
        current_type = ""

    for unit in units:
        words = unit["text"].split()
        if len(words) > hard_max_words:
            flush()
            for start in range(0, len(words), hard_max_words):
                part = dict(unit)
                part["text"] = " ".join(words[start : start + hard_max_words])
                current = [part]
                current_type = unit["chunk_type"]
                flush()
            continue

        current_words = sum(len(item["text"].split()) for item in current)
        type_changed = current and unit["chunk_type"] != current_type
        would_overflow = current and current_words + len(words) > target_words
        if type_changed or would_overflow:
            flush()
        if not current:
            current_type = unit["chunk_type"]
        current.append(unit)

    flush()
    return packed


def safe_page_fields(packed: dict[str, Any]) -> dict[str, Any]:
    decision_pages = packed.get("decision_page_numbers", [])
    physical_pages = packed.get("physical_page_numbers", [])
    printed_pages = packed.get("printed_page_numbers", [])
    fallback_pages = physical_pages or decision_pages
    page_number = min(printed_pages) if printed_pages else (
        min(fallback_pages) if fallback_pages else None
    )
    return {
        "page_number": page_number,
        "decision_page_numbers": decision_pages,
        "decision_page_start": min(decision_pages) if decision_pages else None,
        "decision_page_end": max(decision_pages) if decision_pages else None,
        "physical_page_numbers": physical_pages,
        "physical_page_start": min(physical_pages) if physical_pages else None,
        "physical_page_end": max(physical_pages) if physical_pages else None,
        "printed_page_numbers": printed_pages,
        "printed_page_start": min(printed_pages) if printed_pages else None,
        "printed_page_end": max(printed_pages) if printed_pages else None,
    }


def summarize(text: str, max_words: int) -> str:
    words = clean_value(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,.;") + "..."


def first_chunk_text(
    chunks: list[dict[str, Any]],
    chunk_types: Iterable[str],
    max_words: int,
) -> str:
    wanted = set(chunk_types)
    for chunk in chunks:
        if chunk["chunk_type"] in wanted and chunk.get("text"):
            return summarize(chunk["text"], max_words)
    return ""


def issue_text(chunks: list[dict[str, Any]]) -> str:
    information = first_chunk_text(chunks, ("INFORMATION_REQUESTED",), 70)
    if information:
        return information

    narrative = first_chunk_text(chunks, ("CASE_NARRATIVE",), 100)
    if not narrative:
        return ""
    decision_marker = re.search(r"\bनिर्णय\b", narrative)
    if decision_marker:
        narrative = narrative[decision_marker.end() :]
    return summarize(narrative, 70)


def build_precedent_card(
    metadata: DecisionMetadata,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    issue = issue_text(chunks)
    finding = first_chunk_text(
        chunks,
        ("COMMISSION_FINDINGS", "LEGAL_REASONING"),
        80,
    )
    outcome = first_chunk_text(chunks, ("FINAL_DIRECTION",), 55)
    penalty = first_chunk_text(chunks, ("PENALTY_OR_SHOW_CAUSE",), 40)

    if penalty:
        pio_learning = (
            "समय-सीमा, उत्तर के कारण और अभिलेख स्पष्ट रखें; अन्यथा धारा 20 "
            "की शास्ति या कारण बताओ कार्यवाही का जोखिम हो सकता है।"
        )
    elif outcome and contains_any(outcome, ("प्रदान", "उपलब्ध", "देने")):
        pio_learning = (
            "मांगी गई सूचना पर स्पष्ट, बिंदुवार निर्णय दें और प्रकटीकरण योग्य "
            "अभिलेख समय पर उपलब्ध कराएं।"
        )
    else:
        pio_learning = (
            "आवेदन, उत्तर, अपील और प्रेषण का प्रमाण सुरक्षित रखते हुए अधिनियम "
            "के प्रासंगिक प्रावधानों के आधार पर स्पष्ट निर्णय दें।"
        )

    return {
        "issue": issue,
        "section": metadata.rti_sections,
        "finding": finding,
        "outcome": outcome,
        "pio_learning": pio_learning,
    }


def render_precedent_card(card: dict[str, Any]) -> str:
    sections = ", ".join(card["section"]) or "उल्लेख उपलब्ध नहीं"
    return clean_value(
        f"विधिक प्रश्न: {card['issue']} "
        f"प्रासंगिक धारा: {sections}. "
        f"आयोग का निष्कर्ष: {card['finding']} "
        f"परिणाम: {card['outcome']} "
        f"PIO सीख: {card['pio_learning']}"
    )


def metadata_chunk_text(metadata: DecisionMetadata) -> str:
    fields = [
        f"अपील प्रकरण क्रमांक: {metadata.appeal_number}",
        f"आदेश दिनांक: {metadata.decision_date}",
        f"अपीलार्थी: {metadata.appellant}",
        f"लोक प्राधिकारी: {metadata.public_authority}",
        f"प्रासंगिक धाराएं: {', '.join(metadata.rti_sections)}",
    ]
    return "\n".join(field for field in fields if not field.endswith(": "))


class CGSICDecisionChunker:
    def __init__(
        self,
        manifest_path: Path = DEFAULT_MANIFEST,
        target_words: int = 350,
        hard_max_words: int = 600,
    ):
        self.target_words = target_words
        self.hard_max_words = hard_max_words
        self.manifest = self._load_manifest(manifest_path)

    @staticmethod
    def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            decision["decision_id"]: decision
            for decision in payload.get("decisions", [])
        }

    def chunk_structured(
        self,
        structured_path: Path,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        structured = json.loads(structured_path.read_text(encoding="utf-8"))
        decision_id = structured_path.parent.name
        manifest_entry = self.manifest.get(decision_id)
        pages = structured.get("pages", [])
        full_text = "\n\n".join(page.get("text", "") for page in pages)
        metadata = extract_metadata(full_text)
        split_validation = validate_split_boundary(full_text, len(pages))

        packed = pack_units(
            page_units(pages, manifest_entry),
            target_words=self.target_words,
            hard_max_words=self.hard_max_words,
        )
        source_pdf = Path(structured.get("source_pdf", "")).name
        actual_pdf = source_pdf or f"{decision_id}.pdf"
        sequence = (
            manifest_entry.get("sequence_in_contents")
            if manifest_entry
            else parse_sequence(decision_id)
        )

        base_payload = {
            "source": SOURCE_COMPILATION,
            "actual_pdf": actual_pdf,
            "decision_pdf": actual_pdf,
            "source_document_id": SOURCE_DOCUMENT_ID,
            "source_type": "CGSIC_IMPORTANT_DECISION",
            "corpus": CORPUS,
            "commission": COMMISSION,
            "jurisdiction": JURISDICTION,
            "decision_id": decision_id,
            "sequence_in_compilation": sequence,
            **metadata.to_dict(),
            "split_quality": split_validation["split_quality"],
            "split_review_required": split_validation["review_required"],
            "language": "hi",
        }

        chunks = []
        metadata_pages = packed[0] if packed else {
            "decision_page_numbers": [],
            "physical_page_numbers": [],
            "printed_page_numbers": [],
        }
        chunks.append(
            {
                "chunk_id": f"{decision_id}_CASE_METADATA_001",
                "text": metadata_chunk_text(metadata),
                **base_payload,
                "chunk_type": "CASE_METADATA",
                **safe_page_fields(metadata_pages),
                "retrieval_priority": RETRIEVAL_PRIORITY["CASE_METADATA"],
                "classification_scores": {},
                "ocr_confidence_min": minimum_confidence(metadata_pages),
                "is_derived": False,
            }
        )

        for index, item in enumerate(packed, 2):
            chunk_type = item["chunk_type"]
            chunks.append(
                {
                    "chunk_id": f"{decision_id}_{chunk_type}_{index:03d}",
                    "text": clean_value(item["text"]),
                    **base_payload,
                    "chunk_type": chunk_type,
                    **safe_page_fields(item),
                    "retrieval_priority": RETRIEVAL_PRIORITY[chunk_type],
                    "classification_scores": item["classification_scores"],
                    "ocr_confidence_min": minimum_confidence(item),
                    "is_derived": False,
                }
            )

        card = build_precedent_card(metadata, chunks)
        all_pages = {
            "decision_page_numbers": sorted(
                {
                    page
                    for chunk in chunks
                    for page in chunk["decision_page_numbers"]
                }
            ),
            "physical_page_numbers": sorted(
                {
                    page
                    for chunk in chunks
                    for page in chunk["physical_page_numbers"]
                }
            ),
            "printed_page_numbers": sorted(
                {
                    page
                    for chunk in chunks
                    for page in chunk["printed_page_numbers"]
                }
            ),
        }
        chunks.append(
            {
                "chunk_id": f"{decision_id}_PRECEDENT_SUMMARY_999",
                "text": render_precedent_card(card),
                **base_payload,
                "chunk_type": "PRECEDENT_SUMMARY",
                **safe_page_fields(all_pages),
                "retrieval_priority": RETRIEVAL_PRIORITY["PRECEDENT_SUMMARY"],
                "classification_scores": {},
                "ocr_confidence_min": minimum_page_confidence(pages),
                "is_derived": True,
                "precedent_card": card,
            }
        )

        report = build_quality_report(
            decision_id,
            structured_path,
            structured,
            metadata,
            split_validation,
            chunks,
            self.hard_max_words,
        )
        return chunks, report


def minimum_confidence(item: dict[str, Any]) -> float | None:
    values = item.get("ocr_confidences", [])
    return round(min(values), 4) if values else None


def minimum_page_confidence(pages: list[dict[str, Any]]) -> float | None:
    values = [
        float(page["confidence"])
        for page in pages
        if page.get("confidence") is not None
    ]
    return round(min(values), 4) if values else None


def parse_sequence(decision_id: str) -> int | None:
    match = re.search(r"(\d+)$", decision_id)
    return int(match.group(1)) if match else None


def build_quality_report(
    decision_id: str,
    structured_path: Path,
    structured: dict[str, Any],
    metadata: DecisionMetadata,
    split_validation: dict[str, Any],
    chunks: list[dict[str, Any]],
    hard_max_words: int,
) -> dict[str, Any]:
    pages = structured.get("pages", [])
    substantive = [
        chunk for chunk in chunks if chunk["chunk_type"] != "PRECEDENT_SUMMARY"
    ]
    words = [len(chunk["text"].split()) for chunk in substantive]
    empty_pages = [
        int(page.get("page_num") or index)
        for index, page in enumerate(pages, 1)
        if not clean_value(page.get("text", ""))
    ]
    low_confidence_pages = [
        {
            "page_num": int(page.get("page_num") or index),
            "confidence": page.get("confidence"),
        }
        for index, page in enumerate(pages, 1)
        if page.get("confidence") is not None
        and float(page["confidence"]) < 0.50
    ]
    warnings = list(split_validation["reasons"])
    if empty_pages:
        warnings.append(f"empty OCR pages: {empty_pages}")
    if low_confidence_pages:
        warnings.append(
            f"{len(low_confidence_pages)} page(s) have OCR confidence below 0.50"
        )
    if not metadata.appeal_number:
        warnings.append("appeal number metadata missing")
    if not metadata.public_authority:
        warnings.append("public authority metadata missing")
    if not any(
        chunk["chunk_type"] in {"COMMISSION_FINDINGS", "LEGAL_REASONING"}
        for chunk in chunks
    ):
        warnings.append("no commission finding or legal reasoning chunk detected")

    return {
        "decision_id": decision_id,
        "input_file": str(structured_path),
        "source_pdf": structured.get("source_pdf", ""),
        "quality_status": "review" if warnings else "pass",
        "split_validation": split_validation,
        "metadata_completeness": {
            "appeal_number": bool(metadata.appeal_number),
            "decision_date": bool(metadata.decision_date),
            "appellant": bool(metadata.appellant),
            "public_authority": bool(metadata.public_authority),
            "rti_sections": bool(metadata.rti_sections),
        },
        "ocr_quality": {
            "page_count": len(pages),
            "empty_pages": empty_pages,
            "low_confidence_pages": low_confidence_pages,
            "minimum_confidence": minimum_page_confidence(pages),
        },
        "chunk_quality": {
            "chunk_count": len(chunks),
            "chunk_type_counts": dict(
                sorted(Counter(chunk["chunk_type"] for chunk in chunks).items())
            ),
            "minimum_words": min(words) if words else 0,
            "maximum_words": max(words) if words else 0,
            "chunks_above_hard_max": [
                chunk["chunk_id"]
                for chunk in substantive
                if len(chunk["text"].split()) > hard_max_words
            ],
            "hard_max_words": hard_max_words,
        },
        "warnings": unique(warnings),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def find_structured_files(input_path: Path) -> list[Path]:
    if input_path.is_file() and input_path.name == "structured.json":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("structured.json"))
    return []


def chunk_corpus(
    input_path: Path,
    output_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    target_words: int = 350,
    hard_max_words: int = 600,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    structured_files = find_structured_files(input_path)
    if not structured_files:
        raise ValueError(f"No structured.json files found under {input_path}")

    chunker = CGSICDecisionChunker(
        manifest_path=manifest_path,
        target_words=target_words,
        hard_max_words=hard_max_words,
    )
    all_chunks = []
    reports = []
    for structured_path in structured_files:
        chunks, report = chunker.chunk_structured(structured_path)
        decision_id = report["decision_id"]
        decision_output = output_path / decision_id
        write_jsonl(decision_output / "legal_chunks.jsonl", chunks)
        write_json(decision_output / "chunk_quality_report.json", report)
        all_chunks.extend(chunks)
        reports.append(report)

    aggregate = {
        "schema_version": 1,
        "input": str(input_path),
        "manifest": str(manifest_path),
        "decisions_processed": len(reports),
        "decisions_passed": sum(
            report["quality_status"] == "pass" for report in reports
        ),
        "decisions_requiring_review": sum(
            report["quality_status"] == "review" for report in reports
        ),
        "split_quality_counts": dict(
            Counter(
                report["split_validation"]["split_quality"]
                for report in reports
            )
        ),
        "total_chunks": len(all_chunks),
        "chunk_type_counts": dict(
            sorted(Counter(chunk["chunk_type"] for chunk in all_chunks).items())
        ),
        "reports": reports,
    }
    write_jsonl(output_path / "cgsic_legal_chunks.jsonl", all_chunks)
    write_json(output_path / "chunk_quality_report.json", aggregate)
    return all_chunks, aggregate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chunk CGSIC Stage 2 structured JSON into legal JSONL"
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help="structured.json file or directory containing decision folders",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="CGSIC 136-decision manifest",
    )
    parser.add_argument("--target-words", type=int, default=350)
    parser.add_argument("--hard-max-words", type=int, default=600)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input path not found: {args.input}")
    if args.target_words <= 0 or args.hard_max_words < args.target_words:
        raise SystemExit("Require 0 < target-words <= hard-max-words")

    chunks, report = chunk_corpus(
        input_path=args.input,
        output_path=args.output,
        manifest_path=args.manifest,
        target_words=args.target_words,
        hard_max_words=args.hard_max_words,
    )
    print(f"Processed decisions : {report['decisions_processed']}")
    print(f"Generated chunks    : {len(chunks)}")
    print(f"Passed quality      : {report['decisions_passed']}")
    print(f"Require review      : {report['decisions_requiring_review']}")
    print(f"Output              : {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
