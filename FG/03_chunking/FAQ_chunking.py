#!/usr/bin/env python3
r"""
Bilingual FAQ-aware chunker for Stage 2 OCR Markdown.

Purpose
-------
This script creates structure-based retrieval chunks for Hindi and English FAQ
documents. It keeps each Question + Answer + related bullets/paragraphs together
until the next question, a major Markdown section heading, or document end.

Supported FAQ forms
-------------------
Hindi:
    प्रश्न 1. क्या जानकारी मांगी जा सकती है?
    उत्तरः ...

English:
    Question 1. What information may be requested?
    Answer: ...

The script intentionally does NOT use Docling DocumentConverter or
HybridChunker. It reads the existing structured.md directly so the parser does
not lose or detach answer text during Markdown-to-document conversion.

Examples
--------
# Chunk one Hindi or English document folder under stage2_output
python FAQ_chunking_bilingual.py --document faq_hindi

# Chunk a direct Markdown file
python FAQ_chunking_bilingual.py `
  --input ".\faq_english\structured.md" `
  --output ".\output_english" `
  --max-tokens 512 `
  --clean-output

# Chunk every document folder under stage2_output
python FAQ_chunking_bilingual.py `
  --input "..\01_preprocessing\stage2_output" `
  --output ".\output" `
  --max-tokens 512 `
  --clean-output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# Matches both Hindi and English FAQ question headings/paragraphs.
# Examples:
#   प्रश्न 1. क्या जानकारी मांगी जा सकती है?
#   ### प्रश्न २ : आवेदन कैसे करें?
#   Question 1. What information may be requested?
#   ## Question 2: How should an application be made?
QUESTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<label>प्रश्न|प्रश्‍न|question)\s*"
    r"(?P<number>[0-9०-९]+)\s*[.।:：]?\s*"
    r"(?P<text>.*?)\s*$",
    re.IGNORECASE | re.UNICODE,
)
# Snapshot/PDF FAQ format.
# Examples:
#   Q007. Where do I find the "User Registration" button?
#   Q008: What happens after I submit the registration form?
#   ### Q009. What is a Second Appeal application?
#   **Q010. How do I start a Second Appeal application?**
SNAPSHOT_QUESTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?P<label>Q)\s*[-._]?\s*"
    r"(?P<number>\d{1,6})\s*[.।:：)\-–]\s*"
    r"(?P<text>.+?)\s*(?:\*\*)?\s*$",
    re.IGNORECASE | re.UNICODE,
)

# Ignore the repeated document header shown on PDF/snapshot pages.
SNAPSHOT_RUNNING_HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?:RTI\s+PORTAL\s+)?USER\s+MANUAL\s*[-–—:]\s*DETAILED\s+FAQ"
    r"\s*(?:\*\*)?\s*$",
    re.IGNORECASE | re.UNICODE,
)

# Detect Hindi and English answer markers. The marker remains in chunk content.
# Examples:
#   उत्तरः ...
#   उत्तर: ...
#   उत्तर:- ...
#   Answer: ...
#   **Answer:** ...
ANSWER_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?:उत्तर|answer)\s*(?:\*\*)?\s*[:ः：-]",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)

# Treat only H1/H2 headings as major document-section boundaries.
# Question headings are tested before this expression, so "## Question 1..."
# remains a FAQ question rather than becoming a section heading.
MAJOR_SECTION_RE = re.compile(r"^\s*#{1,2}(?!#)\s+(.+?)\s*$", re.UNICODE)

# Optional source markers inserted by the preprocessing stage.
PAGE_MARKER_RE = re.compile(
    r"^\s*<!--\s*Page\s+(\d+)\s*-->\s*$",
    re.IGNORECASE,
)


@dataclass
class FAQBlock:
    """A source segment that should remain intact unless it exceeds max_tokens."""

    section: str
    question_line: str
    body: str
    pages: list[int] = field(default_factory=list)
    ordinal: int = 0
    kind: str = "faq"  # "faq" or "section_note"
    question_style: str = "standard"  # "standard" or "snapshot"

    @property
    def has_answer(self) -> bool:
        # Snapshot FAQ documents usually do not write "Answer:" explicitly.
        # Their paragraph(s) after Q001/Q002 are treated as the answer.
        if self.question_style == "snapshot":
            return bool(self.body.strip())

        return bool(ANSWER_RE.search(self.body))

@dataclass
class OutputChunk:
    """A persisted retrieval chunk."""

    index: int
    section: str
    question_line: str
    body: str
    pages: list[int]
    source_block_ordinal: int
    part: int
    parts_in_block: int
    kind: str
    has_answer: bool
    content_tokens: int = 0


class TokenCounter:
    """
    Count tokens with the same Hugging Face tokenizer used by the embedding model.

    If transformers/the model is not available, a Unicode-aware approximate
    counter is used so parsing can still run. Use the actual tokenizer for
    production embeddings whenever possible.
    """

    def __init__(self, model: Optional[str], use_tokenizer: bool = True) -> None:
        self.model = model
        self.tokenizer = None

        if not use_tokenizer or not model:
            logger.warning("Tokenizer disabled; using approximate token counts.")
            return

        try:
            from transformers import AutoTokenizer

            logger.info("Loading tokenizer: %s", model)
            self.tokenizer = AutoTokenizer.from_pretrained(model)
        except Exception as exc:
            logger.warning(
                "Could not load tokenizer '%s': %s. Using approximate token counts.",
                model,
                exc,
            )

    def count(self, text: str) -> int:
        if not text:
            return 0

        if self.tokenizer is not None:
            return len(self.tokenizer.encode(text, add_special_tokens=False))

        # Conservative fallback that works for both English and Devanagari text.
        return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def normalize_lines(lines: Iterable[str]) -> str:
    """Remove only leading/trailing empty lines and preserve internal layout."""
    values = list(lines)

    while values and not values[0].strip():
        values.pop(0)

    while values and not values[-1].strip():
        values.pop()

    return "\n".join(values)


def unique_sorted_pages(pages: Iterable[int]) -> list[int]:
    """Remove duplicates and return valid page numbers in ascending order."""
    return sorted({page for page in pages if isinstance(page, int) and page > 0})


def format_pages(pages: Iterable[int]) -> str:
    """Render exact source pages as compact ranges, for example: 1-3,5."""
    values = unique_sorted_pages(pages)
    if not values:
        return "Unknown"

    runs: list[str] = []
    start = previous = values[0]

    for page in values[1:]:
        if page == previous + 1:
            previous = page
            continue

        runs.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page

    runs.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(runs)


def canonical_question_label(label: str) -> str:
    """Normalize a detected question label while preserving the document language."""
    return "Question" if label.casefold() == "question" else "प्रश्न"


def is_english_question(question_line: str) -> bool:
    """Return True when the FAQ question has an English Question label."""
    return question_line.strip().casefold().startswith("question")


def continuation_label(question_line: str) -> str:
    """Use an English or Hindi continuation marker based on the question label."""
    if is_english_question(question_line):
        return "**Answer continued:**"
    return "**उत्तर जारी है:**"

def detect_question_line(raw_line: str) -> tuple[Optional[str], Optional[re.Match]]:
    """
    Detect either the existing Hindi/English FAQ format or snapshot Q001 format.

    Returns:
        ("standard", match) for Question 1 / प्रश्न 1
        ("snapshot", match) for Q001 / Q002
        (None, None) when the line is not a question
    """
    standard_match = QUESTION_RE.match(raw_line)
    if standard_match:
        return "standard", standard_match

    snapshot_match = SNAPSHOT_QUESTION_RE.match(raw_line)
    if snapshot_match:
        return "snapshot", snapshot_match

    return None, None

def parse_faq_markdown(markdown_text: str) -> list[FAQBlock]:
    """
    Parse structured.md directly, without a generic document converter.

    Parsing rules:
    - Start a FAQ block at `प्रश्न N` or `Question N`.
    - Include every following line: Answer markers, bullets, forms, examples,
      and page continuations.
    - End only at the next question, next major H1/H2 section, or document end.
    - Keep non-FAQ text as a `section_note` block so no content is silently lost.
    - Treat page comments as metadata; do not write them into chunk payloads.
    """
    blocks: list[FAQBlock] = []

    current_section = "Untitled section"
    current_page: Optional[int] = None

    active_question: Optional[dict] = None
    note_lines: list[str] = []
    note_pages: list[int] = []

    def add_current_page(page_list: list[int]) -> None:
        if current_page is not None and current_page not in page_list:
            page_list.append(current_page)

    def flush_note() -> None:
        nonlocal note_lines, note_pages

        note_text = normalize_lines(note_lines)
        if note_text:
            blocks.append(
                FAQBlock(
                    section=current_section,
                    question_line="",
                    body=note_text,
                    pages=unique_sorted_pages(note_pages),
                    ordinal=len(blocks) + 1,
                    kind="section_note",
                )
            )

        note_lines = []
        note_pages = []

    def flush_question() -> None:
        nonlocal active_question

        if active_question is None:
            return

        body = normalize_lines(active_question["body_lines"])
        blocks.append(
            FAQBlock(
                section=active_question["section"],
                question_line=active_question["question_line"],
                body=body,
                pages=unique_sorted_pages(active_question["pages"]),
                ordinal=len(blocks) + 1,
                kind="faq",
                question_style=active_question["question_style"],
            )
        )
        active_question = None

    for raw_line in markdown_text.splitlines():
        page_match = PAGE_MARKER_RE.match(raw_line)
        if page_match:
            current_page = int(page_match.group(1))
            if active_question is not None:
                add_current_page(active_question["pages"])
            else:
                add_current_page(note_pages)
            continue

        question_style, question_match = detect_question_line(raw_line)

        if question_match:
            # A question starts a new retrieval unit, closing the prior one.
            flush_question()
            flush_note()

            question_no = question_match.group("number")
            question_text = question_match.group("text").strip()

            if question_style == "snapshot":
                # Keep the original snapshot style, including leading zeroes: Q007.
                question_line = f"Q{question_no}."
            else:
                question_label = canonical_question_label(question_match.group("label"))
                question_line = f"{question_label} {question_no}."

            if question_text:
                question_line += f" {question_text}"

            active_question = {
                "section": current_section,
                "question_line": question_line,
                "body_lines": [],
                "pages": [],
                "question_style": question_style,
            }
            add_current_page(active_question["pages"])
            continue

        # PDF snapshots may repeat this document title on every page.
        # It must not close the active question and create a broken chunk.
        if SNAPSHOT_RUNNING_HEADER_RE.match(raw_line):
            continue


        section_match = MAJOR_SECTION_RE.match(raw_line)
        if section_match:
            # A major section boundary ends the active Q/A block.
            flush_question()
            flush_note()
            current_section = section_match.group(1).strip()
            continue

        if active_question is not None:
            active_question["body_lines"].append(raw_line)
        else:
            note_lines.append(raw_line)
            add_current_page(note_pages)

    flush_question()
    flush_note()

    return blocks


def render_content(section: str, question_line: str, body: str, part: int = 1) -> str:
    """
    Build the text embedded and stored in the vector database.

    Every continuation repeats the original section and question, so a retrieved
    later part of a large answer is understandable without the first part.
    """
    elements: list[str] = []

    if section:
        elements.append(f"## {section}")

    if question_line:
        elements.append(question_line)

    if part > 1 and question_line:
        elements.append(continuation_label(question_line))

    if body.strip():
        elements.append(body.strip())

    return "\n\n".join(elements).strip()


def find_safe_cut(text: str, rough_limit: int) -> int:
    """
    Choose a sentence, paragraph, newline, or word boundary near rough_limit.

    The caller guarantees rough_limit falls inside text.
    """
    if rough_limit >= len(text):
        return len(text)

    minimum = max(1, int(rough_limit * 0.60))
    candidates = [
        text.rfind("\n\n", minimum, rough_limit + 1),
        text.rfind("\n", minimum, rough_limit + 1),
        text.rfind("।", minimum, rough_limit + 1),
        text.rfind(".", minimum, rough_limit + 1),
        text.rfind("?", minimum, rough_limit + 1),
        text.rfind("!", minimum, rough_limit + 1),
        text.rfind(";", minimum, rough_limit + 1),
        text.rfind(" ", minimum, rough_limit + 1),
    ]
    cut = max(candidates)

    if cut <= 0:
        cut = rough_limit
    elif text.startswith("\n\n", cut):
        cut += 2
    elif text[cut] in "\n।.?!; ":
        cut += 1

    return min(cut, len(text))


def split_long_text_by_tokens(text: str, token_limit: int, counter: TokenCounter) -> list[str]:
    """
    Split an oversized paragraph while preserving all characters.

    This is a fallback only. Normal Question + Answer blocks are kept whole.
    """
    text = text.strip()
    if not text:
        return [""]

    if counter.count(text) <= token_limit:
        return [text]

    pieces: list[str] = []
    remaining = text

    while remaining:
        if counter.count(remaining) <= token_limit:
            pieces.append(remaining.strip())
            break

        # Find the largest character prefix that fits the token budget.
        low, high = 1, len(remaining)
        best = 1

        while low <= high:
            mid = (low + high) // 2
            candidate = remaining[:mid]

            if counter.count(candidate) <= token_limit:
                best = mid
                low = mid + 1
            else:
                high = mid - 1

        cut = find_safe_cut(remaining, best)
        piece = remaining[:cut].strip()

        # Guard against an empty/infinite-loop edge case.
        if not piece:
            piece = remaining[: max(1, best)].strip()
            cut = max(1, best)

        pieces.append(piece)
        remaining = remaining[cut:].lstrip()

    return pieces


def split_body_by_tokens(text: str, token_limit: int, counter: TokenCounter) -> list[str]:
    """
    Split at paragraph boundaries first; split inside a paragraph only when needed.
    """
    text = text.strip()
    if not text:
        return [""]

    if counter.count(text) <= token_limit:
        return [text]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    pieces: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"

        if counter.count(candidate) <= token_limit:
            current = candidate
            continue

        if current:
            pieces.append(current)
            current = ""

        if counter.count(paragraph) <= token_limit:
            current = paragraph
        else:
            pieces.extend(split_long_text_by_tokens(paragraph, token_limit, counter))

    if current:
        pieces.append(current)

    return pieces or [""]


def split_block(
    block: FAQBlock,
    max_tokens: int,
    counter: TokenCounter,
    one_question_one_chunk: bool = False,
) -> list[OutputChunk]:
    """
    Preserve one FAQ block per chunk unless it exceeds max_tokens.

    Snapshot FAQ format Q001/Q002 is always preserved as one complete chunk.
    Standard Hindi/English FAQ blocks can also be preserved with
    --one-question-one-chunk.
    """
    original_content = render_content(
        block.section,
        block.question_line,
        block.body,
        part=1,
    )
    original_tokens = counter.count(original_content)

    keep_whole_question = (
        block.kind == "faq"
        and (
            block.question_style == "snapshot"
            or one_question_one_chunk
        )
    )

    if keep_whole_question:
        if original_tokens > max_tokens:
            logger.warning(
                "Keeping one question in one chunk despite token limit: %s | %d tokens > %d",
                block.question_line,
                original_tokens,
                max_tokens,
            )

        return [
            OutputChunk(
                index=0,
                section=block.section,
                question_line=block.question_line,
                body=block.body,
                pages=block.pages,
                source_block_ordinal=block.ordinal,
                part=1,
                parts_in_block=1,
                kind=block.kind,
                has_answer=block.has_answer,
                content_tokens=original_tokens,
            )
        ]

    if original_tokens <= max_tokens:
        return [
            OutputChunk(
                index=0,
                section=block.section,
                question_line=block.question_line,
                body=block.body,
                pages=block.pages,
                source_block_ordinal=block.ordinal,
                part=1,
                parts_in_block=1,
                kind=block.kind,
                has_answer=block.has_answer,
                content_tokens=original_tokens,
            )
        ]

    first_prefix = render_content(block.section, block.question_line, "", part=1)
    continuation_prefix = render_content(block.section, block.question_line, "", part=2)

    first_budget = max(32, max_tokens - counter.count(first_prefix) - 4)
    continuation_budget = max(32, max_tokens - counter.count(continuation_prefix) - 4)

    raw_parts = split_body_by_tokens(block.body, first_budget, counter)

    adjusted_parts: list[str] = []
    for part_index, part_body in enumerate(raw_parts, start=1):
        budget = first_budget if part_index == 1 else continuation_budget

        if counter.count(part_body) <= budget:
            adjusted_parts.append(part_body)
        else:
            adjusted_parts.extend(split_body_by_tokens(part_body, budget, counter))

    output: list[OutputChunk] = []
    parts_in_block = len(adjusted_parts)

    for part_index, part_body in enumerate(adjusted_parts, start=1):
        content = render_content(
            block.section,
            block.question_line,
            part_body,
            part=part_index,
        )
        output.append(
            OutputChunk(
                index=0,
                section=block.section,
                question_line=block.question_line,
                body=part_body,
                pages=block.pages,
                source_block_ordinal=block.ordinal,
                part=part_index,
                parts_in_block=parts_in_block,
                kind=block.kind,
                has_answer=block.has_answer,
                content_tokens=counter.count(content),
            )
        )

    return output

def build_chunks(
    blocks: list[FAQBlock],
    max_tokens: int,
    counter: TokenCounter,
    one_question_one_chunk: bool = False,
) -> list[OutputChunk]:
    """Create chunks while preserving Question + Answer boundaries."""
    chunks: list[OutputChunk] = []

    for block in blocks:
     chunks.extend(
        split_block(
            block,
            max_tokens=max_tokens,
            counter=counter,
            one_question_one_chunk=one_question_one_chunk,
        )
     )
    for index, chunk in enumerate(chunks, start=1):
        chunk.index = index

    return chunks


def render_output_file(document_name: str, source_name: str, chunk: OutputChunk) -> str:
    """Render one readable .txt chunk file."""
    question_for_metadata = chunk.question_line or "(section note)"

    payload = render_content(
        chunk.section,
        chunk.question_line,
        chunk.body,
        part=chunk.part,
    )

    return (
        f"# FAQ Chunk {chunk.index}\n"
        f"Document: {document_name}\n"
        f"Source: {source_name}\n"
        f"Pages: {format_pages(chunk.pages)}\n"
        f"Section: {chunk.section}\n"
        f"Question: {question_for_metadata}\n"
        f"Part: {chunk.part}/{chunk.parts_in_block}\n"
        f"Kind: {chunk.kind}\n"
        f"Has answer: {'yes' if chunk.has_answer else 'no'}\n"
        f"Content tokens: {chunk.content_tokens}\n"
        "\n---\n\n"
        f"{payload}\n"
    )


def remove_previous_faq_outputs(output_dir: Path, doc_name: str) -> None:
    """Delete only FAQ chunk outputs generated by this script for one document."""
    patterns = [
        f"{doc_name}_faq_chunk_*.txt",
        f"{doc_name}_faq_chunks_metadata.json",
    ]

    removed = 0
    for pattern in patterns:
        for path in output_dir.glob(pattern):
            path.unlink()
            removed += 1

    if removed:
        logger.info("  Removed %d previous FAQ output file(s)", removed)


def sha256_file(path: Path) -> str:
    """Return a SHA-256 hash for one source Markdown file."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict:
    """Load the FAQ chunking manifest, or return a new one."""
    if not path.exists():
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "last_updated": None,
            "documents": {},
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read chunking manifest %s: %s", path, exc)
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "last_updated": None,
            "documents": {},
        }

    data.setdefault("documents", {})
    return data


