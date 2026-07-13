"""
Layer A - generic, document-agnostic candidate boundary detection.

This does NOT decide final chunks. It just flags which blocks are
*plausible* structural boundaries so that:
  - window_builder.py can align windows to sensible edges instead of
    slicing mid-clause,
  - the LLM prompt can include a heading outline for context,
  - obvious cases can be short-circuited without an LLM call if you want
    (see analysis/boundary_analyser.py's `--skip-obvious` flag).

Nothing here is specific to any one document - it is pure pattern
matching over heading levels and generic numbering conventions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ingestion.markdown_loader import DocumentBlock, NUMBERING_PATTERNS

# Generic keyword cues that often mark a legal/structural unit start.
# This list is intentionally generic (not tailored to any one document)
# and is used only as a *hint*, never as a hard rule.
STRUCTURAL_KEYWORDS = re.compile(
    r"^\s*("
    r"chapter|section|rule|order|notification|schedule|annexure|appendix|"
    r"form|part|clause|article|regulation|circular|"
    r"अध्याय|धारा|नियम|आदेश|अधिसूचना|अनुसूची|परिशिष्ट|प्रपत्र"
    r")\b",
    re.IGNORECASE,
)

# e.g. "7.", "7.1", "7(1)(a)", "नियम 3(2)"
IDENTIFIER_RE = re.compile(
    r"\b\d+(\.\d+)*(\([a-zA-Z0-9]+\))*\b"
)


@dataclass
class CandidateBoundary:
    block_id: str
    reason: str
    strength: float  # 0-1, purely descriptive, not a routing threshold


def _numbering_token(text: str) -> str | None:
    first_token = text.strip().split(" ", 1)[0] if text.strip() else ""
    for pattern in NUMBERING_PATTERNS:
        if pattern.match(first_token):
            return first_token
    return None


def detect_candidate_boundaries(
    blocks: list[DocumentBlock],
) -> list[CandidateBoundary]:
    candidates: list[CandidateBoundary] = []

    prev_heading_level: int | None = None

    for block in blocks:
        if block.block_type == "heading":
            strength = 1.0
            reason = f"markdown heading level {block.heading_level}"
            if prev_heading_level is not None and block.heading_level is not None:
                if block.heading_level <= prev_heading_level:
                    reason += " (sibling or higher-level heading)"
            candidates.append(CandidateBoundary(block.block_id, reason, strength))
            prev_heading_level = block.heading_level
            continue

        if block.block_type in ("paragraph", "list_item"):
            first_line = block.text.strip().splitlines()[0] if block.text.strip() else ""
            if STRUCTURAL_KEYWORDS.match(first_line):
                candidates.append(CandidateBoundary(
                    block.block_id,
                    "starts with a generic structural keyword",
                    0.7,
                ))
                continue
            token = _numbering_token(first_line)
            if token:
                candidates.append(CandidateBoundary(
                    block.block_id,
                    f"starts with numbering pattern '{token}'",
                    0.5,
                ))
                continue

        if block.block_type == "table":
            candidates.append(CandidateBoundary(
                block.block_id, "table block (potential schedule/appendix)", 0.4
            ))

        if block.block_type == "hr":
            candidates.append(CandidateBoundary(
                block.block_id, "horizontal rule (explicit visual separator)", 0.6
            ))

    return candidates


def build_heading_outline(blocks: list[DocumentBlock]) -> list[dict]:
    """A simple table-of-contents style outline used as LLM context."""
    outline = []
    for block in blocks:
        if block.block_type == "heading":
            outline.append({
                "block_id": block.block_id,
                "level": block.heading_level,
                "text": block.text,
            })
    return outline
