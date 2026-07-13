"""
Builds block windows to send to the LLM for boundary analysis, each with a
small amount of neighbouring context (previous/next N blocks), similar to
Pass 2 in the reference pipeline. Windows try to align to a candidate
boundary (e.g. a heading) rather than cutting mid-window when possible,
but this is a soft preference, not a hard requirement - the assembler and
validators will catch any resulting issues and you can always run a
manual repair pass over the seam.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingestion.markdown_loader import DocumentBlock
from structure.candidate_detector import CandidateBoundary


@dataclass
class Window:
    index: int
    window_blocks: list[DocumentBlock]
    context_before: list[DocumentBlock]
    context_after: list[DocumentBlock]


def build_windows(
    blocks: list[DocumentBlock],
    candidates: list[CandidateBoundary],
    window_size: int = 30,
    context_overlap: int = 3,
) -> list[Window]:
    candidate_ids = {c.block_id for c in candidates}
    n = len(blocks)
    windows: list[Window] = []

    start = 0
    index = 0
    while start < n:
        # Tentative end of window
        end = min(start + window_size, n)

        # Try to extend/shrink slightly so the window ends right before a
        # strong candidate boundary (heading) rather than mid-section.
        # Search a small look-ahead range only - this is a soft nudge.
        if end < n:
            look_ahead = min(end + 5, n)
            for probe in range(end, look_ahead):
                if blocks[probe].block_id in candidate_ids:
                    end = probe
                    break

        window_blocks = blocks[start:end]
        ctx_before = blocks[max(0, start - context_overlap):start]
        ctx_after = blocks[end:min(n, end + context_overlap)]

        windows.append(Window(
            index=index,
            window_blocks=window_blocks,
            context_before=ctx_before,
            context_after=ctx_after,
        ))

        index += 1
        start = end if end > start else start + window_size  # safety

    return windows


def build_region_window(
    blocks: list[DocumentBlock],
    start_block_id: str,
    end_block_id: str,
    context_overlap: int = 6,
) -> Window:
    """Used by the manual repair pass: builds one wide window covering an
    explicit block range the human reviewer names, with extra context on
    both sides."""
    ids = [b.block_id for b in blocks]
    try:
        start_idx = ids.index(start_block_id)
        end_idx = ids.index(end_block_id)
    except ValueError as exc:
        raise ValueError(
            f"block id not found in document: {exc}"
        ) from exc

    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx

    window_blocks = blocks[start_idx:end_idx + 1]
    ctx_before = blocks[max(0, start_idx - context_overlap):start_idx]
    ctx_after = blocks[end_idx + 1: min(len(blocks), end_idx + 1 + context_overlap)]

    return Window(
        index=-1,
        window_blocks=window_blocks,
        context_before=ctx_before,
        context_after=ctx_after,
    )