def save_manifest(path: Path, manifest: dict) -> None:
    """Save the FAQ chunking manifest atomically."""
    manifest["last_updated"] = datetime.now().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def manifest_key(input_md: Path) -> str:
    """Use a stable absolute path key for one structured.md source."""
    return str(input_md.resolve())


def output_files_exist(entry: dict) -> bool:
    """Return True only when every recorded output file still exists."""
    output_files = entry.get("output_files") or []
    return bool(output_files) and all(Path(path).exists() for path in output_files)


def should_skip_document(
    input_md: Path,
    output_dir: Path,
    manifest: dict,
    source_hash: str,
    force: bool,
) -> bool:
    """Check whether this source has already been chunked successfully."""
    if force:
        return False

    entry = manifest.get("documents", {}).get(manifest_key(input_md))
    if not entry:
        return False

    if entry.get("status") != "success":
        return False

    if entry.get("sha256") != source_hash:
        return False

    if Path(entry.get("output_dir", "")) != output_dir:
        return False

    if not output_files_exist(entry):
        return False

    return True


def mark_manifest_success(
    input_md: Path,
    output_dir: Path,
    document_name: str,
    source_hash: str,
    chunk_count: int,
    manifest: dict,
) -> None:
    """Record a successful chunking run for one structured.md source."""
    doc_name = input_md.stem
    output_files = sorted(
        str(path)
        for path in output_dir.glob(f"{doc_name}_faq_chunk_*.txt")
    )
    metadata_path = output_dir / f"{doc_name}_faq_chunks_metadata.json"
    if metadata_path.exists():
        output_files.append(str(metadata_path))

    manifest.setdefault("documents", {})[manifest_key(input_md)] = {
        "status": "success",
        "document_name": document_name,
        "source_path": str(input_md),
        "sha256": source_hash,
        "mtime": input_md.stat().st_mtime,
        "output_dir": str(output_dir),
        "output_files": output_files,
        "chunk_count": chunk_count,
        "processed_at": datetime.now().isoformat(),
    }


