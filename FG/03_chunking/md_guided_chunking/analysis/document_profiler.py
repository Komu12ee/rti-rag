"""Stage 1 / Pass 1 - build a DocumentProfile from a sample of blocks."""
from __future__ import annotations

import json
from pathlib import Path

from ingestion.markdown_loader import DocumentBlock, blocks_to_dicts
from structure.candidate_detector import build_heading_outline
from llm.ollama_client import OllamaStructuredClient
from llm.schemas import DocumentProfile

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "prompts" / "document_profile.txt"
)

SYSTEM_PROMPT = (
    "You analyse document structure. Never modify the source text. "
    "Return only valid structured data conforming to the given schema."
)


def _sample_blocks(blocks: list[DocumentBlock], max_blocks: int = 60) -> list[DocumentBlock]:
    n = len(blocks)
    if n <= max_blocks:
        return blocks
    head = blocks[: max_blocks // 3]
    mid_start = n // 2 - max_blocks // 6
    mid = blocks[max(0, mid_start): max(0, mid_start) + max_blocks // 3]
    tail = blocks[-(max_blocks // 3):]
    return head + mid + tail


def build_document_profile(
    filename: str,
    blocks: list[DocumentBlock],
    client: OllamaStructuredClient | None = None,
) -> DocumentProfile:
    client = client or OllamaStructuredClient()

    outline = build_heading_outline(blocks)
    sample = _sample_blocks(blocks)

    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        filename=filename,
        heading_outline=json.dumps(outline, ensure_ascii=False, indent=2),
        sample_blocks=json.dumps(
            blocks_to_dicts(sample), ensure_ascii=False, indent=2
        ),
    )

    return client.generate(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        response_model=DocumentProfile,
    )
