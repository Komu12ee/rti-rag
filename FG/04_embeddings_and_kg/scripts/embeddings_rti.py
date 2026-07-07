#!/usr/bin/env python3
"""
Production Embeddings Pipeline with citation-aware Qdrant payloads.

This version reads the metadata headers written by
FAQ_chunking_rti_sources.py and stores the original legal-book citation in
Qdrant. The Flask/Web UI can then show one deduplicated reference such as:

    rti-rule-book.pdf — Section 18 — book pp. 33-35

rather than displaying a derived FAQ file such as structured_faq.pdf.

Required chunk header fields
----------------------------
Original source book: rti-rule-book.pdf
Source type: rti_rule_book
Legal reference: Section 18
Book pages: 33-35
Source PDF pages: 45-47
Citation: rti-rule-book.pdf — Section 18 — book pp. 33-35

Usage
-----
# Incrementally index new or changed chunks
python embeddings_production_citations.py

# Delete all old vectors, reset the manifest, and rebuild from disk
python embeddings_production_citations.py --recreate

# Index only RTI chunks whose original source book is rti-rule-book.pdf
python embeddings_production_citations.py --only-source-book rti-rule-book.pdf

# Test only the RTI original book in interactive query mode
python embeddings_production_citations.py --query --source-book rti-rule-book.pdf

# Show metadata/indexing status without loading embedding models
python embeddings_production_citations.py --status

# Remove manifest-tracked Qdrant points whose chunk files no longer exist
python embeddings_production_citations.py --prune
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PayloadSchemaType,
        PointIdsList,
        PointStruct,
        VectorParams,
    )
except ImportError:
    print("Error: qdrant-client is required. Run: pip install qdrant-client")
    raise SystemExit(1)

try:
    from FlagEmbedding import BGEM3FlagModel, FlagReranker
    from tqdm import tqdm
except ImportError:
    print("Error: FlagEmbedding and tqdm are required.")
    print("Run: pip install FlagEmbedding torch tqdm")
    raise SystemExit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

DEFAULT_CHUNK_DIR = PROJECT_ROOT / "03_chunking" / "output"
QDRANT_PATH = PROJECT_ROOT / "04_embeddings_and_kg" / "db" / "qdrant_local"
MANIFEST_FILE = PROJECT_ROOT / "04_embeddings_and_kg" / ".embeddings_manifest.json"

COLLECTION_NAME = "db3"
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    str(PROJECT_ROOT / "models" / "bge-m3"),
)
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL",
    str(PROJECT_ROOT / "models" / "bge-reranker-v2-m3"),
)

ENCODE_BATCH_SIZE = 8
UPSERT_BATCH_SIZE = 100
MAX_LENGTH = 1024

HYBRID_ALPHA = 0.60
RERANK_MIN_K = 3
RERANK_MAX_K = 6
RERANK_THRESHOLD = 0.65

# Namespace used for deterministic UUIDs. A file that changes keeps the same
# Qdrant point id and is safely upserted in place.
POINT_NAMESPACE = uuid.UUID("4e0da1e2-97a1-4f62-bf38-df9cd2825b7e")


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_page_spec(value: Any) -> list[int]:
    """Parse 33-35, 33,35-36, [33, 34], or a scalar page number."""
    if value is None:
        return []

    if isinstance(value, int):
        return [value] if value > 0 else []

    if isinstance(value, list):
        pages: list[int] = []
        for item in value:
            pages.extend(parse_page_spec(item))
        return sorted(set(pages))

    value = str(value).strip()
    if not value or value.casefold() == "unknown":
        return []

    pages: list[int] = []
    for part in re.split(r"\s*,\s*", value.replace("–", "-")):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            left, right = part.split("-", 1)
            try:
                start, end = int(left.strip()), int(right.strip())
            except ValueError:
                continue

            if start > 0 and end >= start and end - start <= 1_000:
                pages.extend(range(start, end + 1))
        else:
            try:
                page = int(part)
            except ValueError:
                continue
            if page > 0:
                pages.append(page)

    return sorted(set(pages))


def format_pages(pages: Iterable[int]) -> str:
    values = sorted({int(page) for page in pages if isinstance(page, int) and page > 0})
    if not values:
        return "Unknown"

    output: list[str] = []
    start = previous = values[0]

    for page in values[1:]:
        if page == previous + 1:
            previous = page
            continue

        output.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page

    output.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(output)


def stable_point_id(relative_file: str) -> str:
    """Create an id that is stable across re-indexes of the same chunk path."""
    return str(uuid.uuid5(POINT_NAMESPACE, f"{COLLECTION_NAME}:{relative_file.replace(chr(92), '/')}"))


def file_hash(path: Path) -> str:
    """Hash complete chunk bytes, including citation header metadata."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_citation_label(source_book: str, legal_reference: str, book_pages: list[int]) -> str:
    if not source_book:
        return ""

    parts = [source_book]
    if legal_reference:
        parts.append(legal_reference)
    if book_pages:
        parts.append(f"book pp. {format_pages(book_pages)}")
    return " — ".join(parts)


