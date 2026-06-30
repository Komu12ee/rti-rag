#!/usr/bin/env python3
r'''RTI legal Q&A chunker with section-level citations.

Creates one chunk per legal Q&A block, supports Q./Q:/Question N/प्रश्न N,
and writes source metadata for Qdrant/Web UI. It does not use Docling.

Recommended:
python RTI_legal_chunker_final.py --input ".\\structured.md" --output ".\\output" \
  --source-book "rti-rule-book.pdf" --source-type rti_rule_book \
  --book-pdf-offset 12 --source-manifest ".\\rti_source_manifest.json" \
  --strict-citations --clean-output

Manifest example:
{
  "defaults": {"source_book":"rti-rule-book.pdf", "source_type":"rti_rule_book", "book_pdf_offset":12},
  "rules": [
    {"match":"(?i)Section\\s*1\\b", "legal_reference":"Section 1", "book_pages":"2"},
    {"match":"(?i)Section\\s*8\\s*\\(1\\)\\s*\\(j\\)", "legal_reference":"Section 8(1)(j)", "book_pages":"22"}
  ]
}

Manifest regexes are matched only against CHAPTER + QUESTION, never answer text.
'''

from __future__ import annotations

import argparse
import copy
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Regexes
# -----------------------------------------------------------------------------

