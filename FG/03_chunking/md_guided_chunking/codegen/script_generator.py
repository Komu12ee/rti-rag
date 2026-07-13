"""
Stage 2 - reusable script generation.

The pipeline still learns from the analysed sample document(s), but the
generated artifact is no longer a fixed dump of those sample chunks. It is a
standalone deterministic Markdown chunker that re-reads whatever file/folder
you pass at runtime, applies learned structural boundary hints, and writes
fresh chunk files.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from chunking.parent_child_builder import Chunk
from ingestion.markdown_loader import DocumentBlock
from llm.schemas import ChunkingDecision, DocumentProfile


SampleRecord = dict[str, Any]


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _slugify(value: str) -> str:
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_") or "chunker"


def _safe_script_stem(value: str) -> str:
    stem = _slugify(value)
    if stem.lower().endswith("_chunking"):
        stem = stem[:-9]
    return stem or "chunker"


def _block_span_size(
    start_block_id: str,
    end_block_id: str,
    blocks_by_id: dict[str, DocumentBlock],
    ordered_ids: list[str],
) -> tuple[int, int]:
    start_idx = ordered_ids.index(start_block_id)
    end_idx = ordered_ids.index(end_block_id)
    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx
    text_len = sum(len(blocks_by_id[bid].text) for bid in ordered_ids[start_idx:end_idx + 1])
    return text_len, end_idx - start_idx + 1


def _identifier_pattern(identifier: str | None) -> str | None:
    if not identifier:
        return None
    cleaned = identifier.strip()
    if re.fullmatch(r"\d+(\.\d+)*", cleaned):
        return r"^\s*\d+(\.\d+)*[\).]?\s+"
    if re.fullmatch(r"\d+(\.\d+)*(\([A-Za-z0-9]+\))+", cleaned):
        return r"^\s*\d+(\.\d+)*(\([A-Za-z0-9]+\))*[\).]?\s+"
    if re.fullmatch(r"[A-Za-z]", cleaned):
        return r"^\s*[A-Za-z][\).]\s+"
    if re.fullmatch(r"[IVXLCDM]+", cleaned, flags=re.IGNORECASE):
        return r"^\s*[IVXLCDM]+[\).]\s+"
    return None


def _learn_start_pattern(
    block: DocumentBlock,
    unit_type: str,
    identifier: str | None,
) -> str | None:
    from_identifier = _identifier_pattern(identifier)
    if from_identifier:
        return from_identifier

    first = _first_line(block.text)
    if not first:
        return None

    lowered = first.casefold()
    keyword_patterns = {
        "chapter": r"^\s*(chapter|\u0905\u0927\u094d\u092f\u093e\u092f)\b",
        "section": r"^\s*(section|sec\.?|\u0927\u093e\u0930\u093e)\b",
        "subsection": r"^\s*(sub[-\s]?section|\u0909\u092a\s*\u0927\u093e\u0930\u093e)\b",
        "rule": r"^\s*(rule|\u0928\u093f\u092f\u092e)\b",
        "subrule": r"^\s*(sub[-\s]?rule|\u0909\u092a\s*\u0928\u093f\u092f\u092e)\b",
        "part": r"^\s*(part|\u092d\u093e\u0917)\b",
        "clause": r"^\s*(clause|\u0916\u0902\u0921)\b",
        "schedule": r"^\s*(schedule|\u0905\u0928\u0941\u0938\u0942\u091a\u0940)\b",
        "annexure": r"^\s*(annexure|appendix|\u092a\u0930\u093f\u0936\u093f\u0937\u094d\u091f)\b",
        "form": r"^\s*(form|\u092a\u094d\u0930\u092a\u0924\u094d\u0930)\b",
        "notification": r"^\s*(notification|\u0905\u0927\u093f\u0938\u0942\u091a\u0928\u093e)\b",
        "circular": r"^\s*(circular|\u092a\u0930\u093f\u092a\u0924\u094d\u0930)\b",
        "government_order": r"^\s*(government\s+order|order|\u0906\u0926\u0947\u0936)\b",
    }
    if unit_type in keyword_patterns:
        english_token = keyword_patterns[unit_type].split("|", 1)[0].strip(r"^\s*(")
        if english_token and english_token.replace("\\s+", " ") in lowered:
            return keyword_patterns[unit_type]

    if re.match(r"^\s*\d+(\.\d+)*[\).]?\s+\S", first):
        return r"^\s*\d+(\.\d+)*[\).]?\s+"
    if re.match(r"^\s*[A-Za-z][\).]\s+\S", first):
        return r"^\s*[A-Za-z][\).]\s+"
    if re.match(r"^\s*\([A-Za-z0-9]+\)\s+\S", first):
        return r"^\s*\([A-Za-z0-9]+\)\s+"

    return None


def _sample_name(sample: SampleRecord) -> str:
    source_path = sample.get("source_path")
    if source_path:
        return str(source_path)
    return str(sample.get("source_filename") or sample.get("document_id") or "sample")


def _build_strategy(
    samples: list[SampleRecord],
    strategy_name: str,
    source_label: str,
) -> dict[str, Any]:
    heading_levels: set[int] = set()
    boundary_block_types: set[str] = set()
    boundary_patterns: set[str] = set()
    document_types: set[str] = set()
    languages: set[str] = set()
    unit_types: set[str] = set()
    chunk_char_counts: list[int] = []
    chunk_block_counts: list[int] = []

    for sample in samples:
        profile = sample.get("profile")
        if isinstance(profile, DocumentProfile):
            document_types.add(profile.document_type)
            languages.update(profile.languages or [])

        decision = sample.get("decision")
        blocks = sample.get("blocks") or []
        if not isinstance(decision, ChunkingDecision) or not blocks:
            continue

        ordered_ids = [b.block_id for b in blocks]
        blocks_by_id = {b.block_id: b for b in blocks}

        for unit in decision.units:
            unit_types.add(unit.unit_type)
            try:
                char_count, block_count = _block_span_size(
                    unit.start_block_id,
                    unit.end_block_id,
                    blocks_by_id,
                    ordered_ids,
                )
                if char_count > 0:
                    chunk_char_counts.append(char_count)
                    chunk_block_counts.append(block_count)
            except ValueError:
                pass

            start_block = blocks_by_id.get(unit.start_block_id)
            if not start_block:
                continue

            boundary_block_types.add(start_block.block_type)
            if start_block.block_type == "heading" and start_block.heading_level is not None:
                heading_levels.add(start_block.heading_level)

            pattern = _learn_start_pattern(start_block, unit.unit_type, unit.identifier)
            if pattern:
                boundary_patterns.add(pattern)

    target_chars = int(median(chunk_char_counts)) if chunk_char_counts else 3500
    max_chars = max(1800, min(9000, target_chars * 2))
    max_blocks = int(median(chunk_block_counts)) if chunk_block_counts else 18
    max_blocks = max(4, min(60, max_blocks * 2))

    return {
        "strategy_name": strategy_name,
        "source_label": source_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(samples),
        "sample_files": [_sample_name(sample) for sample in samples],
        "document_types": sorted(document_types) or ["other"],
        "languages": sorted(languages) or ["en"],
        "unit_types": sorted(unit_types) or ["heading_group", "other"],
        "heading_levels": sorted(heading_levels),
        "boundary_block_types": sorted(boundary_block_types),
        "boundary_patterns": sorted(boundary_patterns),
        "target_chars": max(800, min(6000, target_chars)),
        "max_chars": max_chars,
        "max_blocks_per_chunk": max_blocks,
    }


def generate_strategy_chunker_script(
    samples: list[SampleRecord],
    strategy_name: str,
    source_label: str,
) -> str:
    strategy = _build_strategy(samples, strategy_name=strategy_name, source_label=source_label)
    strategy_json = json.dumps(strategy, ensure_ascii=False, indent=4)
    display_source_label = source_label.replace("\\", "/")

    header = f'''"""
