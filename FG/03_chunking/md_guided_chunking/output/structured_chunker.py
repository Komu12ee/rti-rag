"""
AUTO-GENERATED hardcoded chunker for: structured.md
Document id: structured
Generated at: 2026-07-13T03:16:30.618586+00:00

This file was produced once by the md_guided_chunking pipeline's Stage 2
codegen step. It is now a STANDALONE artifact:
  - it does NOT call Ollama or any LLM,
  - it does NOT re-parse or re-analyse structured.md,
  - every chunk boundary and piece of text below is hardcoded as it was
    determined at generation time.

If structured.md changes, re-run the pipeline (`cli.py analyze` /
`cli.py generate`) to produce a fresh version of this file - do not hand
-edit boundaries here without also updating the source pipeline's saved
decision, or the two will drift apart.

Run this file directly:
    python structured_chunker.py --emit jsonl   > structured.jsonl
    python structured_chunker.py --emit txt      # prints readable dump
    python structured_chunker.py --emit qdrant   > structured_points.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict


@dataclass
class HardcodedChunk:
    chunk_id: str
    unit_type: str
    identifier: str | None
    title: str | None
    parent_id: str | None
    child_ids: list[str]
    previous_sibling_id: str | None
    next_sibling_id: str | None
    start_block_id: str
    end_block_id: str
    text: str


_CHUNK_0000 = HardcodedChunk(
    chunk_id='structured_section_b0002_b0003',
    unit_type='section',
    identifier=None,
    title=None,
    parent_id=None,
    child_ids=[],
    previous_sibling_id=None,
    next_sibling_id='structured_section_b0007_b0008',
    start_block_id='b0002',
    end_block_id='b0003',
    text="""जनसूचना अधिकारी का पंजीयन

- रजिस्ट्रेशन क लिए ऑनलाईन पोर्टल https/ /rtionline cg govin ओपन करें |
- जनसूचना अधिकारी का पंजीयन' पर Click करें |
- मैंने सभी निर्देशों को ध्यान से पढ़ लिया है पर टिक करें और Next पर क्लिक करें |
- जनसूचना अधिकारी का व्यक्तिगत विवरण नाम॰ ई मेल आईडी॰ मो॰ नं॰, लिंग॰ पदनाम, राज्य, जिला. मुख्य विभाग, कार्यालय की जानकारी देवें |
- नोट - यदि दी गई तालिका में आपके कार्यालय का नाम सूचीबद्घ न हा ता "नया कार्यालय जोड़ें "  ऑप्शन पर क्लिक करें और नया कार्यालय बनायें Submit पर क्लिक करें |
- दिये गये ई्मेल आईडी में एक लिंक आयेगा|
- उस लिंक को क्लिक करने पर पासवर्ड बनाने का आएगा | लॉगिन आईडी आपका दर्ज ईमेल आईडी रहेगा| मेन्यू
- प्रथम अपीलीय अधिकारी / नोडल अधिकारी की जानकारी की एंट्री करने के लिए अपने ई मेल आईडी हेतु पासवर्ड डालकर आरटीआई पोर्टल Open करें |""",
)
_CHUNK_0001 = HardcodedChunk(
    chunk_id='structured_section_b0007_b0008',
    unit_type='section',
    identifier=None,
    title=None,
    parent_id=None,
    child_ids=[],
    previous_sibling_id='structured_section_b0002_b0003',
    next_sibling_id='structured_section_b0011_b0015',
    start_block_id='b0007',
    end_block_id='b0008',
    text="""नोडल अधिकारी क लिए

नोडल अधिकारी का दिये गये ई मेल आईडी में एक लिंक जायेगा॰ जिसको ओपन करके पासवर्ड बनाना होगा|""",
)
_CHUNK_0002 = HardcodedChunk(
    chunk_id='structured_section_b0011_b0015',
    unit_type='section',
    identifier=None,
    title=None,
    parent_id=None,
    child_ids=[],
    previous_sibling_id='structured_section_b0007_b0008',
    next_sibling_id=None,
    start_block_id='b0011',
    end_block_id='b0015',
    text="""प्रथम अपीलीय अधिकारी के लिए