# ---------------------------------------------------------------------------
# Chunk parsing
# ---------------------------------------------------------------------------

HEADER_KEY_MAP = {
    "document": "document_name",
    "source": "source_file",
    "input pages": "input_pages",
    "section": "section_heading",
    "question": "question",
    "part": "part",
    "kind": "kind",
    "has answer": "has_answer",
    "content tokens": "content_tokens",
    "original source book": "source_book",
    "source book": "source_book",
    "source type": "source_type",
    "legal reference": "legal_reference",
    "book pages": "book_pages",
    "source pdf pages": "pdf_pages",
    "pdf pages": "pdf_pages",
    "citation": "citation_label",
}


@dataclass
class ChunkRecord:
    file: str
    hash: str
    text: str
    document_name: str
    source_file: str
    chunk: str
    section_heading: str
    question: str
    part: str
    kind: str
    source_book: str
    source_type: str
    legal_reference: str
    book_pages: list[int]
    pdf_pages: list[int]
    input_pages: list[int]
    citation_label: str


def split_chunk_header(raw_text: str) -> tuple[dict[str, str], str]:
    """
    Split the human-readable chunk header from its embedded body.

    The separator is exactly the line created by the chunker:
        ---
    """
    separator = re.search(r"(?m)^\s*---\s*$", raw_text)
    if not separator:
        return {}, raw_text.strip()

    header_text = raw_text[:separator.start()].strip()
    body = raw_text[separator.end():].strip()

    headers: dict[str, str] = {}
    for line in header_text.splitlines():
        if line.lstrip().startswith("#"):
            continue

        if ":" not in line:
            continue

        raw_key, value = line.split(":", 1)
        key = HEADER_KEY_MAP.get(raw_key.strip().casefold())
        if key:
            headers[key] = value.strip()

    return headers, body


def extract_chunk_number(stem: str) -> str:
    """Extract the suffix after the final _chunk_ marker."""
    if "_chunk_" not in stem:
        return "0"
    return stem.rsplit("_chunk_", 1)[-1]


def extract_document_name(stem: str) -> str:
    """Remove final _chunk_XXX suffix from a chunk filename."""
    if "_chunk_" not in stem:
        return stem
    return stem.rsplit("_chunk_", 1)[0]


def load_chunk_record(chunk_file: Path, chunk_dir: Path) -> ChunkRecord:
    raw = chunk_file.read_text(encoding="utf-8")
    headers, body = split_chunk_header(raw)
    if not body:
        raise ValueError("Chunk body is empty after metadata header")

    relative_file = chunk_file.relative_to(chunk_dir).as_posix()
    fallback_doc = extract_document_name(chunk_file.stem)

    source_book = headers.get("source_book", "").strip()
    source_type = headers.get("source_type", "general").strip() or "general"
    legal_reference = headers.get("legal_reference", "").strip()
    book_pages = parse_page_spec(headers.get("book_pages"))
    pdf_pages = parse_page_spec(headers.get("pdf_pages"))
    input_pages = parse_page_spec(headers.get("input_pages"))

    citation_label = headers.get("citation_label", "").strip()
    if not citation_label:
        citation_label = create_citation_label(source_book, legal_reference, book_pages)

    return ChunkRecord(
        file=relative_file,
        hash=file_hash(chunk_file),
        text=body,
        document_name=headers.get("document_name", fallback_doc).strip() or fallback_doc,
        source_file=headers.get("source_file", chunk_file.name).strip() or chunk_file.name,
        chunk=extract_chunk_number(chunk_file.stem),
        section_heading=headers.get("section_heading", "").strip(),
        question=headers.get("question", "").strip(),
        part=headers.get("part", "").strip(),
        kind=headers.get("kind", "").strip(),
        source_book=source_book,
        source_type=source_type,
        legal_reference=legal_reference,
        book_pages=book_pages,
        pdf_pages=pdf_pages,
        input_pages=input_pages,
        citation_label=citation_label,
    )