AUTO-GENERATED reusable Markdown chunker.

Strategy name: {strategy_name}
Learned from: {display_source_label}
Generated at: {strategy["generated_at"]}

This file was produced by md_guided_chunking. It does not call Ollama or any
LLM at runtime. It re-reads the Markdown file/folder you pass to it and applies
the learned boundary strategy deterministically.

Default:
    python {strategy_name}_chunking.py <input_path>

With explicit output:
    python {strategy_name}_chunking.py <input_path> --output chunk_output
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


STRATEGY = {strategy_json}

'''

    runtime = r'''
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+\S")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW_RE = re.compile(r".*\|.*")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_PAGE_COMMENT_RE = re.compile(r"^\s*<!--\s*page\s+\d+\s*-->\s*$", re.IGNORECASE)
_GENERIC_STRUCTURAL_RE = re.compile(
    r"^\s*("
    r"chapter|section|sec\.?|sub[-\s]?section|rule|sub[-\s]?rule|part|clause|"
    r"schedule|annexure|appendix|form|notification|circular|government\s+order|order|"
    r"\u0905\u0927\u094d\u092f\u093e\u092f|\u0927\u093e\u0930\u093e|"
    r"\u0909\u092a\s*\u0927\u093e\u0930\u093e|\u0928\u093f\u092f\u092e|"
    r"\u0909\u092a\s*\u0928\u093f\u092f\u092e|\u092d\u093e\u0917|"
    r"\u0916\u0902\u0921|\u0905\u0928\u0941\u0938\u0942\u091a\u0940|"
    r"\u092a\u0930\u093f\u0936\u093f\u0937\u094d\u091f|\u092a\u094d\u0930\u092a\u0924\u094d\u0930|"
    r"\u0905\u0927\u093f\u0938\u0942\u091a\u0928\u093e|\u092a\u0930\u093f\u092a\u0924\u094d\u0930|"
    r"\u0906\u0926\u0947\u0936"
    r")\b",
    re.IGNORECASE,
)
_NUMBERED_BOUNDARY_RE = re.compile(
    r"^\s*(\d+(\.\d+)*(\([A-Za-z0-9]+\))*[\).]?|[A-Za-z][\).]|\([A-Za-z0-9]+\))\s+\S"
)
_BOUNDARY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in STRATEGY.get("boundary_patterns", [])
]