प्रथम अपीलीय अधिकारी को दिये गये ई मेल आईडी में एक लिंक जायेगा, जिसको ओपन करक पासवर्ड बनाना होगा|

प्रथम अपीलीय अधिकारी का ईमेल आईडी, उसका लॉगइन आईडी होगा|

प्रथम अपीलीय अधिकारी को अपना आदेश अपलोड करना है| यदि पहले से आदेश अपलोड है तो नीचे दिए गए आदेश की कॉपी को सेलेक्ट करक अपलोड कर सकते हैं |

जनसचूना अधिकारी को एप्रूवल देना है|""",
)

ALL_CHUNKS: list[HardcodedChunk] = [
    _CHUNK_0000,
    _CHUNK_0001,
    _CHUNK_0002,
]

CHUNKS_BY_ID: dict[str, HardcodedChunk] = {c.chunk_id: c for c in ALL_CHUNKS}
PARENT_CHUNKS: list[HardcodedChunk] = [c for c in ALL_CHUNKS if c.child_ids]
CHILD_CHUNKS: list[HardcodedChunk] = [c for c in ALL_CHUNKS if c.parent_id]
TOP_LEVEL_CHUNKS: list[HardcodedChunk] = [c for c in ALL_CHUNKS if c.parent_id is None]


def get_chunk(chunk_id: str) -> HardcodedChunk | None:
    return CHUNKS_BY_ID.get(chunk_id)


def get_with_parent(chunk_id: str) -> tuple[HardcodedChunk | None, HardcodedChunk | None]:
    chunk = get_chunk(chunk_id)
    if chunk is None:
        return None, None
    parent = CHUNKS_BY_ID.get(chunk.parent_id) if chunk.parent_id else None
    return chunk, parent


def get_siblings(chunk_id: str) -> list[HardcodedChunk]:
    chunk = get_chunk(chunk_id)
    if chunk is None:
        return []
    parent = CHUNKS_BY_ID.get(chunk.parent_id) if chunk.parent_id else None
    sibling_ids = parent.child_ids if parent else [
        c.chunk_id for c in TOP_LEVEL_CHUNKS
    ]
    return [CHUNKS_BY_ID[cid] for cid in sibling_ids if cid in CHUNKS_BY_ID]


def to_qdrant_points(chunks: list[HardcodedChunk]) -> list[dict]:
    """Child (leaf) chunks become vector points; parent text is carried as
    payload for context expansion at query time. Replace `vector` with
    real embeddings from your embedding model before upserting."""
    points = []
    leaf_chunks = [c for c in chunks if not c.child_ids] or chunks
    for c in leaf_chunks:
        parent = CHUNKS_BY_ID.get(c.parent_id) if c.parent_id else None
        points.append({
            "id": c.chunk_id,
            "vector": None,  # fill in with your embedding model's output
            "payload": {
                "chunk_id": c.chunk_id,
                "unit_type": c.unit_type,
                "identifier": c.identifier,
                "title": c.title,
                "text": c.text,
                "parent_id": c.parent_id,
                "parent_text": parent.text if parent else None,
                "previous_sibling_id": c.previous_sibling_id,
                "next_sibling_id": c.next_sibling_id,
                "start_block_id": c.start_block_id,
                "end_block_id": c.end_block_id,
            },
        })
    return points


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emit", choices=["jsonl", "txt", "qdrant"], default="jsonl",
        help="Output format.",
    )
    parser.add_argument(
        "--leaf-only", action="store_true",
        help="Only emit child/leaf chunks (skip parent-only container chunks).",
    )
    args = parser.parse_args()

    chunks = CHILD_CHUNKS if args.leaf_only and CHILD_CHUNKS else ALL_CHUNKS

    if args.emit == "jsonl":
        for c in chunks:
            sys.stdout.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    elif args.emit == "txt":
        for c in chunks:
            print(f"=== {c.chunk_id} ({c.unit_type} {c.identifier or ''}) ===")
            print(c.text)
            print()
    elif args.emit == "qdrant":
        points = to_qdrant_points(chunks)
        print(json.dumps(points, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