def chunk_document(
    input_md: Path,
    output_dir: Path,
    counter: TokenCounter,
    max_tokens: int,
    document_name: Optional[str] = None,
    clean_output: bool = False,
    one_question_one_chunk: bool = False,
) -> int:
    
    """Parse one bilingual structured.md and save FAQ-preserving chunks."""
    if not input_md.exists():
        raise FileNotFoundError(f"Input Markdown not found: {input_md}")

    output_dir.mkdir(parents=True, exist_ok=True)

    doc_name = input_md.stem
    display_name = document_name or input_md.parent.name or doc_name

    if clean_output:
        remove_previous_faq_outputs(output_dir, doc_name)

    markdown_text = input_md.read_text(encoding="utf-8")
    blocks = parse_faq_markdown(markdown_text)

    faq_blocks = [block for block in blocks if block.kind == "faq"]
    missing_answers = [block for block in faq_blocks if not block.has_answer]

    logger.info("Processing: %s", input_md)
    logger.info(
        "  Parsed %d FAQ block(s) and %d section note(s)",
        len(faq_blocks),
        len(blocks) - len(faq_blocks),
    )

    if missing_answers:
        logger.warning(
            "  %d FAQ block(s) have no detected Hindi/English answer marker: %s",
            len(missing_answers),
            ", ".join(block.question_line or "unknown" for block in missing_answers),
        )

    chunks = build_chunks(
        blocks,
        max_tokens=max_tokens,
        counter=counter,
        one_question_one_chunk=one_question_one_chunk,
    )

    for chunk in chunks:
        output_file = output_dir / f"{doc_name}_faq_chunk_{chunk.index:03d}.txt"
        output_file.write_text(
            render_output_file(display_name, input_md.name, chunk),
            encoding="utf-8",
        )

    metadata = {
        "document": input_md.name,
        "document_name": display_name,
        "source_path": str(input_md),
        "chunking_method": "bilingual_faq_rule_based",
        "supported_languages": ["Hindi", "English"],
        "rules": {
            "question_start": "Hindi: प्रश्न N; English: Question N",
            "answer_marker": "Hindi: उत्तरः/उत्तर:; English: Answer:",
            "boundary": "next FAQ question, next major H1/H2 heading, or document end",
            "answer_preserved": True,
            "page_tracking": "exact source page markers: <!-- Page N -->",
        },
        "max_content_tokens": max_tokens,
        "tokenizer_model": counter.model if counter.tokenizer is not None else None,
        "token_count_mode": "tokenizer" if counter.tokenizer is not None else "approximate",
        "source_faq_blocks": len(faq_blocks),
        "source_section_notes": len(blocks) - len(faq_blocks),
        "faq_blocks_without_answer_marker": [
            {
                "ordinal": block.ordinal,
                "section": block.section,
                "question": block.question_line,
                "pages": block.pages,
            }
            for block in missing_answers
        ],
        "total_chunks": len(chunks),
        "chunks": [
            {
                "index": chunk.index,
                "filename": f"{doc_name}_faq_chunk_{chunk.index:03d}.txt",
                "section": chunk.section,
                "question": chunk.question_line,
                "pages": chunk.pages,
                "page_range": format_pages(chunk.pages),
                "source_block_ordinal": chunk.source_block_ordinal,
                "part": chunk.part,
                "parts_in_block": chunk.parts_in_block,
                "kind": chunk.kind,
                "has_answer": chunk.has_answer,
                "content_tokens": chunk.content_tokens,
            }
            for chunk in chunks
        ],
    }

    metadata_path = output_dir / f"{doc_name}_faq_chunks_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("  Saved %d FAQ-preserving chunk(s) to: %s", len(chunks), output_dir)
    logger.info("  Metadata: %s", metadata_path)

    return len(chunks)


