"""Checks document ordering and identifier-numbering continuity.
Missing numbers/out-of-order units are reported as warnings only - this
module never invents or renumbers anything."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ingestion.markdown_loader import DocumentBlock
from llm.schemas import ChunkingDecision, StructuralUnit

_LEADING_INT_RE = re.compile(r"^\d+")


@dataclass
class SequenceReport:
    out_of_order: list[tuple[str, str]] = field(default_factory=list)  # (unit_id_a, unit_id_b)
    numbering_gaps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.out_of_order and not self.numbering_gaps


def check_ordering(
    blocks: list[DocumentBlock], decision: ChunkingDecision
) -> SequenceReport:
    ordered_ids = [b.block_id for b in blocks]
    report = SequenceReport()

    def pos(block_id: str) -> int:
        try:
            return ordered_ids.index(block_id)
        except ValueError:
            return -1

    prev: StructuralUnit | None = None
    for unit in sorted(decision.units, key=lambda u: pos(u.start_block_id)):
        if pos(unit.start_block_id) > pos(unit.end_block_id):
            label = unit.identifier or unit.start_block_id
            report.out_of_order.append((label, "start_block_id after end_block_id"))
        if prev is not None and pos(unit.start_block_id) < pos(prev.end_block_id):
            report.out_of_order.append((
                prev.identifier or prev.start_block_id,
                unit.identifier or unit.start_block_id,
            ))
        prev = unit

    # Numbering continuity, grouped by unit_type (only where identifiers
    # are simple leading integers - anything else is skipped rather than
    # guessed at).
    by_type: dict[str, list[int]] = {}
    for unit in decision.units:
        if not unit.identifier:
            continue
        match = _LEADING_INT_RE.match(unit.identifier.strip())
        if not match:
            continue
        by_type.setdefault(unit.unit_type, []).append(int(match.group()))

    for unit_type, numbers in by_type.items():
        numbers_sorted = sorted(set(numbers))
        for a, b in zip(numbers_sorted, numbers_sorted[1:]):
            if b - a > 1:
                gap = ", ".join(str(x) for x in range(a + 1, b))
                report.numbering_gaps.append(
                    f"{unit_type}: missing {gap} between {a} and {b}"
                )

    return report
