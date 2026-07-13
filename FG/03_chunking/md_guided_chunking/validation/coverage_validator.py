"""Checks that every source block is included in exactly one unit, or is
explicitly listed as unresolved. Reports only - never modifies anything."""
from __future__ import annotations

from dataclasses import dataclass, field

from ingestion.markdown_loader import DocumentBlock
from llm.schemas import ChunkingDecision


@dataclass
class CoverageReport:
    total_blocks: int
    covered_blocks: int
    missing_block_ids: list[str] = field(default_factory=list)
    duplicate_block_ids: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_block_ids and not self.duplicate_block_ids


def _expand_unit_block_ids(unit_start: str, unit_end: str, ordered_ids: list[str]) -> list[str]:
    start_idx = ordered_ids.index(unit_start)
    end_idx = ordered_ids.index(unit_end)
    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx
    return ordered_ids[start_idx:end_idx + 1]


def check_coverage(
    blocks: list[DocumentBlock], decision: ChunkingDecision
) -> CoverageReport:
    ordered_ids = [b.block_id for b in blocks]
    seen: dict[str, int] = {bid: 0 for bid in ordered_ids}

    for unit in decision.units:
        try:
            covered = _expand_unit_block_ids(
                unit.start_block_id, unit.end_block_id, ordered_ids
            )
        except ValueError:
            # start/end id doesn't exist in the document at all
            continue
        for bid in covered:
            seen[bid] = seen.get(bid, 0) + 1

    for bid in decision.unresolved_block_ids:
        if bid in seen:
            seen[bid] = max(seen[bid], 1)  # explicitly acknowledged as unresolved

    missing = [bid for bid, count in seen.items() if count == 0]
    duplicates = [bid for bid, count in seen.items() if count > 1]

    return CoverageReport(
        total_blocks=len(ordered_ids),
        covered_blocks=len(ordered_ids) - len(missing),
        missing_block_ids=missing,
        duplicate_block_ids=duplicates,
    )