@dataclass
class Block:
    block_id: str
    block_type: str
    text: str
    line_start: int
    line_end: int
    heading_level: Optional[int] = None


@dataclass
class RuntimeChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    unit_type: str
    title: Optional[str]
    source_path: str
    start_block_id: str
    end_block_id: str
    start_line: int
    end_line: int
    text: str


def _slugify(value: str) -> str:
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch.lower())
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_") or "document"


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _join_block_text(blocks: list[Block]) -> str:
    return "\n\n".join(block.text for block in blocks if block.text.strip()).strip()


def load_markdown_blocks(path: str | Path) -> list[Block]:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    blocks: list[Block] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"b{counter:04d}"

    def add_block(
        block_type: str,
        block_text: str,
        line_start: int,
        line_end: int,
        heading_level: Optional[int] = None,
    ) -> None:
        if block_text.strip():
            blocks.append(Block(
                block_id=next_id(),
                block_type=block_type,
                text=block_text.strip("\n"),
                line_start=line_start,
                line_end=line_end,
                heading_level=heading_level,
            ))

    i = 0
    n = len(lines)
    para_buffer: list[str] = []
    para_start: Optional[int] = None

    def flush_paragraph(end_line: int) -> None:
        nonlocal para_buffer, para_start
        if para_buffer:
            joined = "\n".join(para_buffer).strip()
            if joined:
                add_block("paragraph", joined, para_start if para_start is not None else end_line, end_line)
        para_buffer = []
        para_start = None

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        if stripped == "":
            flush_paragraph(i)
            i += 1
            continue

        fence_match = _FENCE_RE.match(raw)
        if fence_match:
            flush_paragraph(i - 1)
            fence_token = fence_match.group(1)
            start_line = i
            code_lines = [raw]
            i += 1
            while i < n and not lines[i].strip().startswith(fence_token):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                code_lines.append(lines[i])
                i += 1
            add_block("code_block", "\n".join(code_lines), start_line, i - 1)
            continue

        heading_match = _HEADING_RE.match(raw)
        if heading_match:
            flush_paragraph(i - 1)
            add_block(
                "heading",
                heading_match.group(2),
                i,
                i,
                heading_level=len(heading_match.group(1)),
            )
            i += 1
            continue

        if _HR_RE.match(raw):
            flush_paragraph(i - 1)
            add_block("hr", stripped, i, i)
            i += 1
            continue

        if _TABLE_ROW_RE.match(raw) and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1].strip()):
            flush_paragraph(i - 1)
            start_line = i
            table_lines = [raw, lines[i + 1]]
            i += 2
            while i < n and _TABLE_ROW_RE.match(lines[i]) and lines[i].strip() != "":
                table_lines.append(lines[i])
                i += 1
            add_block("table", "\n".join(table_lines), start_line, i - 1)
            continue

        if _BLOCKQUOTE_RE.match(raw):
            flush_paragraph(i - 1)
            start_line = i
            quote_lines = [raw]
            i += 1
            while i < n and _BLOCKQUOTE_RE.match(lines[i]):
                quote_lines.append(lines[i])
                i += 1
            add_block("blockquote", "\n".join(quote_lines), start_line, i - 1)
            continue

        if _LIST_RE.match(raw):
            flush_paragraph(i - 1)
            start_line = i
            list_lines = [raw]
            i += 1
            while i < n and lines[i].strip() != "" and (
                _LIST_RE.match(lines[i]) or lines[i].startswith((" ", "\t"))
            ):
                list_lines.append(lines[i])
                i += 1
            add_block("list_item", "\n".join(list_lines), start_line, i - 1)
            continue

        if para_start is None:
            para_start = i
        para_buffer.append(raw)
        i += 1

    flush_paragraph(n - 1)
    return blocks