# ---------------------------------------------------------------------------
# Incremental manifest
# ---------------------------------------------------------------------------

class EmbeddingsManifest:
    """Track chunk hashes and Qdrant IDs so changed chunks are re-indexed."""

    def __init__(self, manifest_path: Path):
        self.path = manifest_path
        self.data = self._load()

    @staticmethod
    def _empty() -> dict:
        return {
            "version": "2.0",
            "created_at": now_iso(),
            "last_updated": None,
            "collection": COLLECTION_NAME,
            "indexed_chunks": {},
            "total_indexed": 0,
        }

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()

        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load manifest %s: %s", self.path, exc)
            return self._empty()

        if not isinstance(loaded, dict):
            logger.warning("Manifest root is invalid; starting a new manifest.")
            return self._empty()

        loaded.setdefault("version", "1.0")
        loaded.setdefault("indexed_chunks", {})
        loaded.setdefault("total_indexed", len(loaded["indexed_chunks"]))
        loaded.setdefault("collection", COLLECTION_NAME)
        return loaded

    def save(self) -> None:
        self.data["version"] = "2.0"
        self.data["collection"] = COLLECTION_NAME
        self.data["total_indexed"] = len(self.data["indexed_chunks"])
        self.data["last_updated"] = now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def entry(self, relative_file: str) -> Optional[dict]:
        value = self.data["indexed_chunks"].get(relative_file)
        return value if isinstance(value, dict) else None

    def is_current(self, record: ChunkRecord) -> bool:
        entry = self.entry(record.file)
        return bool(entry and entry.get("hash") == record.hash)

    def upsert(self, record: ChunkRecord, point_id: str) -> None:
        self.data["indexed_chunks"][record.file] = {
            "id": point_id,
            "hash": record.hash,
            "indexed_at": now_iso(),
            "source_book": record.source_book,
            "citation_label": record.citation_label,
        }

    def delete_entries(self, relative_files: Iterable[str]) -> None:
        for relative_file in relative_files:
            self.data["indexed_chunks"].pop(relative_file, None)

    def clear(self) -> None:
        self.data = self._empty()
        self.save()

    def stale_entries(self, existing_relative_files: set[str]) -> dict[str, dict]:
        return {
            path: entry
            for path, entry in self.data["indexed_chunks"].items()
            if path not in existing_relative_files and isinstance(entry, dict)
        }


# ---------------------------------------------------------------------------
# Qdrant and model lifecycle
# ---------------------------------------------------------------------------

_client: Optional[QdrantClient] = None
_model: Optional[BGEM3FlagModel] = None
_reranker: Optional[FlagReranker] = None


def get_client() -> QdrantClient:
    global _client
    if _client is not None:
        return _client

    logger.info("Connecting to Qdrant at %s...", QDRANT_PATH)
    QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    _client = QdrantClient(path=str(QDRANT_PATH))
    _client.get_collections()
    logger.info("Connected to local embedded Qdrant")
    return _client


def close_client() -> None:
    global _client
    if _client is None:
        return
    try:
        _client.close()
    except Exception:
        pass
    finally:
        _client = None


atexit.register(close_client)


def get_model() -> BGEM3FlagModel:
    global _model
    if _model is None:
        logger.info("Loading BGE-M3 embedding model...")
        _model = BGEM3FlagModel(EMBEDDING_MODEL, use_fp16=True)
        _model.return_sparse = True
    return _model


