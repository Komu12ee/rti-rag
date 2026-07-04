from __future__ import annotations

"""
Dedicated retrieval against pio_directory_v1.

This module never searches legal collections such as db3 or
cgsic_important_decisions_v1. It reuses the existing rag_pipeline module's
BGE-M3 model and Qdrant client, so Flask has only one embedded-Qdrant handle.
"""

import importlib
import os
from typing import Any, Mapping

from qdrant_client import models


COLLECTION_NAME = os.getenv("PIO_QDRANT_COLLECTION", "pio_directory_v1")
DENSE_VECTOR_NAME = "dense_bge_m3"
SPARSE_VECTOR_NAME = "sparse_bge_m3"


def _to_sparse_vector(weights: Mapping[Any, Any]) -> models.SparseVector:
    pairs = sorted(
        (int(token_id), float(weight))
        for token_id, weight in dict(weights).items()
        if float(weight) > 0.0
    )
    return models.SparseVector(
        indices=[token_id for token_id, _ in pairs],
        values=[weight for _, weight in pairs],
    )


def _build_filter(filters: Mapping[str, str | None] | None) -> models.Filter:
    conditions: list[models.FieldCondition] = [
        models.FieldCondition(
            key="record_type",
            match=models.MatchValue(value="rti_officer_directory"),
        ),
        models.FieldCondition(
            key="is_active",
            match=models.MatchValue(value=True),
        ),
    ]

    for field_name, raw_value in (filters or {}).items():
        value = str(raw_value or "").strip()
        if value:
            conditions.append(
                models.FieldCondition(
                    key=field_name,
                    match=models.MatchValue(value=value),
                )
            )

    return models.Filter(must=conditions)


def _points_from_response(response: Any) -> list[Any]:
    if response is None:
        return []
    return list(getattr(response, "points", None) or [])


def _get_rag_module(rag_module: Any | None) -> Any:
    return rag_module or importlib.import_module("rag_pipeline")


def retrieve_pio_directory_context(
    *,
    query_text: str,
    num_context: int = 5,
    filters: Mapping[str, str | None] | None = None,
    rag_module: Any | None = None,
) -> list[dict[str, Any]]:
    """
    Native dense + sparse RRF search over only pio_directory_v1.

    A dense-only fallback is retained for an older qdrant-client runtime.
    It does not call an LLM and does not re-embed the indexed directory.
    """
    query_text = str(query_text or "").strip()
    if not query_text:
        return []

    limit = max(1, min(int(num_context), 10))
    candidate_limit = max(20, limit * 5)

    rag = _get_rag_module(rag_module)
    rag.ensure_models_loaded()
    client = rag.ensure_qdrant_client()

    if not client.collection_exists(COLLECTION_NAME):
        raise RuntimeError(
            f"PIO Qdrant collection '{COLLECTION_NAME}' was not found. "
            "Check PIO_QDRANT_COLLECTION and the active Qdrant path."
        )

    encoded = rag.model.encode(
        [query_text],
        batch_size=1,
        max_length=512,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )

    dense_values = encoded.get("dense_vecs")
    if dense_values is None or len(dense_values) == 0:
        raise RuntimeError("BGE-M3 did not return a dense query vector.")

    dense_query = dense_values[0].tolist()
    lexical_weights = encoded.get("lexical_weights") or []
    sparse_weights = lexical_weights[0] if lexical_weights else {}
    qdrant_filter = _build_filter(filters)

    try:
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=dense_query,
                    using=DENSE_VECTOR_NAME,
                    filter=qdrant_filter,
                    limit=candidate_limit,
                ),
                models.Prefetch(
                    query=_to_sparse_vector(sparse_weights),
                    using=SPARSE_VECTOR_NAME,
                    filter=qdrant_filter,
                    limit=candidate_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        points = _points_from_response(response)
        search_mode = "dense+sparse_rrf"
    except (AttributeError, TypeError, ValueError) as error:
        # Compatibility path for older qdrant-client versions.
        print(
            "[PIO_QDRANT] Native hybrid query unavailable; "
            f"using dense fallback: {type(error).__name__}: {error}"
        )
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_query,
            using=DENSE_VECTOR_NAME,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        points = _points_from_response(response)
        search_mode = "dense_fallback"

    results: list[dict[str, Any]] = []
    for rank, point in enumerate(points, start=1):
        results.append(
            {
                "rank": rank,
                "score": float(getattr(point, "score", 0.0) or 0.0),
                "payload": dict(getattr(point, "payload", {}) or {}),
                "search_mode": search_mode,
            }
        )

    return results
