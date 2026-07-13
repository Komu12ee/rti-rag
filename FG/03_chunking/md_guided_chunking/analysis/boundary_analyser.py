"""
Stage 1 / Pass 2 - runs the LLM once per window and aggregates the results
into a single ChunkingDecision.

IMPORTANT: This module never decides to retry a window on its own. Every
window is analysed exactly once. If a unit comes back with low confidence
or needs_review=True, it is simply included in the aggregated decision
as-is, with those flags intact, for a human to look at
(`cli.py review`). If you decide something needs another pass, you run
`analysis/repair.py` yourself, explicitly, against the specific block or
unit range you choose.
"""
from __future__ import annotations

import json
from pathlib import Path

from ingestion.markdown_loader import DocumentBlock, blocks_to_dicts
from structure.candidate_detector import detect_candidate_boundaries
from structure.window_builder import Window, build_windows
from llm.ollama_client import OllamaStructuredClient
from llm.schemas import ChunkingDecision, DocumentProfile, StructuralUnit

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "prompts" / "boundary_analysis.txt"
)

SYSTEM_PROMPT = (
    "You analyse document structure. Never modify the source text. "
    "Return only valid structured data conforming to the given schema."
)


class WindowChunkingResult(StructuralUnit):
    """internal alias, kept for clarity when reading logs"""
    pass


def _window_to_prompt(window: Window, profile: DocumentProfile) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        document_profile=profile.model_dump_json(indent=2),
        context_before=json.dumps(
            blocks_to_dicts(window.context_before), ensure_ascii=False, indent=2
        ),
        window_blocks=json.dumps(
            blocks_to_dicts(window.window_blocks), ensure_ascii=False, indent=2
        ),
        context_after=json.dumps(
            blocks_to_dicts(window.context_after), ensure_ascii=False, indent=2
        ),
    )


def analyse_boundaries(
    blocks: list[DocumentBlock],
    profile: DocumentProfile,
    window_size: int = 30,
    context_overlap: int = 3,
    client: OllamaStructuredClient | None = None,
    verbose: bool = True,
) -> ChunkingDecision:
    client = client or OllamaStructuredClient()

    candidates = detect_candidate_boundaries(blocks)
    windows = build_windows(
        blocks, candidates, window_size=window_size, context_overlap=context_overlap
    )

    all_units: list[StructuralUnit] = []
    unresolved: list[str] = []

    # A minimal per-window schema: reuse ChunkingDecision, since the model
    # returns the same "document_type + units + unresolved" shape for a
    # window as it would for the whole doc; document_type will just be
    # repeated/ignored across windows in favour of the Pass-1 profile.
    for window in windows:
        if verbose:
            wb = window.window_blocks
            span = f"{wb[0].block_id}..{wb[-1].block_id}" if wb else "(empty)"
            print(f"[analyse] window {window.index}: blocks {span} "
                  f"({len(wb)} blocks)")

        if not window.window_blocks:
            continue

        prompt = _window_to_prompt(window, profile)
        result = client.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            response_model=ChunkingDecision,
        )

        all_units.extend(result.units)
        unresolved.extend(result.unresolved_block_ids)

    return ChunkingDecision(
        document_type=profile.document_type,
        units=all_units,
        unresolved_block_ids=sorted(set(unresolved)),
    )


def save_decision(decision: ChunkingDecision, path: str | Path) -> None:
    Path(path).write_text(
        decision.model_dump_json(indent=2), encoding="utf-8"
    )


def load_decision(path: str | Path) -> ChunkingDecision:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ChunkingDecision.model_validate(data)


def write_review_report(decision: ChunkingDecision, path: str | Path) -> None:
    """Human-readable markdown report, sorted lowest-confidence first, so
    you can quickly decide what (if anything) to send to repair.py."""
    rows = sorted(decision.units, key=lambda u: u.confidence)

    lines = [
        "# Boundary Analysis Review",
        "",
        f"Document type (from profile): `{decision.document_type}`",
        f"Total units: {len(decision.units)}",
        f"Unresolved block ids: {len(decision.unresolved_block_ids)}",
        "",
        "| Confidence | Needs Review | Unit Type | Identifier | "
        "Start Block | End Block | Reason |",
        "|---:|:---:|---|---|---|---|---|",
    ]
    for u in rows:
        flag = "**YES**" if u.needs_review else "no"
        lines.append(
            f"| {u.confidence:.2f} | {flag} | {u.unit_type} | "
            f"{u.identifier or '-'} | {u.start_block_id} | {u.end_block_id} | "
            f"{u.boundary_reason.replace(chr(10), ' ')} |"
        )

    if decision.unresolved_block_ids:
        lines += ["", "## Unresolved block IDs (not assigned to any unit)", ""]
        for bid in decision.unresolved_block_ids:
            lines.append(f"- {bid}")

    lines += [
        "",
        "## What to do next",
        "",
        "This report is informational only - nothing was auto-retried. "
        "If you see rows you're not happy with, run, for example:",
        "",
        "```bash",
        "python cli.py repair path/to/your_doc.md --unit-id <identifier> "
        "--context-blocks 6",
        "```",
        "",
        "or target a raw block range directly:",
        "",
        "```bash",
        "python cli.py repair path/to/your_doc.md "
        "--block-range <start_block_id>:<end_block_id>",
        "```",
    ]

    Path(path).write_text("\n".join(lines), encoding="utf-8")