def get_reranker() -> FlagReranker:
    global _reranker
    if _reranker is None:
        logger.info("Loading BGE-Reranker model...")
        _reranker = FlagReranker(RERANKER_MODEL, use_fp16=True)
    return _reranker


def ensure_collection(client: QdrantClient) -> None:
    if not client.collection_exists(COLLECTION_NAME):
        logger.info("Creating collection '%s'...", COLLECTION_NAME)
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )

    # Useful if you later run filtered retrieval in Flask. Older Qdrant versions
    # may not support local payload indexes; indexing still works if this fails.
    for field in ("source_book", "source_type", "legal_reference"):
        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            # "already exists" and older local-client limitations are non-fatal.
            pass


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def iter_chunk_files(chunk_dir: Path) -> list[Path]:
    if not chunk_dir.exists():
        logger.error("Chunk directory not found: %s", chunk_dir)
        return []
    return sorted(chunk_dir.rglob("*_chunk_*.txt"))


def collect_records(
    chunk_dir: Path,
    manifest: EmbeddingsManifest,
    only_source_book: Optional[str],
) -> tuple[list[ChunkRecord], set[str]]:
    """Load new/changed chunk records and return all on-disk relative paths."""
    records: list[ChunkRecord] = []
    on_disk: set[str] = set()

    for path in iter_chunk_files(chunk_dir):
        try:
            record = load_chunk_record(path, chunk_dir)
        except Exception as exc:
            logger.warning("Skipping unreadable chunk %s: %s", path, exc)
            continue

        on_disk.add(record.file)

        if only_source_book and record.source_book != only_source_book:
            continue

        if not manifest.is_current(record):
            records.append(record)

    return records, on_disk


def build_payload(record: ChunkRecord, sparse_embedding: Optional[dict]) -> dict:
    """Create a clean, JSON-serialisable Qdrant payload."""
    payload: dict[str, Any] = {
        # Retrieval body only; chunk header is deliberately excluded.
        "text": record.text,
        "document_name": record.document_name,
        "source_file": record.source_file,
        "chunk": record.chunk,
        "file": record.file,
        "section_heading": record.section_heading,
        "question": record.question,
        "part": record.part,
        "kind": record.kind,

        # Original legal source metadata used by the Web UI.
        "source_book": record.source_book,
        "source_type": record.source_type,
        "legal_reference": record.legal_reference,
        "book_pages": record.book_pages,
        "book_page_range": format_pages(record.book_pages),
        "pdf_pages": record.pdf_pages,
        "pdf_page_range": format_pages(record.pdf_pages),
        "pdf_page_start": min(record.pdf_pages) if record.pdf_pages else None,
        "input_pages": record.input_pages,
        "input_page_range": format_pages(record.input_pages),
        "citation_label": record.citation_label,
    }

    if sparse_embedding is not None:
        try:
            payload["sparse_embedding"] = {
                str(key): float(value)
                for key, value in sparse_embedding.items()
            }
        except Exception as exc:
            logger.warning("Could not serialise sparse embedding for %s: %s", record.file, exc)

    return payload


def delete_points(client: QdrantClient, ids: list[Any]) -> None:
    """Delete old point IDs in manageable batches."""
    if not ids:
        return

    for offset in range(0, len(ids), UPSERT_BATCH_SIZE):
        batch = ids[offset: offset + UPSERT_BATCH_SIZE]
        try:
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=PointIdsList(points=batch),
            )
        except Exception as exc:
            logger.warning("Could not delete %d old Qdrant point(s): %s", len(batch), exc)