def _matches_learned_pattern(block: Block) -> bool:
    first = _first_line(block.text)
    return bool(first and any(pattern.search(first) for pattern in _BOUNDARY_PATTERNS))


def _allow_numbered_boundaries() -> bool:
    unit_types = set(STRATEGY.get("unit_types", []))
    return bool(unit_types.intersection({"section", "subsection", "clause", "rule", "subrule", "part", "chapter"}))


def _is_boundary_block(block: Block, index: int) -> bool:
    if _PAGE_COMMENT_RE.match(block.text):
        return False

    if block.block_type == "heading":
        heading_levels = STRATEGY.get("heading_levels", [])
        return not heading_levels or block.heading_level in heading_levels

    if block.block_type == "table" and "table" in STRATEGY.get("boundary_block_types", []):
        return True

    first = _first_line(block.text)
    if not first:
        return False

    if _matches_learned_pattern(block):
        return True

    if _GENERIC_STRUCTURAL_RE.match(first):
        return True

    if _allow_numbered_boundaries() and block.block_type in {"paragraph", "list_item"}:
        return bool(_NUMBERED_BOUNDARY_RE.match(first))

    return index == 0


def _infer_unit_type(block: Block) -> str:
    first = _first_line(block.text)
    if block.block_type == "heading":
        return "heading_group"
    if block.block_type == "table":
        return "table"

    lowered = first.casefold()
    checks = [
        ("chapter", ("chapter", "\u0905\u0927\u094d\u092f\u093e\u092f")),
        ("section", ("section", "sec.", "\u0927\u093e\u0930\u093e")),
        ("rule", ("rule", "\u0928\u093f\u092f\u092e")),
        ("part", ("part", "\u092d\u093e\u0917")),
        ("schedule", ("schedule", "\u0905\u0928\u0941\u0938\u0942\u091a\u0940")),
        ("annexure", ("annexure", "appendix", "\u092a\u0930\u093f\u0936\u093f\u0937\u094d\u091f")),
        ("form", ("form", "\u092a\u094d\u0930\u092a\u0924\u094d\u0930")),
        ("notification", ("notification", "\u0905\u0927\u093f\u0938\u0942\u091a\u0928\u093e")),
        ("circular", ("circular", "\u092a\u0930\u093f\u092a\u0924\u094d\u0930")),
    ]
    for unit_type, tokens in checks:
        if any(token in lowered for token in tokens):
            return unit_type
    return "other"


