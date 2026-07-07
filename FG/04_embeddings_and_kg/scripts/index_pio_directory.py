"""
Create the PIO / FAA hybrid-search Qdrant collection.

This script creates ONE NEW collection:
    pio_directory_v1

It does NOT change or delete your legal Qdrant collections:
    db3
    cgsic_important_decisions_v1

Run from: 05_webui

Examples:
    python .\scripts\index_pio_directory.py `
      --data "C:\path\to\officers_clean_latest.json" `
      --recreate

    python .\scripts\index_pio_directory.py --status

Requirements:
    pip install -U "qdrant-client>=1.14" FlagEmbedding torch python-dotenv
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import torch
    from dotenv import load_dotenv
    from FlagEmbedding import BGEM3FlagModel
    from qdrant_client import QdrantClient, models
except ImportError as error:
    raise SystemExit(
        "Missing dependency: "
        f"{error}\n\n"
        "Install:\n"
        'pip install -U "qdrant-client>=1.14" FlagEmbedding torch python-dotenv'
    )


# ───────────────────────────────────────────────────────────────
# Project / Qdrant configuration
# ───────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]  # .../CHiPS-RTI-Project
WEBUI_DIR = PROJECT_ROOT / "05_webui"

# Uses the same .env file that Flask / rag_pipeline.py uses.
load_dotenv(WEBUI_DIR / ".env")

COLLECTION_NAME = os.getenv("PIO_QDRANT_COLLECTION", "pio_directory_v1")
DENSE_VECTOR_NAME = "dense_bge_m3"
SPARSE_VECTOR_NAME = "sparse_bge_m3"
DENSE_VECTOR_SIZE = 1024
MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    str(PROJECT_ROOT / "models" / "bge-m3"),
)

DEFAULT_BATCH_SIZE = int(os.getenv("PIO_INDEX_BATCH_SIZE", "24"))
DEFAULT_UPSERT_BATCH_SIZE = int(os.getenv("PIO_UPSERT_BATCH_SIZE", "128"))


# ───────────────────────────────────────────────────────────────
# Text / payload preparation
# ───────────────────────────────────────────────────────────────

def clean(value: Any) -> str:
    """Safely normalize portal text without destroying Hindi."""
    text = "" if value is None else str(value)
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    return re.sub(r"\s+", " ", text).strip()


def key(value: Any) -> str:
    """Stable lowercase value for Qdrant keyword filters."""
    return clean(value).casefold()


def role_words(role: str) -> str:
    if role == "PIO":
        return (
            "Public Information Officer PIO "
            "जन सूचना अधिकारी लोक सूचना अधिकारी"
        )

    return (
        "First Appellate Authority FAA First Appellate Officer "
        "प्रथम अपीलीय प्राधिकारी प्रथम अपीलीय अधिकारी"
    )


def build_search_text(record: dict[str, Any]) -> str:
    """
    Dense BGE-M3 understands meaning; sparse BGE-M3 preserves exact terms.

    This intentionally contains both English and Hindi role vocabulary because
    the directory itself is multilingual.
    """
    role = clean(record.get("rti_role"))

    fields = [
        "Chhattisgarh RTI officer directory.",
        f"Officer role: {role_words(role)}.",
        f"Officer name: {clean(record.get('officer_name'))}.",
        f"Designation: {clean(record.get('designation'))}.",
        f"Department: {clean(record.get('department_name'))}.",
        f"Office: {clean(record.get('office_name'))}.",
        f"Office section: {clean(record.get('office_section_name'))}.",
        f"District: {clean(record.get('district'))}.",
        f"Office level: {clean(record.get('office_level'))}.",
        f"Address: {clean(record.get('office_address'))}.",
        f"Email: {clean(record.get('email'))}.",
        f"Office code: {clean(record.get('office_code'))}.",
    ]
    return " ".join(part for part in fields if not part.endswith(": ."))


def build_payload(
    record: dict[str, Any],
    source_generated_at: str,
) -> dict[str, Any]:
    """
    Store all answer fields in payload. The chatbot can answer directly from
    Qdrant after PostgreSQL has no exact result; it does not need a second DB
    lookup to display name, office, department, district, email, or address.
    """
    return {
        "record_type": "rti_officer_directory",
        "state": "Chhattisgarh",
        "is_active": bool(record.get("is_active")),

        "officer_record_id": clean(record.get("officer_record_id")),
        "office_id": clean(record.get("office_id")),
        "source_serial_no": record.get("source_serial_no"),

        "officer_name": clean(record.get("officer_name")),
        "officer_name_key": key(record.get("officer_name")),
        "email": clean(record.get("email")),
        "designation_code": clean(record.get("designation_code")),
        "designation": clean(record.get("designation")),

        "rti_role": clean(record.get("rti_role")),
        "rti_role_original": clean(record.get("rti_role_original")),

        "office_code": clean(record.get("office_code")),
        "office_name": clean(record.get("office_name")),
        "office_address": clean(record.get("office_address")),
        "office_section_name": clean(record.get("office_section_name")),
        "office_level": clean(record.get("office_level")),

        "department_code": clean(record.get("department_code")),
        "department_name": clean(record.get("department_name")),
        "department_key": key(
            record.get("department_key") or record.get("department_name")
        ),

        "district": clean(record.get("district")),
        "district_key": key(
            record.get("district_key") or record.get("district")
        ),

        "source_api": clean(record.get("source_api")),
        "source_file": clean(record.get("source_file")),
        "source_generated_at": source_generated_at,

        "search_text": build_search_text(record),
    }


def sparse_vector(weights: dict[Any, Any]) -> models.SparseVector:
    """
    BGE-M3 lexical output is {token_id: weight}.
    Qdrant requires sorted integer indices and matching float values.
    """
    pairs = sorted(
        (int(token_id), float(weight))
        for token_id, weight in dict(weights).items()
        if float(weight) > 0.0
    )

    return models.SparseVector(
        indices=[token_id for token_id, _ in pairs],
        values=[weight for _, weight in pairs],
    )


# ───────────────────────────────────────────────────────────────
# Qdrant setup
# ───────────────────────────────────────────────────────────────

def get_qdrant_client() -> QdrantClient:
    """
    Matches your rag_pipeline.py configuration:
    - QDRANT_MODE=local  → embedded storage
    - QDRANT_MODE=remote → host/port/API key
    """
    mode = os.getenv("QDRANT_MODE", "local").strip().casefold()

    if mode == "remote":
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        api_key = os.getenv("QDRANT_API_KEY") or None
        timeout = int(os.getenv("QDRANT_TIMEOUT", "60"))

        print(f"Connecting to remote Qdrant: {host}:{port}")
        client = QdrantClient(
            host=host,
            port=port,
            api_key=api_key,
            timeout=timeout,
        )
        client.get_collections()
        return client

    local_path = Path(
        os.getenv(
            "CHIPPY_QDRANT_LOCAL_PATH",
            str(PROJECT_ROOT / "04_embeddings_and_kg" / "db" / "qdrant_local"),
        )
    )
    local_path.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to embedded Qdrant: {local_path}")
    print("Important: Flask must be stopped while this script runs.")
    client = QdrantClient(path=str(local_path))
    client.get_collections()
    return client


def create_or_validate_collection(
    client: QdrantClient,
    recreate: bool,
) -> None:
    exists = client.collection_exists(COLLECTION_NAME)

    if exists and recreate:
        print(f"Deleting only '{COLLECTION_NAME}'...")
        client.delete_collection(COLLECTION_NAME)
        exists = False

    if not exists:
        print(f"Creating hybrid collection '{COLLECTION_NAME}'...")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=DENSE_VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams()
            },
        )
    else:
        info = client.get_collection(COLLECTION_NAME)
        names = set((info.config.params.vectors or {}).keys())
        if DENSE_VECTOR_NAME not in names:
            raise RuntimeError(
                f"Collection '{COLLECTION_NAME}' already exists but does not "
                f"have vector '{DENSE_VECTOR_NAME}'. Run again with --recreate."
            )

    # Keyword indexes make district / department / role filtering fast.
    keyword_fields = [
        "record_type",
        "state",
        "officer_record_id",
        "office_id",
        "officer_name_key",
        "designation_code",
        "rti_role",
        "office_code",
        "office_level",
        "department_code",
        "department_key",
        "district_key",
    ]
    for field in keyword_fields:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )

    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="is_active",
        field_schema=models.PayloadSchemaType.BOOL,
        wait=True,
    )


# ───────────────────────────────────────────────────────────────
# Loading / indexing
# ───────────────────────────────────────────────────────────────

def load_records(data_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with data_path.open("r", encoding="utf-8") as f:
        source = json.load(f)

    records = source.get("records")
    if not isinstance(records, list):
        raise ValueError(
            "Expected a JSON object containing a top-level 'records' list."
        )

    # Deterministic indexing: one point for each stable official record ID.
    unique: dict[str, dict[str, Any]] = {}
    ignored = 0

    for record in records:
        if not bool(record.get("is_active")):
            ignored += 1
            continue

        record_id = clean(record.get("officer_record_id"))
        if not record_id:
            ignored += 1
            continue

        unique[record_id] = record

    output = list(unique.values())

    print(f"Source records: {len(records):,}")
    print(f"Active unique records to index: {len(output):,}")
    if ignored:
        print(f"Skipped inactive / missing-ID records: {ignored:,}")

    return output, dict(source.get("metadata") or {})


def build_model() -> BGEM3FlagModel:
    use_fp16 = bool(torch.cuda.is_available())
    print(f"Loading {MODEL_NAME} (CUDA fp16={use_fp16})...")
    return BGEM3FlagModel(MODEL_NAME, use_fp16=use_fp16)


def index_records(
    client: QdrantClient,
    records: list[dict[str, Any]],
    source_generated_at: str,
    batch_size: int,
    upsert_batch_size: int,
) -> None:
    model = build_model()
    total = len(records)
    indexed = 0

    for start in range(0, total, batch_size):
        batch = records[start : start + batch_size]
        texts = [build_search_text(record) for record in batch]

        encoded = model.encode(
            texts,
            batch_size=batch_size,
            max_length=512,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

        dense_vectors = encoded["dense_vecs"]
        sparse_weights = encoded["lexical_weights"]

        points: list[models.PointStruct] = []

        for record, dense, sparse in zip(batch, dense_vectors, sparse_weights):
            # Qdrant point IDs must be unsigned integers or UUID values.
            # UUID5 makes re-indexing the same official record idempotent.
            point_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    clean(record["officer_record_id"]),
                )
            )

            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={
                        DENSE_VECTOR_NAME: dense.tolist(),
                        SPARSE_VECTOR_NAME: sparse_vector(sparse),
                    },
                    payload=build_payload(record, source_generated_at),
                )
            )

        for point_start in range(0, len(points), upsert_batch_size):
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[point_start : point_start + upsert_batch_size],
                wait=True,
            )

        indexed += len(points)
        print(f"Indexed {indexed:,}/{total:,}", flush=True)


def show_status(client: QdrantClient) -> None:
    print(f"\nQdrant collection: {COLLECTION_NAME}")

    if not client.collection_exists(COLLECTION_NAME):
        print("Status: NOT CREATED")
        return

    info = client.get_collection(COLLECTION_NAME)
    print("Status: EXISTS")
    print(f"Points: {info.points_count:,}")
    print(f"Vectors: {list((info.config.params.vectors or {}).keys())}")
    print("Sparse vector: sparse_bge_m3")

    # Payload filters are checked by reading a few stored records.
    response = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=3,
        with_payload=[
            "officer_name",
            "rti_role",
            "department_name",
            "district",
            "office_name",
            "email",
        ],
        with_vectors=False,
    )
    points = response[0] if isinstance(response, tuple) else response.points

    if points:
        print("\nSample records:")
        for point in points:
            payload = point.payload or {}
            print(
                f"- {payload.get('rti_role')} | "
                f"{payload.get('officer_name') or 'Name not listed'} | "
                f"{payload.get('department_name')} | "
                f"{payload.get('district')}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build PIO/FAA hybrid Qdrant directory collection."
    )
    parser.add_argument(
        "--data",
        type=Path,
        help="Path to officers_clean_latest.json",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and rebuild only pio_directory_v1.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show whether pio_directory_v1 exists and its point count.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"BGE-M3 embedding batch size (default {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--upsert-batch-size",
        type=int,
        default=DEFAULT_UPSERT_BATCH_SIZE,
        help=f"Qdrant upsert batch size (default {DEFAULT_UPSERT_BATCH_SIZE}).",
    )
    args = parser.parse_args()

    if args.status and args.data:
        parser.error("Use either --status or --data, not both.")

    if not args.status and args.data is None:
        parser.error("--data is required unless --status is used.")

    if args.batch_size < 1 or args.upsert_batch_size < 1:
        parser.error("Batch sizes must be at least 1.")

    client = get_qdrant_client()

    try:
        if args.status:
            show_status(client)
            return

        if not args.data.exists():
            raise FileNotFoundError(f"Officer JSON not found: {args.data}")

        records, metadata = load_records(args.data)
        role_counts = Counter(clean(r.get("rti_role")) for r in records)

        print(
            "Role counts: "
            + ", ".join(
                f"{role or 'UNKNOWN'}={count:,}"
                for role, count in sorted(role_counts.items())
            )
        )

        create_or_validate_collection(client, recreate=args.recreate)

        source_generated_at = clean(metadata.get("generated_at_utc"))
        index_records(
            client=client,
            records=records,
            source_generated_at=source_generated_at,
            batch_size=args.batch_size,
            upsert_batch_size=args.upsert_batch_size,
        )

        print("\nIndexing completed.")
        show_status(client)

    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"\nERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