def index_new_or_changed_chunks(
    chunk_dir: Path,
    manifest: EmbeddingsManifest,
    *,
    only_source_book: Optional[str] = None,
    prune: bool = False,
) -> int:
    client = get_client()
    ensure_collection(client)

    records, on_disk = collect_records(chunk_dir, manifest, only_source_book)

    if prune:
        stale = manifest.stale_entries(on_disk)
        if only_source_book:
            stale = {
                path: entry for path, entry in stale.items()
                if entry.get("source_book") == only_source_book
            }

        stale_ids = [entry.get("id") for entry in stale.values() if entry.get("id") is not None]
        if stale_ids:
            logger.info("Pruning %d stale point(s) whose files no longer exist...", len(stale_ids))
            delete_points(client, stale_ids)
            manifest.delete_entries(stale.keys())
            manifest.save()

    if not records:
        logger.info("No new or changed chunks to index.")
        return 0

    logger.info("Found %d new/changed chunk(s) to index.", len(records))
    model = get_model()

    try:
        encodings = model.encode(
            [record.text for record in records],
            batch_size=ENCODE_BATCH_SIZE,
            max_length=MAX_LENGTH,
        )
    except Exception as exc:
        logger.error("Embedding encoding failed: %s", exc)
        return 0

    dense_vectors = encodings.get("dense_vecs") if encodings else None
    sparse_vectors = encodings.get("lexical_weights", []) if encodings else []
    if dense_vectors is None or len(dense_vectors) != len(records):
        logger.error("Embedding model returned an invalid dense vector result.")
        return 0

    points: list[PointStruct] = []
    point_records: list[tuple[PointStruct, ChunkRecord]] = []
    obsolete_ids: list[Any] = []

    for index, record in enumerate(records):
        point_id = stable_point_id(record.file)
        old_entry = manifest.entry(record.file)
        if old_entry and old_entry.get("id") != point_id:
            obsolete_ids.append(old_entry.get("id"))

        sparse = sparse_vectors[index] if index < len(sparse_vectors) else None
        payload = build_payload(record, sparse)

        try:
            vector = dense_vectors[index].tolist()
            point = PointStruct(id=point_id, vector=vector, payload=payload)
        except Exception as exc:
            logger.warning("Skipping point for %s: %s", record.file, exc)
            continue

        points.append(point)
        point_records.append((point, record))

    if not points:
        logger.error("No valid Qdrant points could be constructed.")
        return 0

    if obsolete_ids:
        # This handles migration from the old integer-ID manifest scheme.
        delete_points(client, [item for item in obsolete_ids if item is not None])

    logger.info("Upserting %d points...", len(points))
    try:
        for start in tqdm(range(0, len(points), UPSERT_BATCH_SIZE), desc="Upserting"):
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[start:start + UPSERT_BATCH_SIZE],
            )
    except Exception as exc:
        logger.error("Qdrant upsert failed: %s", exc)
        return 0

    for point, record in point_records:
        manifest.upsert(record, str(point.id))
    manifest.save()

    logger.info("Indexed %d new/changed chunk(s) successfully.", len(points))
    return len(points)


# ---------------------------------------------------------------------------
# Retrieval helpers (used by --query and importable by the Flask backend)
# ---------------------------------------------------------------------------

def make_source_filter(source_book: Optional[str]) -> Optional[Filter]:
    """Return a Qdrant filter limiting results to one original source book."""
    if not source_book:
        return None
    return Filter(
        must=[
            FieldCondition(
                key="source_book",
                match=MatchValue(value=source_book),
            )
        ]
    )


def sparse_search(query_sparse: dict, points: Iterable[Any], limit: int = 20) -> list[tuple[Any, float]]:
    scores: list[tuple[Any, float]] = []
    for point in points:
        sparse_payload = point.payload.get("sparse_embedding", {})
        score = sum(
            sparse_payload.get(token, 0.0) * value
            for token, value in query_sparse.items()
            if token in sparse_payload
        )
        scores.append((point.id, score))
    return sorted(scores, key=lambda pair: pair[1], reverse=True)[:limit]


def hybrid_search(
    dense_scores: list[tuple[Any, float]],
    sparse_scores: list[tuple[Any, float]],
    alpha: float = HYBRID_ALPHA,
    k: int = 60,
) -> list[tuple[Any, float]]:
    """Combine dense and sparse rankings with reciprocal-rank fusion."""
    rrf: dict[Any, float] = {}

    for rank, (point_id, _score) in enumerate(dense_scores):
        rrf[point_id] = rrf.get(point_id, 0.0) + alpha / (k + rank + 1)

    for rank, (point_id, _score) in enumerate(sparse_scores):
        rrf[point_id] = rrf.get(point_id, 0.0) + (1.0 - alpha) / (k + rank + 1)

    return sorted(rrf.items(), key=lambda pair: pair[1], reverse=True)


