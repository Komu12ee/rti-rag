"""
Markdown -> stable DocumentBlock list.

This replaces the Docling extraction layer from the generic pipeline.
Since input is guaranteed to be a single .md file, we can parse it
directly with a small state machine instead of pulling in a heavy
document-conversion dependency.

Block types produced:
    heading      - '#' .. '######' lines
    paragraph    - normal prose, blank-line delimited
    list_item    - '-', '*', '+', or '1.' style list lines (grouped as one
                   block per contiguous list, individual items kept as
                   sub-lines in `text` separated by \n so nothing is lost)
    code_block   - fenced ``` ... ``` regions (kept verbatim, not parsed)
    table        - contiguous block of lines containing '|' with a
                   separator row (--- | ---)
    blockquote   - contiguous '>' lines
    hr           - horizontal rule (---, ***, ___ on their own line)
    blank        - not emitted as a block; used only to delimit others

Every block gets a stable block_id of the form "b0001", "b0002", ... in
document order. IDs are stable across re-runs of the same file content
(they are purely positional / content-independent), which is what the
downstream LLM and codegen stages rely on for references.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal, Optional

BlockType = Literal[
    "heading", "paragraph", "list_item", "code_block",
    "table", "blockquote", "hr",
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+\S")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW_RE = re.compile(r".*\|.*")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")

# Generic numbering / identifier patterns the candidate detector also uses.
NUMBERING_PATTERNS = [
    re.compile(r"^\d+(\.\d+)*\.?$"),          # 1  1.2  1.2.3
    re.compile(r"^\(\w+\)$"),                  # (a) (1) (iv)
    re.compile(r"^[A-Za-z]\)$"),                # a)
    re.compile(r"^[IVXLCDM]+\.$", re.IGNORECASE),  # Roman numerals
]


@dataclass
class DocumentBlock:
    block_id: str
    block_type: BlockType
    text: str
    line_start: int
    line_end: int
    heading_level: Optional[int] = None
    detected_language: Optional[str] = None
    content_hash: str = field(default="")

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.text.encode("utf-8")
            ).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)


def _detect_language(text: str) -> str:
    """Very light heuristic: presence of Devanagari => 'hi', else 'en'.
    Extend this if your documents use other scripts."""
    if re.search(r"[\u0900-\u097F]", text):
        if re.search(r"[A-Za-z]{3,}", text):
            return "mixed"
        return "hi"
    return "en"


def load_markdown_blocks(path: str | Path) -> list[DocumentBlock]:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    blocks: list[DocumentBlock] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"b{counter:04d}"

    i = 0
    n = len(lines)
    para_buffer: list[str] = []
    para_start: Optional[int] = None

    def flush_paragraph(end_line: int):
        nonlocal para_buffer, para_start
        if para_buffer:
            joined = "\n".join(para_buffer).strip()
            if joined:
                blocks.append(DocumentBlock(
                    block_id=next_id(),
                    block_type="paragraph",
                    text=joined,
                    line_start=para_start if para_start is not None else end_line,
                    line_end=end_line,
                    detected_language=_detect_language(joined),
                ))
            para_buffer = []
            para_start = None

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        # Blank line: paragraph delimiter
        if stripped == "":
            flush_paragraph(i)
            i += 1
            continue

        # Fenced code block
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
                code_lines.append(lines[i])  # closing fence
                i += 1
            blocks.append(DocumentBlock(
                block_id=next_id(),
                block_type="code_block",
                text="\n".join(code_lines),
                line_start=start_line,
                line_end=i - 1,
            ))
            continue

        # Heading
        heading_match = _HEADING_RE.match(raw)
        if heading_match:
            flush_paragraph(i - 1)
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2)
            blocks.append(DocumentBlock(
                block_id=next_id(),
                block_type="heading",
                text=heading_text,
                line_start=i,
                line_end=i,
                heading_level=level,
                detected_language=_detect_language(heading_text),
            ))
            i += 1
            continue

        # Horizontal rule
        if _HR_RE.match(raw):
            flush_paragraph(i - 1)
            blocks.append(DocumentBlock(
                block_id=next_id(),
                block_type="hr",
                text=stripped,
                line_start=i,
                line_end=i,
            ))
            i += 1
            continue

        # Table (heading row + separator row + body rows)
        if (_TABLE_ROW_RE.match(raw) and i + 1 < n
                and _TABLE_SEP_RE.match(lines[i + 1].strip())):
            flush_paragraph(i - 1)
            start_line = i
            table_lines = [raw, lines[i + 1]]
            i += 2
            while i < n and _TABLE_ROW_RE.match(lines[i]) and lines[i].strip() != "":
                table_lines.append(lines[i])
                i += 1
            blocks.append(DocumentBlock(
                block_id=next_id(),
                block_type="table",
                text="\n".join(table_lines),
                line_start=start_line,
                line_end=i - 1,
            ))
            continue

        # Blockquote
        if _BLOCKQUOTE_RE.match(raw):
            flush_paragraph(i - 1)
            start_line = i
            quote_lines = [raw]
            i += 1
            while i < n and _BLOCKQUOTE_RE.match(lines[i]):
                quote_lines.append(lines[i])
                i += 1
            blocks.append(DocumentBlock(
                block_id=next_id(),
                block_type="blockquote",
                text="\n".join(quote_lines),
                line_start=start_line,
                line_end=i - 1,
            ))
            continue

        # List (contiguous run of list-like lines, including wrapped
        # continuation lines that are indented under a list marker)
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
            joined = "\n".join(list_lines)
            blocks.append(DocumentBlock(
                block_id=next_id(),
                block_type="list_item",
                text=joined,
                line_start=start_line,
                line_end=i - 1,
                detected_language=_detect_language(joined),
            ))
            continue

        # Default: accumulate into paragraph buffer
        if para_start is None:
            para_start = i
        para_buffer.append(raw)
        i += 1

    flush_paragraph(n - 1)

    return blocks


def blocks_to_dicts(blocks: list[DocumentBlock]) -> list[dict]:
    return [b.to_dict() for b in blocks]


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) != 2:
        print("usage: python markdown_loader.py <file.md>")
        raise SystemExit(1)

    result = load_markdown_blocks(sys.argv[1])
    print(json.dumps(blocks_to_dicts(result), indent=2, ensure_ascii=False))
