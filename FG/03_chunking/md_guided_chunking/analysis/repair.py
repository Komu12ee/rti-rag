"""
Manual repair pass.

This module is ONLY ever invoked by you, via `cli.py repair ...`. Nothing
elsewhere in the pipeline calls into this file automatically - there is no
confidence threshold, no auto-retry, no silent re-analysis. You name the
unit or block range; this re-runs the LLM over that region with wider
context and merges the result back into the saved decision (after backing
up the previous version).
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ingestion.markdown_loader import DocumentBlock, blocks_to_dicts
from structure.window_builder import build_region_window
from llm.ollama_client import OllamaStructuredClient
from llm.schemas import ChunkingDecision, DocumentProfile, RepairResult, StructuralUnit

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "prompts" / "boundary_repair.txt"
)

SYSTEM_PROMPT = (
    "You re-analyse a flagged region of document structure. Never modify "
    "the source text. Return only valid structured data conforming to the "
    "given schema."
)


def find_unit_by_identifier(
    decision: ChunkingDecision, identifier: str
) -> StructuralUnit | None:
    for unit in decision.units:
        if unit.identifier == identifier:
            return unit
    return None


def repair_region(
    blocks: list[DocumentBlock],
    profile: DocumentProfile,
    decision: ChunkingDecision,
    start_block_id: str,
    end_block_id: str,
    repair_reason: str = "",
    context_blocks: int = 6,
    client: OllamaStructuredClient | None = None,
) -> RepairResult:
    client = client or OllamaStructuredClient()

    window = build_region_window(
        blocks, start_block_id, end_block_id, context_overlap=context_blocks
    )

    # Previous units that overlapped this region, for the model's reference
    region_ids = {b.block_id for b in window.window_blocks}
    previous_units = [
        u for u in decision.units
        if u.start_block_id in region_ids or u.end_block_id in region_ids
    ]

    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        repair_reason=repair_reason or "(none given)",
        previous_units=json.dumps(
            [u.model_dump() for u in previous_units], ensure_ascii=False, indent=2
        ),
        document_profile=profile.model_dump_json(indent=2),
        region_blocks=json.dumps(
            blocks_to_dicts(
                window.context_before + window.window_blocks + window.context_after
            ),
            ensure_ascii=False,
            indent=2,
        ),
    )

    # Repair passes default to thinking mode ON, since this is explicitly
    # the "I want a deeper look" path - but you can override via the CLI.
    return client.generate(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        response_model=RepairResult,
        thinking=True,
    )


def merge_repair_into_decision(
    decision: ChunkingDecision,
    repair_result: RepairResult,
    start_block_id: str,
    end_block_id: str,
    blocks: list[DocumentBlock],
) -> ChunkingDecision:
    """Removes old units fully inside the repaired region and old units
    that reference now-repaired block ids, then appends the new units.
    Nothing outside the named region is touched."""
    ids_in_order = [b.block_id for b in blocks]
    start_idx = ids_in_order.index(start_block_id)
    end_idx = ids_in_order.index(end_block_id)
    region_ids = set(ids_in_order[start_idx:end_idx + 1])

    kept_units = [
        u for u in decision.units
        if u.start_block_id not in region_ids and u.end_block_id not in region_ids
    ]
    new_units = kept_units + repair_result.units

    kept_unresolved = [
        b for b in decision.unresolved_block_ids if b not in region_ids
    ]
    new_unresolved = sorted(set(kept_unresolved + repair_result.unresolved_block_ids))

    return ChunkingDecision(
        document_type=decision.document_type,
        units=new_units,
        unresolved_block_ids=new_unresolved,
    )


def backup_decision_file(decision_path: str | Path) -> Path:
    decision_path = Path(decision_path)
    if not decision_path.exists():
        return decision_path
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = decision_path.with_name(
        f"{decision_path.stem}.backup-{timestamp}{decision_path.suffix}"
    )
    shutil.copy2(decision_path, backup_path)
    return backup_path
