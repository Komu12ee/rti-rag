"""Flags units that are unusually large or small relative to target token
ranges. This is informational only: it does NOT split or merge anything -
that's left to parent_child_builder.py's deterministic child-splitting,
and ultimately to you."""
from __future__ import annotations

from dataclasses import dataclass, field

from ingestion.markdown_loader import DocumentBlock
from llm.schemas import ChunkingDecision

# Rough token estimate: ~4 characters per token (English-ish heuristic).
CHARS_PER_TOKEN = 4


@dataclass
class SizeFlag:
    identifier: str
    unit_type: str
    approx_tokens: int
    flag: str  # "oversized" | "undersized"


@dataclass
class SizeReport:
    flags: list[SizeFlag] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.flags


def _unit_char_count(
    unit_start: str, unit_end: str, blocks_by_id: dict[str, DocumentBlock],
    ordered_ids: list[str],
) -> int:
    start_idx = ordered_ids.index(unit_start)
    end_idx = ordered_ids.index(unit_end)
    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx
    total = 0
    for bid in ordered_ids[start_idx:end_idx + 1]:
        total += len(blocks_by_id[bid].text)
    return total


def check_sizes(
    blocks: list[DocumentBlock],
    decision: ChunkingDecision,
    target_min_tokens: int = 50,
    target_max_tokens: int = 900,
) -> SizeReport:
    ordered_ids = [b.block_id for b in blocks]
    blocks_by_id = {b.block_id: b for b in blocks}
    report = SizeReport()

    for unit in decision.units:
        try:
            chars = _unit_char_count(
                unit.start_block_id, unit.end_block_id, blocks_by_id, ordered_ids
            )
        except ValueError:
            continue
        approx_tokens = chars // CHARS_PER_TOKEN
        label = unit.identifier or f"{unit.start_block_id}-{unit.end_block_id}"

        if approx_tokens > target_max_tokens:
            report.flags.append(SizeFlag(label, unit.unit_type, approx_tokens, "oversized"))
        elif approx_tokens < target_min_tokens:
            report.flags.append(SizeFlag(label, unit.unit_type, approx_tokens, "undersized"))

    return report