def _title_for_span(blocks: list[Block]) -> Optional[str]:
    if not blocks:
        return None
    first = blocks[0]
    title = _first_line(first.text)
    if first.block_type == "heading" and title:
        return title
    if len(title) > 120:
        return title[:117].rstrip() + "..."
    return title or None


def _split_span(blocks: list[Block], start: int, end: int) -> list[tuple[int, int]]:
    max_chars = int(STRATEGY.get("max_chars", 7000))
    max_blocks = int(STRATEGY.get("max_blocks_per_chunk", 36))
    spans: list[tuple[int, int]] = []
    current_start = start
    current_chars = 0

    for idx in range(start, end):
        block_len = len(blocks[idx].text)
        block_count = idx - current_start
        if idx > current_start and (
            current_chars + block_len > max_chars or block_count >= max_blocks
        ):
            spans.append((current_start, idx))
            current_start = idx
            current_chars = 0
        current_chars += block_len

    if current_start < end:
        spans.append((current_start, end))
    return spans


def build_chunks_for_file(path: str | Path) -> list[RuntimeChunk]:
    source_path = Path(path)
    blocks = load_markdown_blocks(source_path)
    if not blocks:
        return []

    detected_starts = [
        idx for idx, block in enumerate(blocks)
        if idx > 0 and _is_boundary_block(block, idx)
    ]
    if detected_starts:
        starts = [0 if detected_starts[0] > 0 else detected_starts[0]] + detected_starts[1:]
    else:
        starts = [0]

    starts = sorted(set(starts))
    raw_spans: list[tuple[int, int]] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(blocks)
        if end > start:
            raw_spans.extend(_split_span(blocks, start, end))

    document_id = _slugify(source_path.stem)
    chunks: list[RuntimeChunk] = []
    for index, (start, end) in enumerate(raw_spans, start=1):
        span_blocks = blocks[start:end]
        text = _join_block_text(span_blocks)
        if not text:
            continue
        first_block = span_blocks[0]
        chunks.append(RuntimeChunk(
            chunk_id=f"{document_id}_chunk_{index:03d}",
            document_id=document_id,
            chunk_index=index,
            unit_type=_infer_unit_type(first_block),
            title=_title_for_span(span_blocks),
            source_path=str(source_path),
            start_block_id=span_blocks[0].block_id,
            end_block_id=span_blocks[-1].block_id,
            start_line=span_blocks[0].line_start,
            end_line=span_blocks[-1].line_end,
            text=text,
        ))
    return chunks


def _qdrant_points(chunks: list[RuntimeChunk]) -> list[dict]:
    return [
        {
            "id": chunk.chunk_id,
            "vector": None,
            "payload": {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "unit_type": chunk.unit_type,
                "title": chunk.title,
                "source_path": chunk.source_path,
                "start_block_id": chunk.start_block_id,
                "end_block_id": chunk.end_block_id,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "text": chunk.text,
            },
        }
        for chunk in chunks
    ]


def _markdown_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".md":
            raise SystemExit(f"Input file is not Markdown: {input_path}")
        return [input_path]
    if input_path.is_dir():
        return sorted(path for path in input_path.rglob("*.md") if path.is_file())
    raise SystemExit(f"Input path does not exist: {input_path}")


def _output_subdir(base_input: Path, md_file: Path, stem_counts: dict[str, int]) -> str:
    if stem_counts.get(md_file.stem, 0) <= 1:
        return _slugify(md_file.stem)
    try:
        relative = md_file.relative_to(base_input).with_suffix("")
        return _slugify("__".join(relative.parts))
    except ValueError:
        return _slugify(md_file.stem)


