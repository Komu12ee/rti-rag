"""
Layer C - deterministic assembler.

Takes the (possibly human-repaired) ChunkingDecision and the original
blocks, and builds a parent/child chunk tree. The LLM never writes final
chunk text - this module copies the original block text verbatim, in
order, and only structures it according to the LLM's boundary decisions
and identifier/parent_identifier fields.

This structure is what codegen/script_generator.py bakes into the final
hardcoded chunker script.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ingestion.markdown_loader import DocumentBlock
from llm.schemas import ChunkingDecision, StructuralUnit


@dataclass
class Chunk:
    chunk_id: str
    unit_type: str
    identifier: str | None
    title: str | None
    parent_id: str | None
    start_block_id: str
    end_block_id: str
    text: str
    is_parent: bool
    child_ids: list[str] = field(default_factory=list)
    previous_sibling_id: str | None = None
    next_sibling_id: str | None = None


def _slugify(value: str) -> str:
    out = []
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_") or "unit"


def _extract_text(
    start_block_id: str, end_block_id: str,
    blocks_by_id: dict[str, DocumentBlock], ordered_ids: list[str],
) -> str:
    start_idx = ordered_ids.index(start_block_id)
    end_idx = ordered_ids.index(end_block_id)
    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx
    parts = [blocks_by_id[bid].text for bid in ordered_ids[start_idx:end_idx + 1]]
    return "\n\n".join(parts)


def build_chunks(
    blocks: list[DocumentBlock],
    decision: ChunkingDecision,
    document_id: str,
) -> list[Chunk]:
    ordered_ids = [b.block_id for b in blocks]
    blocks_by_id = {b.block_id: b for b in blocks}

    # Sort units by document position so sibling links and IDs come out
    # in a stable, human-sensible order.
    def pos(u: StructuralUnit) -> int:
        try:
            return ordered_ids.index(u.start_block_id)
        except ValueError:
            return 10 ** 9

    sorted_units = sorted(decision.units, key=pos)

    chunks: list[Chunk] = []
    id_by_identifier: dict[str, str] = {}
    generated_ids_used: set[str] = set()

    for unit in sorted_units:
        base = unit.identifier or f"{unit.start_block_id}_{unit.end_block_id}"
        chunk_id = f"{document_id}_{_slugify(unit.unit_type)}_{_slugify(base)}"
        # de-dupe if two units slugify to the same id
        candidate = chunk_id
        suffix = 2
        while candidate in generated_ids_used:
            candidate = f"{chunk_id}_{suffix}"
            suffix += 1
        chunk_id = candidate
        generated_ids_used.add(chunk_id)

        if unit.identifier:
            id_by_identifier[unit.identifier] = chunk_id

        try:
            text = _extract_text(
                unit.start_block_id, unit.end_block_id, blocks_by_id, ordered_ids
            )
        except ValueError:
            text = ""

        chunks.append(Chunk(
            chunk_id=chunk_id,
            unit_type=unit.unit_type,
            identifier=unit.identifier,
            title=unit.title,
            parent_id=None,  # resolved below
            start_block_id=unit.start_block_id,
            end_block_id=unit.end_block_id,
            text=text,
            is_parent=False,  # set below once we know who has children
        ))

    # Resolve parent_id via parent_identifier -> chunk_id lookup, and back
    # -fill child_ids on the parent.
    chunk_by_id = {c.chunk_id: c for c in chunks}
    for unit, chunk in zip(sorted_units, chunks):
        if unit.parent_identifier and unit.parent_identifier in id_by_identifier:
            parent_chunk_id = id_by_identifier[unit.parent_identifier]
            if parent_chunk_id != chunk.chunk_id:
                chunk.parent_id = parent_chunk_id
                chunk_by_id[parent_chunk_id].child_ids.append(chunk.chunk_id)
                chunk_by_id[parent_chunk_id].is_parent = True

    # Sibling links: among chunks sharing the same parent_id (or all
    # top-level chunks if parent_id is None), link by document order.
    groups: dict[str | None, list[Chunk]] = {}
    for chunk in chunks:
        groups.setdefault(chunk.parent_id, []).append(chunk)

    for _, siblings in groups.items():
        siblings_sorted = sorted(
            siblings, key=lambda c: ordered_ids.index(c.start_block_id)
        )
        for i, chunk in enumerate(siblings_sorted):
            if i > 0:
                chunk.previous_sibling_id = siblings_sorted[i - 1].chunk_id
            if i < len(siblings_sorted) - 1:
                chunk.next_sibling_id = siblings_sorted[i + 1].chunk_id

    return chunks
