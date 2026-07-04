from __future__ import annotations

import re
from typing import Any

from qdrant_client import models


PIO_COLLECTION_NAME = "pio_directory_v1"
DENSE_VECTOR_NAME = "dense_bge_m3"
SPARSE_VECTOR_NAME = "sparse_bge_m3"
DENSE_VECTOR_DIMENSION = 1024


def collection_name() -> str:
    """Return the dedicated officer-directory collection name."""
    import os
    return os.getenv("PIO_QDRANT_COLLECTION", PIO_COLLECTION_NAME).strip() or PIO_COLLECTION_NAME


def compact(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(value: Any) -> str:
    """
    Stable equality key for Qdrant keyword filters.

    Keep spaces rather than removing them. The PostgreSQL parser returns
    canonical human-readable district/department names, so this form matches
    `Public Health and Family Welfare Department` exactly after case-folding.
    """
    return compact(value).casefold()


def build_search_text(record: dict[str, Any]) -> str:
    """Create the multilingual text that BGE-M3 embeds for one directory posting."""
    role = compact(record.get("rti_role")).upper()

    if role == "FAA":
        role_terms = (
            "First Appellate Authority FAA First Appellate Officer "
            "प्रथम अपीलीय अधिकारी प्रथम अपीलीय प्राधिकारी"
        )
    else:
        role_terms = (
            "Public Information Officer PIO जन सूचना अधिकारी "
            "लोक सूचना अधिकारी"
        )

    fields = [
        "Chhattisgarh RTI officer directory.",
        f"RTI role: {role_terms}.",
        f"Officer name: {compact(record.get('officer_name'))}.",
        f"Designation: {compact(record.get('designation'))}.",
        f"Department: {compact(record.get('department_name'))}.",
        f"Office: {compact(record.get('office_name'))}.",
        f"Office section: {compact(record.get('office_section_name'))}.",
        f"District: {compact(record.get('district'))}.",
        f"Office level: {compact(record.get('office_level'))}.",
        f"Address: {compact(record.get('office_address'))}.",
        f"Email: {compact(record.get('email'))}.",
        f"Office code: {compact(record.get('office_code'))}.",
    ]

    return " ".join(
        item for item in fields
        if item and not item.endswith(": .")
    )


def build_payload(
    record: dict[str, Any],
    source_generated_at: str | None = None,
    source_file: str | None = None,
) -> dict[str, Any]:
    """
    Payload is deliberately redundant:
    - exact values are returned to the UI;
    - normalized values are used by keyword filters;
    - search_text is available for audit/debugging.
    """
    department_name = compact(record.get("department_name"))
    district_name = compact(record.get("district"))

    return {
        "record_type": "rti_officer_directory",
        "state": "Chhattisgarh",
        "is_active": bool(record.get("is_active", True)),

        "officer_record_id": compact(record.get("officer_record_id")),
        "office_id": compact(record.get("office_id")),
        "source_serial_no": record.get("source_serial_no"),

        "officer_name": compact(record.get("officer_name")),
        "officer_name_key": normalize_key(record.get("officer_name")),
        "email": compact(record.get("email")),
        "designation_code": compact(record.get("designation_code")),
        "designation": compact(record.get("designation")),

        "rti_role": compact(record.get("rti_role")).upper(),
        "rti_role_original": compact(record.get("rti_role_original")),

        "office_code": compact(record.get("office_code")),
        "office_name": compact(record.get("office_name")),
        "office_address": compact(record.get("office_address")),
        "office_section_name": compact(record.get("office_section_name")),
        "office_level": compact(record.get("office_level")),

        "department_code": compact(record.get("department_code")),
        "department_name": department_name,
        "department_key": normalize_key(department_name),

        "district": district_name,
        "district_key": normalize_key(district_name),

        "source_api": compact(record.get("source_api")),
        "source_file": compact(source_file or record.get("source_file")),
        "source_generated_at": compact(source_generated_at),
        "search_text": build_search_text(record),
    }


def sparse_vector(lexical_weights: dict[Any, Any]) -> models.SparseVector:
    """Convert BGE-M3 lexical weights to Qdrant's native sparse-vector format."""
    pairs = sorted(
        (int(token_id), float(weight))
        for token_id, weight in dict(lexical_weights or {}).items()
        if float(weight) > 0.0
    )
    return models.SparseVector(
        indices=[token_id for token_id, _ in pairs],
        values=[weight for _, weight in pairs],
    )


def ensure_collection(
    client,
    recreate: bool = False,
) -> str:
    """
    Create only the PIO directory collection.

    Legal collections such as db3 and cgsic_important_decisions_v1 are never
    changed by this function.
    """
    name = collection_name()

    if client.collection_exists(name) and recreate:
        client.delete_collection(name)

    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=DENSE_VECTOR_DIMENSION,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams()
            },
        )

    # Exact metadata filters are essential for district/department safety.
    for field_name in (
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
    ):
        client.create_payload_index(
            collection_name=name,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )

    client.create_payload_index(
        collection_name=name,
        field_name="is_active",
        field_schema=models.PayloadSchemaType.BOOL,
        wait=True,
    )

    return name