def rerank_results(
    query: str,
    candidate_points: list[Any],
    min_k: int = RERANK_MIN_K,
    max_k: int = RERANK_MAX_K,
    threshold: float = RERANK_THRESHOLD,
) -> list[dict]:
    if not candidate_points:
        return []

    reranker = get_reranker()
    pairs = [[query, point.payload.get("text", "")] for point in candidate_points]
    scores = reranker.compute_score(pairs, normalize=True)

    order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    results: list[dict] = []

    for index in order:
        score = float(scores[index])
        if (score >= threshold and len(results) < max_k) or len(results) < min_k:
            results.append(
                {
                    "point": candidate_points[index],
                    "score": score,
                    "rank": len(results) + 1,
                }
            )
        if len(results) >= max_k:
            break

    return results


def citation_from_payload(payload: dict) -> dict:
    """
    Return the exact source object the Flask API should send to app.js.

    This function intentionally creates one canonical citation per source +
    legal reference + printed page range.
    """
    source_book = payload.get("source_book", "")
    legal_reference = payload.get("legal_reference", "")
    book_pages = payload.get("book_pages", []) or []
    pdf_pages = payload.get("pdf_pages", []) or []
    citation_label = payload.get("citation_label") or create_citation_label(
        source_book, legal_reference, book_pages
    )

    return {
        "document": source_book,
        "source_type": payload.get("source_type", "general"),
        "legal_reference": legal_reference,
        "book_pages": book_pages,
        "book_page_range": payload.get("book_page_range") or format_pages(book_pages),
        "pdf_pages": pdf_pages,
        "pdf_page_start": payload.get("pdf_page_start") or (min(pdf_pages) if pdf_pages else None),
        "citation_label": citation_label,
    }


def deduplicate_citations(results: Iterable[dict]) -> list[dict]:
    """
    Collapse multiple retrieved chunks from the same legal source into one UI item.
    """
    deduped: dict[tuple[str, str, str], dict] = {}

    for item in results:
        payload = item["point"].payload if isinstance(item, dict) else item.payload
        citation = citation_from_payload(payload)

        if not citation["document"]:
            continue

        key = (
            citation["document"],
            citation["legal_reference"],
            citation["book_page_range"],
        )
        deduped.setdefault(key, citation)

    return list(deduped.values())


