#!/usr/bin/env python3
"""
CIC / RTI legal-section-aware chunker.

This layer expects text or markdown that has already come from Docling OCR/layout
extraction. It does not replace Docling; it turns extracted CIC decisions into
retrieval-ready legal chunks with stable metadata.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RETRIEVAL_PRIORITY = {
    "PRECEDENT_SUMMARY": 100,
    "COMMISSION_OBSERVATIONS": 95,
    "FINAL_ORDER": 90,
    "PIO_LEARNING_SIGNAL": 85,
    "INFORMATION_REQUESTED": 75,
    "GROUNDS_FOR_APPEAL": 65,
    "HEARING_SUBMISSIONS": 60,
    "CASE_METADATA": 40,
    "SIGNATURE_AUTHENTICATION": 10,
}

LEGAL_CHUNK_TYPES = set(RETRIEVAL_PRIORITY)


@dataclass
class ExtractedCase:
    case_number: str = ""
    source_type: str = "CIC_DECISION"
    appellant: str = ""
    respondent: str = ""
    public_authority: str = ""
    commissioner: str = ""
    rti_application_date: str = ""
    cpio_reply_date: str = ""
    first_appeal_date: str = ""
    faa_order_date: str = ""
    second_appeal_date: str = ""
    hearing_date: str = ""
    decision_date: str = ""
    outcome: str = ""
    rti_sections: list[str] = field(default_factory=list)
    exemption_sections: list[str] = field(default_factory=list)
    court_references: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def metadata(self) -> dict[str, Any]:
        return {
            "case_number": self.case_number,
            "source_type": self.source_type,
            "appellant": self.appellant,
            "respondent": self.respondent,
            "public_authority": self.public_authority,
            "commissioner": self.commissioner,
            "rti_application_date": self.rti_application_date,
            "cpio_reply_date": self.cpio_reply_date,
            "first_appeal_date": self.first_appeal_date,
            "faa_order_date": self.faa_order_date,
            "second_appeal_date": self.second_appeal_date,
            "hearing_date": self.hearing_date,
            "decision_date": self.decision_date,
            "outcome": self.outcome,
            "rti_sections": self.rti_sections,
            "exemption_sections": self.exemption_sections,
            "court_references": self.court_references,
            "keywords": self.keywords,
        }


class LegalDocumentParser:
    """Extract stable case metadata from Docling markdown/text."""

    DATE_PATTERNS = {
        "rti_application_date": r"RTI application\s*\|?\s*[:|]?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})",
        "cpio_reply_date": r"CPIO reply\s*\|?\s*[:|]?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})",
        "first_appeal_date": r"First Appeal\s*\|?\s*[:|]?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})",
        "faa_order_date": r"FAA Order\s*\|?\s*[:|]?\s*([A-Za-z ]+|\d{1,2}\.\d{1,2}\.\d{2,4})",
        "second_appeal_date": r"Second Appeal\s*\|?\s*[:|]?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})",
        "hearing_date": r"Date of hearing\s*\|?\s*[:|]?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})",
    }

    def parse(self, text: str) -> ExtractedCase:
        normalized = normalize_text(text)
        case = ExtractedCase()
        case.case_number = self._extract_case_number(normalized)
        case.appellant = self._extract_appellant(normalized)
        case.respondent = self._extract_respondent(normalized)
        case.public_authority = self._extract_public_authority(case.respondent, normalized)
        case.commissioner = self._extract_commissioner(normalized)
        case.outcome = self._extract_outcome(normalized)
        case.court_references = self._extract_court_references(normalized)
        case.keywords = self._extract_keywords(normalized)

        for field_name, pattern in self.DATE_PATTERNS.items():
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                setattr(case, field_name, clean_value(match.group(1)))

        return case

    def _extract_case_number(self, text: str) -> str:
        match = re.search(r"\bCIC\s*/?\s*([A-Z]{3,})\s*/\s*([A-Z])\s*/\s*(\d{4})\s*/\s*(\d+)", text)
        if match:
            registry = match.group(1)
            if registry.startswith("IAAOIN"):
                registry = registry[1:]
            return f"CIC/{registry}/{match.group(2)}/{match.group(3)}/{match.group(4)}"
        match = re.search(r"\b(CIC[ /A-Z0-9_-]{8,}\d{3,})", text)
        return clean_value(match.group(1)).replace(" ", "") if match else ""

    def _extract_appellant(self, text: str) -> str:
        match = re.search(r"In the matter of:\s*(.+?)(?:\n+| Appellant\b)", text, re.IGNORECASE)
        return clean_value(match.group(1)) if match else ""

    def _extract_respondent(self, text: str) -> str:
        match = re.search(r"Vs\.\s*(.+?)\s+Respondent\b", text, re.IGNORECASE | re.DOTALL)
        if match:
            return clean_value(match.group(1))
        match = re.search(r"Respondent:\s*(.+?)(?:During the hearing|$)", text, re.IGNORECASE | re.DOTALL)
        return clean_value(match.group(1)) if match else ""

    def _extract_public_authority(self, respondent: str, text: str) -> str:
        for candidate in (
            r"Airport Authority of India",
            r"Airports Authority of India",
            r"Central Information Commission",
        ):
            match = re.search(candidate, respondent or text, re.IGNORECASE)
            if match:
                return match.group(0)
        return respondent

    def _extract_commissioner(self, text: str) -> str:
        match = re.search(r"\[?([A-Z][A-Za-z .]+?)\]?\s+Information Commissioner", text)
        if not match:
            return ""
        commissioner = clean_value(match.group(1))
        if commissioner.startswith("IAmitava"):
            commissioner = commissioner[1:]
        return commissioner

    def _extract_outcome(self, text: str) -> str:
        lowered = text.lower()
        if "appeal is disposed" in lowered or "appeal is disposed of" in lowered:
            return "appeal disposed of"
        if "appeal is allowed" in lowered:
            return "appeal allowed"
        if "appeal is rejected" in lowered or "appeal is dismissed" in lowered:
            return "appeal rejected"
        return ""

    def _extract_court_references(self, text: str) -> list[str]:
        refs = []
        for match in re.finditer(r"Hon ?ble\s+High Court[^.,\n]*", text, re.IGNORECASE):
            refs.append(clean_value(match.group(0)))
        return unique(refs)

    def _extract_keywords(self, text: str) -> list[str]:
        keywords = []
        checks = {
            "committee": r"\bcommittee\b",
            "high court": r"high court",
            "mumbai airport": r"mumbai airport",
            "final report": r"final report",
            "pointwise reply": r"pointwise",
            "construction restriction": r"construction.*radius|radius.*construction",
        }
        for label, pattern in checks.items():
            if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                keywords.append(label)
        return keywords


class LegalSectionChunker:
    """Create CIC legal chunks with metadata and retrieval priorities."""

    def __init__(self, target_words: tuple[int, int] = (250, 450), hard_max_words: int = 600):
        self.target_words = target_words
        self.hard_max_words = hard_max_words
        self.parser = LegalDocumentParser()

    def chunk_text(self, text: str, source_name: str = "") -> list[dict[str, Any]]:
        normalized = normalize_text(text)
        case = self.parser.parse(normalized)
        sections = self._detect_sections(normalized)

        chunks: list[dict[str, Any]] = []
        self._add_chunk(chunks, case, "CASE_METADATA", self._metadata_text(case), source_name, 1, 1)
        self._add_section_chunks(chunks, case, "INFORMATION_REQUESTED", sections["information_requested"], source_name)
        self._add_section_chunks(chunks, case, "GROUNDS_FOR_APPEAL", sections["grounds_for_appeal"], source_name)
        self._add_section_chunks(chunks, case, "HEARING_SUBMISSIONS", sections["hearing_submissions"], source_name)
        self._add_section_chunks(chunks, case, "COMMISSION_OBSERVATIONS", sections["commission_observations"], source_name)
        self._add_section_chunks(chunks, case, "FINAL_ORDER", sections["final_order"], source_name)
        self._add_chunk(chunks, case, "PIO_LEARNING_SIGNAL", self._pio_learning(case, sections), source_name, None, None)
        self._add_chunk(chunks, case, "PRECEDENT_SUMMARY", self._precedent_summary(case, sections), source_name, None, None)
        return chunks

    def chunk_file(self, input_path: Path, output_path: Path | None = None) -> list[dict[str, Any]]:
        if input_path.is_dir():
            return self.chunk_directory(input_path, output_path)

        text = input_path.read_text(encoding="utf-8")
        chunks = self.chunk_text(text, source_name=input_path.parent.name if input_path.name == "structured.md" else input_path.stem)
        if output_path:
            write_jsonl(chunks, output_path)
        return chunks

    def chunk_directory(self, input_dir: Path, output_root: Path | None = None) -> list[dict[str, Any]]:
        if output_root and output_root.suffix:
            raise ValueError("Output path for directory input must be a directory")

        output_root = output_root or Path(__file__).resolve().parent / "legal_output" / input_dir.name
        chunks: list[dict[str, Any]] = []
        for structured in sorted(input_dir.rglob("structured.md")):
            if not structured.is_file():
                continue
            relative_dir = structured.parent.relative_to(input_dir)
            output_path = output_root / relative_dir / "legal_chunks.jsonl"
            chunks.extend(self.chunk_file(structured, output_path))
        return chunks

    def _detect_sections(self, text: str) -> dict[str, dict[str, Any]]:
        facts_start = find_heading(text, "Facts")
        grounds_start = find_heading(text, "Grounds for Second Appeal")
        order_start = find_heading(text, "Order")

        info_start = facts_start if facts_start >= 0 else 0
        info_end = grounds_start if grounds_start >= 0 else order_start if order_start >= 0 else len(text)
        grounds_end = order_start if order_start >= 0 else len(text)

        order_text = text[order_start: len(text)] if order_start >= 0 else ""
        observation_start_rel = find_phrase(order_text, "On perusal of the case record")
        final_start_rel = find_phrase(order_text, "With the above observation")
        if final_start_rel < 0:
            final_start_rel = find_phrase(order_text, "the appeal is")

        hearing_end_rel = observation_start_rel if observation_start_rel >= 0 else final_start_rel if final_start_rel >= 0 else len(order_text)
        observation_end_rel = final_start_rel if final_start_rel >= 0 else len(order_text)

        return {
            "information_requested": {
                "text": trim_heading(text[info_start:info_end]),
                "page_start": 1,
                "page_end": 2 if "<!-- Page 2 -->" in text[info_start:info_end] else 1,
            },
            "grounds_for_appeal": {
                "text": trim_heading(text[grounds_start:grounds_end]) if grounds_start >= 0 else "",
                "page_start": 2,
                "page_end": 2,
            },
            "hearing_submissions": {
                "text": trim_heading(order_text[:hearing_end_rel]),
                "page_start": 2,
                "page_end": 2,
            },
            "commission_observations": {
                "text": clean_value(order_text[observation_start_rel:observation_end_rel]) if observation_start_rel >= 0 else "",
                "page_start": 2,
                "page_end": 2,
            },
            "final_order": {
                "text": self._extract_final_order(order_text[final_start_rel:]) if final_start_rel >= 0 else "",
                "page_start": 2,
                "page_end": 2,
            },
        }

    def _extract_final_order(self, text: str) -> str:
        if not text:
            return ""
        stop = re.search(r"\[?[A-Z][A-Za-z .]+?\]?\s+Information Commissioner", text)
        final_text = text[: stop.start()] if stop else text
        final_text = re.sub(r"Authenticated true copy.*", "", final_text, flags=re.IGNORECASE | re.DOTALL)
        return clean_value(final_text)

    def _add_section_chunks(
        self,
        chunks: list[dict[str, Any]],
        case: ExtractedCase,
        chunk_type: str,
        section: dict[str, Any],
        source_name: str,
    ) -> None:
        text = clean_value(section.get("text", ""))
        if not text:
            return
        for part in split_long_section(text, self.hard_max_words):
            self._add_chunk(
                chunks,
                case,
                chunk_type,
                part,
                source_name,
                section.get("page_start"),
                section.get("page_end"),
            )

    def _add_chunk(
        self,
        chunks: list[dict[str, Any]],
        case: ExtractedCase,
        chunk_type: str,
        text: str,
        source_name: str,
        page_start: int | None,
        page_end: int | None,
    ) -> None:
        if chunk_type not in LEGAL_CHUNK_TYPES:
            raise ValueError(f"Unsupported legal chunk type: {chunk_type}")
        text = clean_value(text)
        if not text:
            return
        metadata = case.metadata()
        metadata.update(
            {
                "chunk_type": chunk_type,
                "page_start": page_start,
                "page_end": page_end,
                "retrieval_priority": RETRIEVAL_PRIORITY[chunk_type],
            }
        )
        chunk_index = len(chunks) + 1
        chunk_id_base = case.case_number or source_name or "unknown"
        chunk_id = safe_id(f"{chunk_id_base}_{chunk_type}_{chunk_index:03d}")
        chunks.append(
            {
                "chunk_id": chunk_id,
                "source": source_name,
                "text": text,
                **metadata,
            }
        )

    def _metadata_text(self, case: ExtractedCase) -> str:
        lines = [
            f"Case Number: {case.case_number}",
            f"Appellant: {case.appellant}",
            f"Respondent: {case.respondent}",
            f"Public Authority: {case.public_authority}",
            f"RTI Application Date: {case.rti_application_date}",
            f"CPIO Reply Date: {case.cpio_reply_date}",
            f"First Appeal Date: {case.first_appeal_date}",
            f"FAA Order Date: {case.faa_order_date}",
            f"Second Appeal Date: {case.second_appeal_date}",
            f"Hearing Date: {case.hearing_date}",
            f"Commissioner: {case.commissioner}",
            f"Outcome: {case.outcome}",
        ]
        return "\n".join(line for line in lines if not line.endswith(": "))

    def _pio_learning(self, case: ExtractedCase, sections: dict[str, dict[str, Any]]) -> str:
        observations = sections.get("commission_observations", {}).get("text", "").lower()
        if "just" in observations and "proper" in observations and "pointwise" in observations:
            return "Timely, pointwise, and proper replies are likely to be upheld where no deficiency is shown."
        if "penalty" in observations or "show cause" in observations:
            return "PIOs should respond within statutory timelines and document reasons to avoid penalty or show-cause risk."
        return "PIOs should give clear, timely, pointwise replies and preserve proof of dispatch for appeal hearings."

    def _precedent_summary(self, case: ExtractedCase, sections: dict[str, dict[str, Any]]) -> str:
        info = sections.get("information_requested", {}).get("text", "")
        observations = sections.get("commission_observations", {}).get("text", "")
        final_order = sections.get("final_order", {}).get("text", "")
        return clean_value(
            "Information requested: "
            + summarize_text(info, 65)
            + " Legal issue: whether the CPIO response required Commission intervention. "
            + "Commission reasoning: "
            + summarize_text(observations, 55)
            + " Outcome: "
            + (case.outcome or summarize_text(final_order, 25))
        )


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_value(value: str) -> str:
    value = re.sub(r"<!-- Page \d+ -->", " ", value or "")
    value = re.sub(r"^#+\s*", "", value.strip())
    value = re.sub(r"\s+", " ", value)
    return value.strip(" :|-")


def find_heading(text: str, heading: str) -> int:
    match = re.search(rf"(?im)^\s*#+\s*{re.escape(heading)}\s*:?\s*$", text)
    if match:
        return match.start()
    match = re.search(rf"(?i)\b{re.escape(heading)}\b", text)
    return match.start() if match else -1


def find_phrase(text: str, phrase: str) -> int:
    match = re.search(re.escape(phrase), text, re.IGNORECASE)
    return match.start() if match else -1


def trim_heading(text: str) -> str:
    text = re.sub(r"(?im)^\s*#+\s*[^:\n]+:?\s*$", "", text, count=1)
    return clean_value(text)


def split_long_section(text: str, hard_max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= hard_max_words:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) <= 1:
        return [" ".join(words[i : i + hard_max_words]) for i in range(0, len(words), hard_max_words)]

    chunks: list[str] = []
    current: list[str] = []
    for paragraph in paragraphs:
        candidate = " ".join(current + [paragraph])
        if len(candidate.split()) > hard_max_words and current:
            chunks.append(" ".join(current))
            current = [paragraph]
        else:
            current.append(paragraph)
    if current:
        chunks.append(" ".join(current))
    return chunks


def summarize_text(text: str, max_words: int) -> str:
    words = clean_value(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,.;") + "..."


def safe_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_/-]+", "_", value)
    return value.replace("/", "_").strip("_")


def unique(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def write_jsonl(chunks: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate CIC/RTI legal-section JSONL chunks")
    parser.add_argument("--input", "-i", required=True, help="Docling structured.md, text file, or folder")
    parser.add_argument("--output", "-o", help="Output JSONL file or directory")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input path not found: {input_path}")

    if args.output:
        output_path = Path(args.output)
    elif input_path.is_dir():
        output_path = Path(__file__).resolve().parent / "legal_output" / input_path.name
    else:
        output_dir = Path(__file__).resolve().parent / "legal_output" / input_path.parent.name
        output_path = output_dir / "legal_chunks.jsonl"

    if input_path.is_dir():
        if output_path.exists() and output_path.is_file():
            raise SystemExit("When --input is a directory, --output must be an output directory")
        output_path.mkdir(parents=True, exist_ok=True)
    elif output_path.exists() and output_path.is_dir():
        output_path = output_path / "legal_chunks.jsonl"

    chunks = LegalSectionChunker().chunk_file(input_path, output_path)
    print(f"Generated {len(chunks)} legal chunks: {output_path}")
    for chunk in chunks:
        print(f"- {chunk['chunk_type']} priority={chunk['retrieval_priority']} words={len(chunk['text'].split())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