# Q. ..., Q: ..., Question 1. ..., प्रश्न 1. ...
QUESTION_RE = re.compile(
    r"""^\s*(?:#{1,6}\s*)?(?:
        (?P<long_label>प्रश्न|प्रश्‍न|question)\s*(?P<number>[0-9०-९]+)\s*[.।:：]?
      | (?P<short_label>q)\s*[.:：]
    )\s*(?P<text>.*?)\s*$""",
    re.IGNORECASE | re.UNICODE | re.VERBOSE,
)
ANSWER_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?:उत्तर|answer)\s*(?:\*\*)?\s*(?:[:ः：-])",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)
MARKDOWN_SECTION_RE = re.compile(r"^\s*#{1,2}(?!#)\s+(?P<title>.+?)\s*$", re.UNICODE)
CHAPTER_RE = re.compile(
    r"^\s*(?:chapter\s+(?:[ivxlcdm]+|\d+)\b.*|अध्याय\s*(?:[0-9०-९]+|[ivxlcdm]+)?\b.*)\s*$",
    re.IGNORECASE | re.UNICODE,
)
SECTION_HEADING_RE = re.compile(
    r"^\s*(?:section|sec\.?|धारा)\s*(?P<section>\d+(?:\s*\(\s*[0-9A-Za-z]+\s*\))*)"
    r"\s*(?:[-–—:.]\s*)?(?P<title>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
PAGE_MARKER_RE = re.compile(r"^\s*<!--\s*Page\s+(?P<page>\d+)\s*-->\s*$", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"^\s*<!--.*?-->\s*$")

# Supports Section 1, Section 8(1)(j), Section 19(8)(a), Rule 3(2), etc.
LEGAL_SECTION_RE = re.compile(
    r"\b(?:section|sec\.?)\s*(?P<section>\d+(?:\s*\(\s*[0-9A-Za-z]+\s*\))*)"
    r"(?=\s|$|[.,;:?!])",
    re.IGNORECASE,
)
LEGAL_RULE_RE = re.compile(
    r"\b(?:rule)\s*(?P<rule>\d+(?:\s*\(\s*[0-9A-Za-z]+\s*\))*)"
    r"(?=\s|$|[.,;:?!])",
    re.IGNORECASE,
)

# Explicit source metadata lines. These are stripped from the embedded body.
SOURCE_BOOK_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*"
    r"(?:source\s+book|original\s+source(?:\s+book)?|book\s+source)"
    r"\s*(?:\*\*)?\s*(?::|-)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
SOURCE_REFERENCE_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*"
    r"(?:source\s+reference|original\s+source|legal\s+source)"
    r"\s*(?:\*\*)?\s*(?::|-)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
LEGAL_REFERENCE_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*legal\s+reference\s*(?:\*\*)?\s*(?::|-)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
BOOK_PAGES_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*(?:book\s+pages?|printed\s+pages?)\s*(?:\*\*)?\s*(?::|-)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
PDF_PAGES_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*(?:source\s+pdf\s+pages?|pdf\s+pages?|viewer\s+pages?)\s*(?:\*\*)?\s*(?::|-)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
SOURCE_TYPE_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*source\s+type\s*(?:\*\*)?\s*(?::|-)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
CITATION_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*citation\s*(?:\*\*)?\s*(?::|-)?\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
BOOK_FILE_RE = re.compile(r"(?P<book>[\w.\- ()]+?\.pdf)\b", re.IGNORECASE)
BOOK_PAGE_IN_TEXT_RE = re.compile(
    r"\b(?:book\s*)?(?:pp?\.?|pages?)\s*[:.]?\s*"
    r"(?P<pages>\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)",
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# Data structures
# -----------------------------------------------------------------------------

@dataclass
class SourceReference:
    source_book: str = ""
    source_type: str = ""
    legal_reference: str = ""
    book_pages: list[int] = field(default_factory=list)
    pdf_pages: list[int] = field(default_factory=list)
    input_pages: list[int] = field(default_factory=list)
    citation_label: str = ""

    def normalized(self) -> "SourceReference":
        self.source_book = self.source_book.strip()
        self.source_type = self.source_type.strip() or "general"
        self.legal_reference = self.legal_reference.strip()
        self.book_pages = unique_sorted_pages(self.book_pages)
        self.pdf_pages = unique_sorted_pages(self.pdf_pages)
        self.input_pages = unique_sorted_pages(self.input_pages)
        self.citation_label = self.citation_label.strip()
        return self


@dataclass
class LegalBlock:
    chapter: str
    question_line: str
    body: str
    input_pages: list[int] = field(default_factory=list)
    source_reference: SourceReference = field(default_factory=SourceReference)
    ordinal: int = 0
    kind: str = "faq"  # faq | section_note

    @property
    def has_answer(self) -> bool:
        return bool(ANSWER_RE.search(self.body))


@dataclass
class OutputChunk:
    index: int
    chapter: str
    question_line: str
    body: str
    input_pages: list[int]
    source_reference: SourceReference
    source_block_ordinal: int
    part: int
    parts_in_block: int
    kind: str
    has_answer: bool
    content_tokens: int = 0


# -----------------------------------------------------------------------------
# Token counting
# -----------------------------------------------------------------------------

class TokenCounter:
    def __init__(self, model: Optional[str], use_tokenizer: bool = True) -> None:
        self.model = model
        self.tokenizer = None
        if not use_tokenizer or not model:
            logger.warning("Tokenizer disabled; using approximate Unicode token counts.")
            return
        try:
            from transformers import AutoTokenizer
            logger.info("Loading tokenizer: %s", model)
            self.tokenizer = AutoTokenizer.from_pretrained(model)
        except Exception as exc:
            logger.warning("Could not load tokenizer '%s': %s. Using approximate counts.", model, exc)

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self.tokenizer is not None:
            return len(self.tokenizer.encode(text, add_special_tokens=False))
        return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


# -----------------------------------------------------------------------------
# Source manifest
# -----------------------------------------------------------------------------

class SourceManifest:
    """Rules are applied to chapter + question only, never statutory answer text."""

    def __init__(self, data: Optional[dict] = None) -> None:
        self.data = data or {}
        self.defaults = self.data.get("defaults", {}) if isinstance(self.data, dict) else {}
        self.documents = self.data.get("documents", {}) if isinstance(self.data, dict) else {}
        self.rules = self.data.get("rules", []) if isinstance(self.data, dict) else []

    @classmethod
    def load(cls, path: Optional[Path]) -> "SourceManifest":
        if path is None:
            return cls({})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Source manifest not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in source manifest {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Source manifest root must be a JSON object.")
        return cls(data)

    def resolve(self, document_name: str, identity_text: str) -> dict:
        config: dict[str, Any] = {}
        if isinstance(self.defaults, dict):
            config.update(self.defaults)
        doc_config = self.documents.get(document_name, {})
        if isinstance(doc_config, dict):
            config.update(doc_config)
        for rule in self.rules:
            if not isinstance(rule, dict):
                continue
            pattern = str(rule.get("match", "")).strip()
            if not pattern:
                continue
            try:
                if re.search(pattern, identity_text, flags=re.IGNORECASE | re.MULTILINE):
                    config.update({k: v for k, v in rule.items() if k != "match"})
            except re.error as exc:
                logger.warning("Ignoring invalid manifest regex '%s': %s", pattern, exc)
        return config


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def normalize_lines(lines: Iterable[str]) -> str:
    values = list(lines)
    while values and not values[0].strip():
        values.pop(0)
    while values and not values[-1].strip():
        values.pop()
    return "\n".join(values)


def unique_sorted_pages(pages: Iterable[int]) -> list[int]:
    return sorted({p for p in pages if isinstance(p, int) and p > 0})


def parse_page_spec(value: Any) -> list[int]:
    """Parse 2, [2,3], '2-4', '2,4-6', 'pp. 33-35'."""
    if value is None:
        return []
    if isinstance(value, int):
        return [value] if value > 0 else []
    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            result.extend(parse_page_spec(item))
        return unique_sorted_pages(result)
    text = str(value).strip()
    if not text:
        return []
    text = re.sub(r"(?i)\b(?:book\s*)?(?:pp?\.?|pages?)\s*[:.]?\s*", "", text)
    result: list[int] = []
    for token in re.split(r"\s*,\s*", text):
        token = token.strip().replace("–", "-").replace("—", "-")
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            try:
                start, end = int(left.strip()), int(right.strip())
            except ValueError:
                continue
            if start > 0 and end >= start and end - start <= 1000:
                result.extend(range(start, end + 1))
        else:
            try:
                page = int(token)
            except ValueError:
                continue
            if page > 0:
                result.append(page)
    return unique_sorted_pages(result)


def format_pages(pages: Iterable[int]) -> str:
    values = unique_sorted_pages(pages)
    if not values:
        return "Unknown"
    ranges: list[str] = []
    start = previous = values[0]
    for page in values[1:]:
        if page == previous + 1:
            previous = page
        else:
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def compact_legal_token(value: str) -> str:
    return re.sub(r"\s+", "", value)


def infer_legal_reference(identity_text: str) -> str:
    """Call only with chapter/question, never a full statutory answer."""
    section = LEGAL_SECTION_RE.search(identity_text)
    if section:
        return f"Section {compact_legal_token(section.group('section'))}"
    rule = LEGAL_RULE_RE.search(identity_text)
    if rule:
        return f"Rule {compact_legal_token(rule.group('rule'))}"
    return ""


def canonical_question_label(label: str) -> str:
    return "Question" if label.casefold() == "question" else "प्रश्न"


def is_english_question(question: str) -> bool:
    return question.strip().casefold().startswith(("q.", "question"))


def continuation_label(question: str) -> str:
    return "**Answer continued:**" if is_english_question(question) else "**उत्तर जारी है:**"


def build_citation_label(ref: SourceReference) -> str:
    if not ref.source_book:
        return ""
    parts = [ref.source_book]
    if ref.legal_reference:
        parts.append(ref.legal_reference)
    if ref.book_pages:
        page_prefix = "p." if len(ref.book_pages) == 1 else "pp."
        parts.append(f"book {page_prefix} {format_pages(ref.book_pages)}")
    return " — ".join(parts)


def merge_reference(base: SourceReference, update: SourceReference) -> SourceReference:
    """Explicit update fields override prior values; supplied pages replace prior pages."""
    result = copy.deepcopy(base)
    for attr in ("source_book", "source_type", "legal_reference", "citation_label"):
        value = getattr(update, attr)
        if value:
            setattr(result, attr, value)
    for attr in ("book_pages", "pdf_pages", "input_pages"):
        value = getattr(update, attr)
        if value:
            setattr(result, attr, unique_sorted_pages(value))
    return result


def reference_from_config(config: Optional[dict], input_pages: Optional[list[int]] = None) -> SourceReference:
    config = config or {}
    return SourceReference(
        source_book=str(config.get("source_book", "") or ""),
        source_type=str(config.get("source_type", "") or ""),
        legal_reference=str(config.get("legal_reference", "") or ""),
        book_pages=parse_page_spec(config.get("book_pages")),
        pdf_pages=parse_page_spec(config.get("pdf_pages")),
        input_pages=unique_sorted_pages(input_pages or []),
        citation_label=str(config.get("citation_label", "") or ""),
    )


def apply_pdf_offset(ref: SourceReference, offset: Optional[int]) -> SourceReference:
    result = copy.deepcopy(ref)
    if result.book_pages and not result.pdf_pages and offset is not None:
        result.pdf_pages = [p + offset for p in result.book_pages if p + offset > 0]
    return result.normalized()


def extract_inline_reference(raw_line: str) -> Optional[SourceReference]:
    """Parse source metadata lines. Return None for ordinary legal answer text."""
    line = raw_line.strip()
    match = SOURCE_BOOK_LINE_RE.match(line)
    if match:
        value = match.group("value").strip().strip("*")
        book = BOOK_FILE_RE.search(value)
        pages = BOOK_PAGE_IN_TEXT_RE.search(value)
        parsed_pages = parse_page_spec(pages.group("pages")) if pages else parse_page_spec(value)
        return SourceReference(
            source_book=book.group("book").strip() if book else "",
            legal_reference=infer_legal_reference(value),
            book_pages=parsed_pages,
        )
    match = SOURCE_REFERENCE_LINE_RE.match(line)
    if match:
        value = match.group("value").strip().strip("*")
        book = BOOK_FILE_RE.search(value)
        pages = BOOK_PAGE_IN_TEXT_RE.search(value)
        return SourceReference(
            source_book=book.group("book").strip() if book else "",
            legal_reference=infer_legal_reference(value),
            book_pages=parse_page_spec(pages.group("pages")) if pages else [],
        )
    match = LEGAL_REFERENCE_LINE_RE.match(line)
    if match:
        return SourceReference(legal_reference=match.group("value").strip().strip("*"))
    match = BOOK_PAGES_LINE_RE.match(line)
    if match:
        return SourceReference(book_pages=parse_page_spec(match.group("value")))
    match = PDF_PAGES_LINE_RE.match(line)
    if match:
        return SourceReference(pdf_pages=parse_page_spec(match.group("value")))
    match = SOURCE_TYPE_LINE_RE.match(line)
    if match:
        return SourceReference(source_type=match.group("value").strip().strip("*"))
    match = CITATION_LINE_RE.match(line)
    if match:
        return SourceReference(citation_label=match.group("value").strip().strip("*"))
    return None


# -----------------------------------------------------------------------------
# Parsing: one block per legal Q&A
# -----------------------------------------------------------------------------

def parse_legal_qa_markdown(
    markdown: str,
    *,
    document_name: str,
    manifest: SourceManifest,
    cli_source_config: dict,
    book_pdf_offset: Optional[int],
    include_section_notes: bool,
) -> list[LegalBlock]:
    blocks: list[LegalBlock] = []
    current_chapter = "Untitled section"
    current_input_page: Optional[int] = None
    pending_reference = SourceReference()
    active: Optional[dict[str, Any]] = None
    note_lines: list[str] = []
    note_pages: list[int] = []

    def add_page(target: list[int]) -> None:
        if current_input_page is not None and current_input_page not in target:
            target.append(current_input_page)

    def resolve_reference(chapter: str, question: str, pages: list[int], explicit: SourceReference) -> SourceReference:
        # The answer body is intentionally excluded from identity_text.
        identity_text = f"{chapter}\n{question}".strip()
        result = reference_from_config(cli_source_config, pages)
        manifest_config = manifest.resolve(document_name, identity_text)
        result = merge_reference(result, reference_from_config(manifest_config, pages))
        result = merge_reference(result, explicit)
        result.input_pages = unique_sorted_pages(pages)
        if not result.legal_reference:
            result.legal_reference = infer_legal_reference(identity_text)
        offset = book_pdf_offset
        if offset is None and manifest_config.get("book_pdf_offset") not in (None, ""):
            try:
                offset = int(manifest_config["book_pdf_offset"])
            except (TypeError, ValueError):
                logger.warning("Invalid book_pdf_offset in source manifest: %r", manifest_config.get("book_pdf_offset"))
        result = apply_pdf_offset(result, offset)
        if not result.citation_label:
            result.citation_label = build_citation_label(result)
        return result.normalized()

    def flush_note() -> None:
        nonlocal note_lines, note_pages
        text = normalize_lines(note_lines)
        if include_section_notes and text:
            ref = resolve_reference(current_chapter, "", note_pages, pending_reference)
            blocks.append(LegalBlock(
                chapter=current_chapter,
                question_line="",
                body=text,
                input_pages=unique_sorted_pages(note_pages),
                source_reference=ref,
                ordinal=len(blocks) + 1,
                kind="section_note",
            ))
        note_lines, note_pages = [], []

    def flush_active() -> None:
        nonlocal active, pending_reference
        if active is None:
            return
        body = normalize_lines(active["body_lines"])
        ref = resolve_reference(
            active["chapter"],
            active["question_line"],
            active["input_pages"],
            active["reference"],
        )
        blocks.append(LegalBlock(
            chapter=active["chapter"],
            question_line=active["question_line"],
            body=body,
            input_pages=unique_sorted_pages(active["input_pages"]),
            source_reference=ref,
            ordinal=len(blocks) + 1,
            kind="faq",
        ))
        active = None
        pending_reference = SourceReference()

    for raw_line in markdown.splitlines():
        page_match = PAGE_MARKER_RE.match(raw_line)
        if page_match:
            current_input_page = int(page_match.group("page"))
            if active is not None:
                add_page(active["input_pages"])
            else:
                add_page(note_pages)
            continue
        if HTML_COMMENT_RE.match(raw_line):
            # Drops OCR/internal comments, e.g. extraction_method/confidence.
            continue
        inline_ref = extract_inline_reference(raw_line)
        if inline_ref is not None:
            if active is not None:
                active["reference"] = merge_reference(active["reference"], inline_ref)
            else:
                pending_reference = merge_reference(pending_reference, inline_ref)
            continue
        question = QUESTION_RE.match(raw_line)
        if question:
            flush_active()
            flush_note()
            question_text = question.group("text").strip()
            if question.group("short_label"):
                question_line = f"Q. {question_text}".strip()
            else:
                label = canonical_question_label(question.group("long_label"))
                question_line = f"{label} {question.group('number')}."
                if question_text:
                    question_line += f" {question_text}"
            active = {
                "chapter": current_chapter,
                "question_line": question_line,
                "body_lines": [],
                "input_pages": [],
                "reference": copy.deepcopy(pending_reference),
            }
            pending_reference = SourceReference()
            add_page(active["input_pages"])
            continue
        if CHAPTER_RE.match(raw_line):
            flush_active()
            flush_note()
            current_chapter = raw_line.strip()
            continue
        markdown_section = MARKDOWN_SECTION_RE.match(raw_line)
        if markdown_section:
            flush_active()
            flush_note()
            current_chapter = markdown_section.group("title").strip()
            continue
        bare_section = SECTION_HEADING_RE.match(raw_line)
        if bare_section and active is None:
            flush_note()
            number = compact_legal_token(bare_section.group("section"))
            title = bare_section.group("title").strip()
            current_chapter = f"Section {number}" + (f" — {title}" if title else "")
            continue
        if active is not None:
            active["body_lines"].append(raw_line)
        else:
            note_lines.append(raw_line)
            add_page(note_pages)

    flush_active()
    flush_note()
    return blocks


# -----------------------------------------------------------------------------
# Payloads and splitting
# -----------------------------------------------------------------------------

def render_payload(chapter: str, legal_reference: str, question: str, body: str, part: int = 1) -> str:
    """This is the ONLY content that should be embedded by the embedding script."""
    parts: list[str] = []
    if chapter and chapter != "Untitled section":
        parts.append(f"## {chapter}")
    if legal_reference:
        parts.append(f"Legal reference: {legal_reference}")
    if question:
        parts.append(question)
    if part > 1 and question:
        parts.append(continuation_label(question))
    if body.strip():
        parts.append(body.strip())
    return "\n\n".join(parts).strip()


def find_safe_cut(text: str, limit: int) -> int:
    if limit >= len(text):
        return len(text)
    minimum = max(1, int(limit * 0.60))
    candidates = [
        text.rfind("\n\n", minimum, limit + 1),
        text.rfind("\n", minimum, limit + 1),
        text.rfind("।", minimum, limit + 1),
        text.rfind(".", minimum, limit + 1),
        text.rfind("?", minimum, limit + 1),
        text.rfind("!", minimum, limit + 1),
        text.rfind(";", minimum, limit + 1),
        text.rfind(" ", minimum, limit + 1),
    ]
    cut = max(candidates)
    if cut <= 0:
        return limit
    if text.startswith("\n\n", cut):
        return min(cut + 2, len(text))
    if text[cut] in "\n।.?!; ":
        return min(cut + 1, len(text))
    return min(cut, len(text))


def split_long_text_by_tokens(text: str, limit: int, counter: TokenCounter) -> list[str]:
    text = text.strip()
    if not text:
        return [""]
    if counter.count(text) <= limit:
        return [text]
    pieces: list[str] = []
    remaining = text
    while remaining:
        if counter.count(remaining) <= limit:
            pieces.append(remaining.strip())
            break
        low, high, best = 1, len(remaining), 1
        while low <= high:
            mid = (low + high) // 2
            if counter.count(remaining[:mid]) <= limit:
                best, low = mid, mid + 1
            else:
                high = mid - 1
        cut = find_safe_cut(remaining, best)
        piece = remaining[:cut].strip()
        if not piece:
            cut = max(1, best)
            piece = remaining[:cut].strip()
        pieces.append(piece)
        remaining = remaining[cut:].lstrip()
    return pieces


def split_body_by_tokens(text: str, limit: int, counter: TokenCounter) -> list[str]:
    text = text.strip()
    if not text:
        return [""]
    if counter.count(text) <= limit:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if counter.count(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        if counter.count(paragraph) <= limit:
            current = paragraph
        else:
            pieces.extend(split_long_text_by_tokens(paragraph, limit, counter))
    if current:
        pieces.append(current)
    return pieces or [""]


def split_block(block: LegalBlock, max_tokens: int, counter: TokenCounter) -> list[OutputChunk]:
    ref = block.source_reference
    full = render_payload(block.chapter, ref.legal_reference, block.question_line, block.body, 1)
    if counter.count(full) <= max_tokens:
        return [OutputChunk(
            index=0, chapter=block.chapter, question_line=block.question_line, body=block.body,
            input_pages=block.input_pages, source_reference=copy.deepcopy(ref),
            source_block_ordinal=block.ordinal, part=1, parts_in_block=1,
            kind=block.kind, has_answer=block.has_answer, content_tokens=counter.count(full),
        )]
    first_prefix = render_payload(block.chapter, ref.legal_reference, block.question_line, "", 1)
    continued_prefix = render_payload(block.chapter, ref.legal_reference, block.question_line, "", 2)
    first_budget = max(32, max_tokens - counter.count(first_prefix) - 4)
    continued_budget = max(32, max_tokens - counter.count(continued_prefix) - 4)
    raw_parts = split_body_by_tokens(block.body, first_budget, counter)
    final_parts: list[str] = []
    for part_number, body in enumerate(raw_parts, 1):
        budget = first_budget if part_number == 1 else continued_budget
        if counter.count(body) <= budget:
            final_parts.append(body)
        else:
            final_parts.extend(split_body_by_tokens(body, budget, counter))
    result: list[OutputChunk] = []
    for part_number, body in enumerate(final_parts, 1):
        payload = render_payload(block.chapter, ref.legal_reference, block.question_line, body, part_number)
        result.append(OutputChunk(
            index=0, chapter=block.chapter, question_line=block.question_line, body=body,
            input_pages=block.input_pages, source_reference=copy.deepcopy(ref),
            source_block_ordinal=block.ordinal, part=part_number, parts_in_block=len(final_parts),
            kind=block.kind, has_answer=block.has_answer, content_tokens=counter.count(payload),
        ))
    return result


def build_chunks(blocks: list[LegalBlock], max_tokens: int, counter: TokenCounter) -> list[OutputChunk]:
    chunks: list[OutputChunk] = []
    for block in blocks:
        chunks.extend(split_block(block, max_tokens, counter))
    for index, chunk in enumerate(chunks, 1):
        chunk.index = index
    return chunks


def render_chunk_file(document_name: str, source_name: str, chunk: OutputChunk) -> str:
    """Headers are metadata. Your embeddings script must embed only after --- ."""
    ref = chunk.source_reference
    payload = render_payload(chunk.chapter, ref.legal_reference, chunk.question_line, chunk.body, chunk.part)
    question = chunk.question_line or "(section note)"
    return (
        f"# RTI Legal Chunk {chunk.index}\n"
        f"Document: {document_name}\n"
        f"Input source: {source_name}\n"
        f"Input pages: {format_pages(chunk.input_pages)}\n"
        f"Chapter: {chunk.chapter}\n"
        f"Question: {question}\n"
        f"Part: {chunk.part}/{chunk.parts_in_block}\n"
        f"Kind: {chunk.kind}\n"
        f"Has answer: {'yes' if chunk.has_answer else 'no'}\n"
        f"Content tokens: {chunk.content_tokens}\n"
        f"Original source book: {ref.source_book or 'Unknown'}\n"
        f"Source type: {ref.source_type}\n"
        f"Legal reference: {ref.legal_reference or 'Unknown'}\n"
        f"Book pages: {format_pages(ref.book_pages)}\n"
        f"Source PDF pages: {format_pages(ref.pdf_pages)}\n"
        f"Citation: {ref.citation_label or 'Unknown'}\n"
        "\n---\n\n"
        f"{payload}\n"
    )


# -----------------------------------------------------------------------------
# Validation and output
# -----------------------------------------------------------------------------

def remove_previous_outputs(output_dir: Path, doc_name: str) -> None:
    patterns = [f"{doc_name}_rti_chunk_*.txt", f"{doc_name}_rti_chunks_metadata.json"]
    removed = 0
    for pattern in patterns:
        for path in output_dir.glob(pattern):
            path.unlink()
            removed += 1
    if removed:
        logger.info("  Removed %d previous RTI chunk output file(s)", removed)


def validate_blocks(blocks: list[LegalBlock], strict: bool) -> None:
    legal = [block for block in blocks if block.kind == "faq"]
    no_answer = [b for b in legal if not b.has_answer]
    no_book = [b for b in legal if not b.source_reference.source_book]
    no_ref = [b for b in legal if not b.source_reference.legal_reference]
    no_book_pages = [b for b in legal if not b.source_reference.book_pages]
    no_pdf_pages = [b for b in legal if not b.source_reference.pdf_pages]
    if no_answer:
        logger.warning("%d legal Q&A block(s) lack an Answer/उत्तर marker.", len(no_answer))
    if no_book:
        logger.warning("%d legal Q&A block(s) lack source_book metadata.", len(no_book))
    if no_ref:
        logger.warning("%d legal Q&A block(s) lack legal_reference metadata.", len(no_ref))
    if no_book_pages:
        logger.warning("%d legal Q&A block(s) lack printed book-page metadata.", len(no_book_pages))
    if no_pdf_pages:
        logger.warning("%d legal Q&A block(s) lack PDF viewer-page metadata.", len(no_pdf_pages))
    if strict:
        invalid = [b for b in legal if not (b.source_reference.source_book and b.source_reference.legal_reference and b.source_reference.book_pages)]
        if invalid:
            sample = "\n".join(
                f"  - {b.question_line} | ref={b.source_reference.legal_reference or 'missing'} | pages={format_pages(b.source_reference.book_pages)}"
                for b in invalid[:10]
            )
            raise ValueError(
                f"{len(invalid)} legal Q&A block(s) miss mandatory source_book, legal_reference, or book_pages metadata:\n{sample}"
            )


def chunk_document(
    input_file: Path,
    output_dir: Path,
    counter: TokenCounter,
    max_tokens: int,
    manifest: SourceManifest,
    cli_source_config: dict,
    book_pdf_offset: Optional[int],
    document_name: str,
    include_section_notes: bool,
    strict_citations: bool,
    clean_output: bool,
) -> int:
    if not input_file.exists():
        raise FileNotFoundError(f"Input Markdown not found: {input_file}")
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_name = input_file.stem
    if clean_output:
        remove_previous_outputs(output_dir, doc_name)
    blocks = parse_legal_qa_markdown(
        input_file.read_text(encoding="utf-8"),
        document_name=document_name,
        manifest=manifest,
        cli_source_config=cli_source_config,
        book_pdf_offset=book_pdf_offset,
        include_section_notes=include_section_notes,
    )
    legal_count = sum(b.kind == "faq" for b in blocks)
    note_count = sum(b.kind == "section_note" for b in blocks)
    logger.info("Processing: %s", input_file)
    logger.info("  Parsed %d legal Q&A block(s); %d section-note block(s)", legal_count, note_count)
    if legal_count == 0:
        raise ValueError("No legal Q&A detected. Expected Q., Q:, Question 1., or प्रश्न 1. lines.")
    validate_blocks(blocks, strict_citations)
    chunks = build_chunks(blocks, max_tokens, counter)
    for chunk in chunks:
        destination = output_dir / f"{doc_name}_rti_chunk_{chunk.index:03d}.txt"
        destination.write_text(render_chunk_file(document_name, input_file.name, chunk), encoding="utf-8")
    metadata = {
        "document": input_file.name,
        "document_name": document_name,
        "source_path": str(input_file),
        "chunking_method": "rti_legal_qa_rule_based",
        "key_guarantees": {
            "supports_Q_dot_and_Q_colon": True,
            "supports_hindi_and_english_questions": True,
            "chapter_detection": "Markdown headings and plain Chapter headings",
            "legal_reference_inference": "chapter + question only; answer body excluded",
            "section_notes_indexed": include_section_notes,
            "embedding_payload_excludes_headers": True,
        },
        "citation_contract": {
            "source_book": "Original PDF/book shown by the Web UI",
            "legal_reference": "Section, subsection, or rule",
            "book_pages": "Printed pages inside the source book",
            "pdf_pages": "PDF viewer page numbers",
            "citation_label": "Single UI citation label",
        },
        "max_content_tokens": max_tokens,
        "tokenizer_model": counter.model if counter.tokenizer is not None else None,
        "token_count_mode": "tokenizer" if counter.tokenizer is not None else "approximate",
        "source_legal_qa_blocks": legal_count,
        "source_section_notes": note_count,
        "total_chunks": len(chunks),
        "chunks": [
            {
                "index": c.index,
                "filename": f"{doc_name}_rti_chunk_{c.index:03d}.txt",
                "chapter": c.chapter,
                "question": c.question_line,
                "input_pages": c.input_pages,
                "input_page_range": format_pages(c.input_pages),
                "source_block_ordinal": c.source_block_ordinal,
                "part": c.part,
                "parts_in_block": c.parts_in_block,
                "kind": c.kind,
                "has_answer": c.has_answer,
                "content_tokens": c.content_tokens,
                "source_reference": asdict(c.source_reference),
                "book_page_range": format_pages(c.source_reference.book_pages),
                "pdf_page_range": format_pages(c.source_reference.pdf_pages),
            }
            for c in chunks
        ],
    }
    metadata_file = output_dir / f"{doc_name}_rti_chunks_metadata.json"
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("  Saved %d legal chunk(s) to: %s", len(chunks), output_dir)
    logger.info("  Metadata: %s", metadata_file)
    return len(chunks)


def iter_input_documents(input_path: Path, document: Optional[str]) -> Iterable[tuple[Path, str]]:
    """Support a direct file, a folder containing structured.md, or stage2_output."""
    if input_path.is_file():
        yield input_path, input_path.parent.name or input_path.stem
        return
    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")
    direct = input_path / "structured.md"
    if direct.exists():
        yield direct, input_path.name
        return
    if document:
        folder = input_path / document
        structured = folder / "structured.md"
        if not structured.exists():
            available = sorted(c.name for c in input_path.iterdir() if c.is_dir() and (c / "structured.md").exists())
            raise FileNotFoundError(
                f"Document folder not found or structured.md missing: {folder}\nAvailable folders: {', '.join(available) if available else '(none)'}"
            )
        yield structured, folder.name
        return
    for folder in sorted(input_path.iterdir()):
        structured = folder / "structured.md"
        if folder.is_dir() and structured.exists():
            yield structured, folder.name


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    fg_dir = script_dir.parent
    parser = argparse.ArgumentParser(description="RTI legal Q&A chunker with source citations")
    parser.add_argument("--input", "-i", type=str, default=str(fg_dir / "01_preprocessing" / "stage2_output"), help="Direct Markdown file, document folder, or stage2_output folder")
    parser.add_argument("--output", "-o", type=str, default=str(script_dir / "output"), help="Output directory")
    parser.add_argument("--document", "-d", type=str, default=None, help="Document folder if --input is stage2_output")
    parser.add_argument("--model", "-m", type=str, default="BAAI/bge-m3", help="Tokenizer for token counting")
    parser.add_argument("--max-tokens", type=int, default=512, help="Maximum embedding payload tokens per chunk")
    parser.add_argument("--no-tokenizer", action="store_true", help="Use approximate Unicode token counting")
    parser.add_argument("--source-book", type=str, default="", help="Default original book filename, e.g. rti-rule-book.pdf")
    parser.add_argument("--source-type", type=str, default="general", help="Default source type, e.g. rti_rule_book")
    parser.add_argument("--legal-reference", type=str, default="", help="Fallback legal reference")
    parser.add_argument("--book-pages", type=str, default="", help="Fallback printed book pages, e.g. 33-35")
    parser.add_argument("--pdf-pages", type=str, default="", help="Fallback source PDF viewer pages")
    parser.add_argument("--book-pdf-offset", type=int, default=None, help="Viewer page minus printed book page; supplied RTI book uses 12")
    parser.add_argument("--source-manifest", type=str, default=None, help="JSON manifest with exact per-section citation rules")
    parser.add_argument("--include-section-notes", action="store_true", help="Index non-Q&A text; off by default to avoid large section_note chunks")
    parser.add_argument("--strict-citations", action="store_true", help="Fail if any legal Q&A lacks source_book, legal_reference, or book_pages")
    parser.add_argument("--clean-output", action="store_true", help="Delete prior *_rti_chunk_*.txt output first")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_tokens < 64:
        logger.error("--max-tokens must be at least 64.")
        return 2
    input_path = Path(args.input).expanduser()
    output_root = Path(args.output).expanduser()
    manifest_path = Path(args.source_manifest).expanduser() if args.source_manifest else None
    manifest = SourceManifest.load(manifest_path)
    cli_source_config = {
        "source_book": args.source_book,
        "source_type": args.source_type,
        "legal_reference": args.legal_reference,
        "book_pages": args.book_pages,
        "pdf_pages": args.pdf_pages,
    }
    logger.info("=" * 80)
    logger.info("Stage 2 -> Stage 3: RTI Legal Q&A Chunking")
    logger.info("=" * 80)
    logger.info("Input: %s", input_path)
    logger.info("Output: %s", output_root)
    logger.info("Default source book: %s", args.source_book or "(manifest/inline source)")
    logger.info("Book PDF offset: %s", args.book_pdf_offset if args.book_pdf_offset is not None else "(none)")
    logger.info("Max payload tokens: %d", args.max_tokens)
    logger.info("Strict citations: %s", args.strict_citations)
    logger.info("=" * 80)
    try:
        counter = TokenCounter(args.model, use_tokenizer=not args.no_tokenizer)
        docs = list(iter_input_documents(input_path, args.document))
        if not docs:
            logger.warning("No structured.md files found under: %s", input_path)
            return 0
        total = 0
        for input_file, doc_name in docs:
            total += chunk_document(
                input_file=input_file,
                output_dir=output_root / doc_name,
                counter=counter,
                max_tokens=args.max_tokens,
                manifest=manifest,
                cli_source_config=cli_source_config,
                book_pdf_offset=args.book_pdf_offset,
                document_name=doc_name,
                include_section_notes=args.include_section_notes,
                strict_citations=args.strict_citations,
                clean_output=args.clean_output,
            )
        logger.info("=" * 80)
        logger.info("Complete: processed %d document(s), created %d chunk(s)", len(docs), total)
        logger.info("=" * 80)
        return 0
    except Exception as exc:
        logger.error("RTI legal chunking failed: %s", exc)
        logger.debug("Traceback details", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