def iter_input_documents(input_path: Path, document: Optional[str]) -> Iterable[tuple[Path, str]]:
    """
    Yield (structured_md_path, document_name) pairs.

    Supported inputs:
    - direct Markdown file, usually structured.md
    - one document folder containing structured.md
    - stage2_output folder containing document subfolders
    """
    if input_path.is_file():
        yield input_path, input_path.parent.name or input_path.stem
        return

    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")

    direct_structured = input_path / "structured.md"
    if direct_structured.exists():
        yield direct_structured, input_path.name
        return

    if document:
        doc_dir = input_path / document
        structured_md = doc_dir / "structured.md"

        if not structured_md.exists():
            available = sorted(
                child.name
                for child in input_path.iterdir()
                if child.is_dir() and (child / "structured.md").exists()
            )
            available_text = ", ".join(available) if available else "(none)"
            raise FileNotFoundError(
                f"Document folder not found or structured.md missing: {doc_dir}\n"
                f"Available document folders: {available_text}"
            )

        yield structured_md, doc_dir.name
        return

    for doc_dir in sorted(input_path.iterdir()):
        if not doc_dir.is_dir():
            continue

        structured_md = doc_dir / "structured.md"
        if structured_md.exists():
            yield structured_md, doc_dir.name


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    fg_dir = script_dir.parent

    parser = argparse.ArgumentParser(
        description="Bilingual Hindi/English FAQ-aware chunking for structured.md"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=str(fg_dir / "01_preprocessing" / "stage2_output"),
        help="stage2_output folder, one document folder, or a direct Markdown file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(script_dir / "output"),
        help="Directory for output FAQ chunks",
    )
    parser.add_argument(
        "--document",
        "-d",
        type=str,
        default=None,
        help="Specific document folder name when --input is a stage2_output folder",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="BAAI/bge-m3",
        help="Tokenizer model used for token limits (default: BAAI/bge-m3)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="Maximum rendered-content tokens per chunk (default: 512)",
    )
    parser.add_argument(
        "--no-tokenizer",
        action="store_true",
        help="Do not load transformers; use approximate Unicode token counts",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Remove previous FAQ chunks generated for each processed source",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess even when the manifest says this structured.md is already chunked",
    )
    parser.add_argument(
        "--one-question-one-chunk",
        action="store_true",
        help=(
            "Keep every detected FAQ question and complete answer in one chunk, "
            "even when it exceeds --max-tokens. Snapshot Q001/Q002 format is "
            "always preserved as one chunk."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.max_tokens < 64:
        logger.error("--max-tokens must be at least 64.")
        return 2

    input_path = Path(args.input).expanduser()
    output_root = Path(args.output).expanduser()
    manifest_path = Path(__file__).resolve().parent / "faq_chunking_manifest.json"

    logger.info("=" * 80)
    logger.info("Stage 2 -> Stage 3: Bilingual FAQ-aware Chunking")
    logger.info("=" * 80)
    logger.info("Input:  %s", input_path)
    logger.info("Output: %s", output_root)
    logger.info("Manifest: %s", manifest_path)
    logger.info("Model:  %s", args.model if not args.no_tokenizer else "(disabled)")
    logger.info("Max content tokens per chunk: %s", args.max_tokens)
    logger.info("Force reprocess: %s", "yes" if args.force else "no")
    logger.info("=" * 80)

    try:
        manifest = load_manifest(manifest_path)
        documents = list(iter_input_documents(input_path, args.document))

        if not documents:
            logger.warning("No structured.md files found under: %s", input_path)
            return 0

        to_process: list[tuple[Path, str, str]] = []
        skipped_count = 0
        for structured_md, document_name in documents:
            document_output = output_root / document_name
            source_hash = sha256_file(structured_md)

            if should_skip_document(
                input_md=structured_md,
                output_dir=document_output,
                manifest=manifest,
                source_hash=source_hash,
                force=args.force,
            ):
                logger.info("[SKIP] FAQ chunks already current: %s", structured_md)
                skipped_count += 1
                continue

            to_process.append((structured_md, document_name, source_hash))

        if not to_process:
            logger.info("=" * 80)
            logger.info(
                "Complete: %d document(s) already current, 0 processed",
                skipped_count,
            )
            logger.info("=" * 80)
            return 0

        counter = TokenCounter(args.model, use_tokenizer=not args.no_tokenizer)

        total_chunks = 0
        processed_count = 0
        for structured_md, document_name, source_hash in to_process:
            document_output = output_root / document_name
            chunk_count = chunk_document(
                input_md=structured_md,
                output_dir=document_output,
                counter=counter,
                max_tokens=args.max_tokens,
                document_name=document_name,
                clean_output=args.clean_output,
                one_question_one_chunk=args.one_question_one_chunk,
            )
            total_chunks += chunk_count
            processed_count += 1
            mark_manifest_success(
                input_md=structured_md,
                output_dir=document_output,
                document_name=document_name,
                source_hash=source_hash,
                chunk_count=chunk_count,
                manifest=manifest,
            )
            save_manifest(manifest_path, manifest)

        logger.info("=" * 80)
        logger.info(
            "Complete: processed %d document(s), skipped %d current document(s), created %d chunk(s)",
            processed_count,
            skipped_count,
            total_chunks,
        )
        logger.info("=" * 80)
        return 0

    except Exception as exc:
        logger.error("FAQ chunking failed: %s", exc)
        logger.debug("Traceback details", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