def write_chunk_files(
    input_path: Path,
    output_dir: Path,
) -> list[RuntimeChunk]:
    md_files = _markdown_files(input_path)
    if not md_files:
        raise SystemExit(f"No Markdown files found under: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    all_chunks: list[RuntimeChunk] = []

    if input_path.is_file():
        chunks = build_chunks_for_file(input_path)
        for chunk in chunks:
            chunk_path = output_dir / f"{chunk.document_id}_chunk_{chunk.chunk_index:03d}.txt"
            chunk_path.write_text(chunk.text, encoding="utf-8")
        all_chunks.extend(chunks)
        return all_chunks

    stem_counts: dict[str, int] = {}
    for md_file in md_files:
        stem_counts[md_file.stem] = stem_counts.get(md_file.stem, 0) + 1

    for md_file in md_files:
        chunks = build_chunks_for_file(md_file)
        doc_dir = output_dir / _output_subdir(input_path, md_file, stem_counts)
        doc_dir.mkdir(parents=True, exist_ok=True)
        for chunk in chunks:
            chunk_path = doc_dir / f"{chunk.document_id}_chunk_{chunk.chunk_index:03d}.txt"
            chunk_path.write_text(chunk.text, encoding="utf-8")
        all_chunks.extend(chunks)

    return all_chunks


def collect_chunks(input_path: Path) -> list[RuntimeChunk]:
    chunks: list[RuntimeChunk] = []
    for md_file in _markdown_files(input_path):
        chunks.extend(build_chunks_for_file(md_file))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", help="Markdown file or folder to chunk.")
    parser.add_argument(
        "--output",
        default=None,
        help="Directory for .txt chunk files. Defaults to ./chunk_output.",
    )
    parser.add_argument(
        "--emit",
        choices=["txt", "jsonl", "qdrant"],
        default="txt",
        help="txt writes UTF-8 chunk files; jsonl/qdrant emit to stdout.",
    )
    parser.add_argument(
        "--leaf-only",
        action="store_true",
        help="Accepted for compatibility; this strategy chunker emits flat runtime chunks.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path).resolve()

    if args.emit == "txt":
        output_dir = Path(args.output).resolve() if args.output else Path.cwd() / "chunk_output"
        chunks = write_chunk_files(input_path, output_dir)
        print(f"Wrote {len(chunks)} chunk files to {output_dir}")
        return

    chunks = collect_chunks(input_path)
    if args.emit == "jsonl":
        for chunk in chunks:
            sys.stdout.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    elif args.emit == "qdrant":
        print(json.dumps(_qdrant_points(chunks), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'''

    return header + runtime


def write_strategy_chunker_script(
    samples: list[SampleRecord],
    script_stem: str,
    source_label: str,
    output_dir: str | Path,
) -> Path:
    safe_stem = _safe_script_stem(script_stem)
    code = generate_strategy_chunker_script(
        samples=samples,
        strategy_name=safe_stem,
        source_label=source_label,
    )
    output_path = Path(output_dir) / f"{safe_stem}_chunking.py"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code, encoding="utf-8")
    return output_path


def write_chunker_script(
    chunks: list[Chunk],
    document_id: str,
    source_filename: str,
    output_dir: str | Path = "output",
    *,
    script_stem: str | None = None,
    blocks: list[DocumentBlock] | None = None,
    decision: ChunkingDecision | None = None,
    profile: DocumentProfile | None = None,
) -> Path:
    sample: SampleRecord = {
        "document_id": document_id,
        "source_filename": source_filename,
        "source_path": source_filename,
        "blocks": blocks or [],
        "profile": profile,
        "decision": decision,
        "chunks": chunks,
    }
    return write_strategy_chunker_script(
        samples=[sample],
        script_stem=script_stem or document_id,
        source_label=source_filename,
        output_dir=output_dir,
    )