def run_query_loop(source_book: Optional[str]) -> None:
    client = get_client()
    if not client.collection_exists(COLLECTION_NAME):
        logger.error("Collection '%s' does not exist. Run indexing first.", COLLECTION_NAME)
        return

    model = get_model()
    qdrant_filter = make_source_filter(source_book)

    logger.info("=" * 72)
    logger.info("Ready for queries. Type 'exit' to quit.")
    if source_book:
        logger.info("Source filter: %s", source_book)
    logger.info("=" * 72)

    while True:
        query = input("\nEnter query (or 'exit'): ").strip()
        if query.casefold() == "exit":
            return
        if not query:
            continue

        try:
            encoded = model.encode([query], batch_size=1, max_length=MAX_LENGTH)
            dense = encoded["dense_vecs"][0].tolist()

            lexical = encoded.get("lexical_weights", [])
            query_sparse = dict(lexical[0]) if lexical else {}

            response = client.query_points(
                collection_name=COLLECTION_NAME,
                query=dense,
                query_filter=qdrant_filter,
                limit=20,
            )

            points = list(response.points) if response and response.points else []
            if not points:
                logger.info("No results found.")
                continue

            dense_scores = [(point.id, float(point.score)) for point in points]
            sparse_scores = sparse_search(query_sparse, points, limit=20) if query_sparse else []
            hybrid = hybrid_search(dense_scores, sparse_scores) if sparse_scores else dense_scores

            by_id = {point.id: point for point in points}
            candidates = [by_id[point_id] for point_id, _ in hybrid[:20] if point_id in by_id]

            ranked = rerank_results(query, candidates)
            if not ranked:
                logger.info("No results remained after reranking.")
                continue

            print("\n" + "=" * 72)
            print(f"Results ({len(ranked)} chunks)")
            print("=" * 72)

            for item in ranked:
                point = item["point"]
                payload = point.payload
                citation = citation_from_payload(payload)
                print(f"\n[#{item['rank']}] score={item['score']:.3f}")
                print(f"Question: {payload.get('question') or '(no question metadata)'}")
                print(f"Citation: {citation['citation_label'] or '(no original source metadata)'}")
                print(payload.get("text", "")[:700])

            citations = deduplicate_citations(ranked)
            if citations:
                print("\nUI source objects:")
                print(json.dumps(citations, ensure_ascii=False, indent=2))

        except Exception as exc:
            logger.error("%s: %s", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# Status and command line
# ---------------------------------------------------------------------------

def show_status(chunk_dir: Path, manifest: EmbeddingsManifest) -> None:
    client = get_client()

    logger.info("=" * 72)
    logger.info("Embeddings status")
    logger.info("=" * 72)
    logger.info("Manifest: %s", manifest.path)
    logger.info("Manifest version: %s", manifest.data.get("version"))
    logger.info("Tracked chunks: %s", len(manifest.data.get("indexed_chunks", {})))
    logger.info("Last updated: %s", manifest.data.get("last_updated") or "Never")

    if client.collection_exists(COLLECTION_NAME):
        info = client.get_collection(COLLECTION_NAME)
        logger.info("Collection: %s", COLLECTION_NAME)
        logger.info("Points stored: %s", info.points_count)
        logger.info("Vector size: 1024")
    else:
        logger.info("Collection: %s (not created)", COLLECTION_NAME)

    files = iter_chunk_files(chunk_dir)
    logger.info("Chunk directory: %s", chunk_dir)
    logger.info("Chunk files on disk: %s", len(files))


def recreate_collection(client: QdrantClient, manifest: EmbeddingsManifest) -> None:
    if client.collection_exists(COLLECTION_NAME):
        logger.warning("Deleting collection '%s'...", COLLECTION_NAME)
        client.delete_collection(collection_name=COLLECTION_NAME)
    manifest.clear()
    logger.info("Collection deleted and manifest reset. Re-indexing will now start.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Citation-aware production embeddings pipeline"
    )
    parser.add_argument("--chunk-dir", type=str, default=str(DEFAULT_CHUNK_DIR))
    parser.add_argument("--query", action="store_true", help="Interactive query mode")
    parser.add_argument(
        "--source-book",
        type=str,
        default=None,
        help="Query filter: only search this original source book",
    )
    parser.add_argument(
        "--only-source-book",
        type=str,
        default=None,
        help="Index/prune only chunks whose 'Original source book' matches this value",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete collection and manifest, then rebuild from current chunk files",
    )
    parser.add_argument("--status", action="store_true", help="Show status without loading models")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete manifest-tracked Qdrant points whose chunk files no longer exist",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    chunk_dir = Path(args.chunk_dir).expanduser()
    manifest = EmbeddingsManifest(MANIFEST_FILE)
    client = get_client()

    if args.status:
        show_status(chunk_dir, manifest)
        return 0

    if args.query:
        run_query_loop(args.source_book)
        return 0

    if args.recreate:
        recreate_collection(client, manifest)

    logger.info("=" * 72)
    logger.info("Citation-aware embeddings indexing")
    logger.info("=" * 72)
    logger.info("Chunk directory: %s", chunk_dir)
    logger.info("Collection: %s", COLLECTION_NAME)
    if args.only_source_book:
        logger.info("Index source filter: %s", args.only_source_book)
    logger.info("=" * 72)

    count = index_new_or_changed_chunks(
        chunk_dir,
        manifest,
        only_source_book=args.only_source_book,
        prune=args.prune,
    )

    logger.info("=" * 72)
    if count:
        logger.info("Successfully indexed %d chunk(s).", count)
    else:
        logger.info("Database is already up to date.")
    logger.info("=" * 72)
    logger.info(
        "For RTI-only verification:\n"
        "  python embeddings_production_citations.py --query "
        "--source-book rti-rule-book.pdf"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
