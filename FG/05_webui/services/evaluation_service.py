from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from services.llm_provider import (
    LLMProviderError,
    capture_llm_usage,
    current_llm_model_name,
    generate_text,
)
from services.postgres_db import get_connection


ALLOWED_CHUNKING_STRATEGIES = {
    "current",
    "fixed_size",
    "recursive",
    "semantic",
    "page_wise",
    "model_assisted",
    "parent_child",
}
ALLOWED_RETRIEVAL_MODES = {"dense", "sparse", "hybrid"}
ALLOWED_VERSION_TYPES = {"chunking", "embedding", "retrieval", "reranker", "prompt", "llm"}
MAX_BENCHMARK_CASES = max(1, int(os.getenv("RAG_EVAL_MAX_CASES", "1000")))


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS rag_eval_datasets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_eval_cases (
        id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL REFERENCES rag_eval_datasets(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        question TEXT NOT NULL,
        expected_answer TEXT NOT NULL DEFAULT '',
        relevant_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
        expected_citations JSONB NOT NULL DEFAULT '[]'::jsonb,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(dataset_id, ordinal)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_eval_experiments (
        id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL REFERENCES rag_eval_datasets(id) ON DELETE CASCADE,
        baseline_experiment_id TEXT REFERENCES rag_eval_experiments(id) ON DELETE SET NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
        config JSONB NOT NULL,
        aggregate_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        error TEXT NOT NULL DEFAULT ''
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_eval_results (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES rag_eval_experiments(id) ON DELETE CASCADE,
        case_id TEXT NOT NULL REFERENCES rag_eval_cases(id) ON DELETE CASCADE,
        actual_answer TEXT NOT NULL DEFAULT '',
        route TEXT NOT NULL DEFAULT '',
        retrieved_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
        actual_citations JSONB NOT NULL DEFAULT '[]'::jsonb,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
        token_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
        estimated_cost_inr DOUBLE PRECISION NOT NULL DEFAULT 0,
        failure_cluster TEXT NOT NULL DEFAULT '',
        failure_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
        judge_details JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(experiment_id, case_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_eval_human_reviews (
        id TEXT PRIMARY KEY,
        result_id TEXT NOT NULL REFERENCES rag_eval_results(id) ON DELETE CASCADE,
        reviewer TEXT NOT NULL,
        relevance SMALLINT NOT NULL CHECK (relevance BETWEEN 1 AND 5),
        faithfulness SMALLINT NOT NULL CHECK (faithfulness BETWEEN 1 AND 5),
        citation_correctness SMALLINT NOT NULL CHECK (citation_correctness BETWEEN 1 AND 5),
        completeness SMALLINT NOT NULL CHECK (completeness BETWEEN 1 AND 5),
        notes TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(result_id, reviewer)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_eval_versions (
        id TEXT PRIMARY KEY,
        version_type TEXT NOT NULL,
        name TEXT NOT NULL,
        version TEXT NOT NULL,
        config JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(version_type, name, version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_eval_alerts (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES rag_eval_experiments(id) ON DELETE CASCADE,
        severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
        alert_type TEXT NOT NULL,
        message TEXT NOT NULL,
        metric_name TEXT NOT NULL DEFAULT '',
        current_value DOUBLE PRECISION,
        baseline_value DOUBLE PRECISION,
        acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS rag_eval_cases_dataset_idx ON rag_eval_cases(dataset_id, ordinal);",
    "CREATE INDEX IF NOT EXISTS rag_eval_experiments_dataset_idx ON rag_eval_experiments(dataset_id, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS rag_eval_results_experiment_idx ON rag_eval_results(experiment_id, created_at);",
    "CREATE INDEX IF NOT EXISTS rag_eval_alerts_experiment_idx ON rag_eval_alerts(experiment_id, created_at DESC);",
)


QUALITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "context_relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "faithfulness": {"type": "number", "minimum": 0, "maximum": 1},
        "citation_correctness": {"type": "number", "minimum": 0, "maximum": 1},
        "answer_completeness": {"type": "number", "minimum": 0, "maximum": 1},
        "hallucination_score": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": [
        "context_relevance",
        "faithfulness",
        "citation_correctness",
        "answer_completeness",
        "hallucination_score",
        "reason",
    ],
    "additionalProperties": False,
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _public_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: _public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    return value


def _row(value: dict[str, Any] | None) -> dict[str, Any] | None:
    return _public_value(dict(value)) if value else None


def ensure_evaluation_schema() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        text = str(value).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            separator = "|" if "|" in text else ";" if ";" in text else None
            items = text.split(separator) if separator else [text]
        else:
            items = parsed if isinstance(parsed, list) else [parsed]
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def _parse_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"notes": text}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def normalise_case(raw: dict[str, Any], ordinal: int) -> dict[str, Any]:
    question = str(raw.get("question") or raw.get("query") or "").strip()
    if not question:
        raise ValueError(f"Benchmark row {ordinal} has no question.")
    expected_answer = str(
        raw.get("expected_answer")
        or raw.get("ground_truth")
        or raw.get("answer")
        or ""
    ).strip()
    relevant_documents = _parse_list(
        raw.get("relevant_documents")
        or raw.get("relevant_docs")
        or raw.get("documents")
    )
    expected_citations = _parse_list(
        raw.get("expected_citations")
        or raw.get("citations")
    )
    metadata = _parse_metadata(raw.get("metadata"))
    for key in ("expected_route", "language", "category", "tags"):
        if raw.get(key) not in (None, ""):
            metadata[key] = raw.get(key)
    return {
        "question": question,
        "expected_answer": expected_answer,
        "relevant_documents": relevant_documents,
        "expected_citations": expected_citations,
        "metadata": metadata,
    }


def parse_benchmark_file(filename: str, content: bytes) -> list[dict[str, Any]]:
    if not content:
        raise ValueError("Benchmark file is empty.")
    suffix = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    text = content.decode("utf-8-sig")
    if suffix == "csv":
        rows = list(csv.DictReader(io.StringIO(text)))
    elif suffix == "json":
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            rows = parsed.get("cases") or parsed.get("items") or []
        else:
            rows = parsed
        if not isinstance(rows, list):
            raise ValueError("JSON benchmark must be a list or contain a 'cases' list.")
    else:
        raise ValueError("Benchmark must be a UTF-8 CSV or JSON file.")
    if not rows:
        raise ValueError("Benchmark contains no cases.")
    if len(rows) > MAX_BENCHMARK_CASES:
        raise ValueError(f"Benchmark exceeds the limit of {MAX_BENCHMARK_CASES} cases.")
    cases = []
    for ordinal, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Benchmark row {ordinal} must be an object.")
        cases.append(normalise_case(raw, ordinal))
    return cases


def create_dataset(
    name: str,
    description: str,
    cases: list[dict[str, Any]],
    created_by: str,
) -> dict[str, Any]:
    ensure_evaluation_schema()
    name = str(name or "").strip()
    if not 2 <= len(name) <= 160:
        raise ValueError("Dataset name must contain 2 to 160 characters.")
    dataset_id = str(uuid4())
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rag_eval_datasets(id, name, description, created_by)
                VALUES (%s, %s, %s, %s)
                RETURNING *;
                """,
                (dataset_id, name, str(description or "").strip()[:2000], created_by),
            )
            dataset = dict(cursor.fetchone())
            for ordinal, case in enumerate(cases, start=1):
                cursor.execute(
                    """
                    INSERT INTO rag_eval_cases(
                        id, dataset_id, ordinal, question, expected_answer,
                        relevant_documents, expected_citations, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb);
                    """,
                    (
                        str(uuid4()), dataset_id, ordinal, case["question"],
                        case["expected_answer"], _json(case["relevant_documents"]),
                        _json(case["expected_citations"]), _json(case["metadata"]),
                    ),
                )
    dataset["case_count"] = len(cases)
    return _row(dataset) or {}


def list_datasets() -> list[dict[str, Any]]:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT d.*, COUNT(c.id)::int AS case_count
                FROM rag_eval_datasets d
                LEFT JOIN rag_eval_cases c ON c.dataset_id = d.id
                GROUP BY d.id
                ORDER BY d.created_at DESC;
                """
            )
            return [_row(dict(item)) or {} for item in cursor.fetchall()]


def get_dataset(dataset_id: str, include_cases: bool = True) -> dict[str, Any] | None:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM rag_eval_datasets WHERE id = %s;",
                (dataset_id,),
            )
            dataset = _row(cursor.fetchone())
            if not dataset:
                return None
            cursor.execute(
                "SELECT COUNT(*)::int AS count FROM rag_eval_cases WHERE dataset_id = %s;",
                (dataset_id,),
            )
            dataset["case_count"] = int(cursor.fetchone()["count"])
            if include_cases:
                cursor.execute(
                    "SELECT * FROM rag_eval_cases WHERE dataset_id = %s ORDER BY ordinal;",
                    (dataset_id,),
                )
                dataset["cases"] = [_row(dict(item)) or {} for item in cursor.fetchall()]
            return dataset


def delete_dataset(dataset_id: str) -> bool:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM rag_eval_datasets WHERE id = %s;", (dataset_id,))
            return cursor.rowcount > 0


def normalise_experiment_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    chunking = str(raw.get("chunking_strategy") or "current").strip().casefold()
    retrieval = str(raw.get("retrieval_mode") or "hybrid").strip().casefold()
    if chunking not in ALLOWED_CHUNKING_STRATEGIES:
        raise ValueError(f"Unsupported chunking strategy: {chunking}")
    if retrieval not in ALLOWED_RETRIEVAL_MODES:
        raise ValueError(f"Unsupported retrieval mode: {retrieval}")
    collections = _parse_list(raw.get("collection_names"))
    top_k = max(1, min(int(raw.get("top_k") or 5), 20))
    candidate_k = max(top_k, min(int(raw.get("candidate_k") or 20), 100))
    return {
        "chunking_strategy": chunking,
        "chunk_size": max(64, min(int(raw.get("chunk_size") or 512), 8192)),
        "chunk_overlap": max(0, min(int(raw.get("chunk_overlap") or 64), 2048)),
        "embedding_model": str(raw.get("embedding_model") or "BAAI/bge-m3").strip()[:240],
        "retrieval_mode": retrieval,
        "collection_names": collections,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "hybrid_alpha": max(0.0, min(float(raw.get("hybrid_alpha", 0.6)), 1.0)),
        "reranker_enabled": _as_bool(raw.get("reranker_enabled"), False),
        "reranker_model": str(raw.get("reranker_model") or "BAAI/bge-reranker-v2-m3").strip()[:240],
        "use_kg": _as_bool(raw.get("use_kg"), True),
        "use_multi_query": _as_bool(raw.get("use_multi_query"), True),
        "prompt_version": str(raw.get("prompt_version") or "current").strip()[:120],
        "prompt_instruction": str(raw.get("prompt_instruction") or "").strip()[:4000],
        "model_version": str(raw.get("model_version") or current_llm_model_name()).strip()[:120],
        "judge_enabled": _as_bool(raw.get("judge_enabled"), True),
        "judge_model": str(raw.get("judge_model") or current_llm_model_name()).strip()[:120],
        "notes": str(raw.get("notes") or "").strip()[:2000],
    }


def _register_experiment_versions(config: dict[str, Any], created_by: str) -> None:
    records = (
        ("chunking", config["chunking_strategy"], str(config["chunk_size"]), {
            "overlap": config["chunk_overlap"], "collections": config["collection_names"]
        }),
        ("embedding", config["embedding_model"], "current", {}),
        ("retrieval", config["retrieval_mode"], "current", {
            "top_k": config["top_k"], "candidate_k": config["candidate_k"]
        }),
        ("reranker", config["reranker_model"], "enabled" if config["reranker_enabled"] else "disabled", {}),
        ("prompt", "answer_prompt", config["prompt_version"], {}),
        ("llm", config["model_version"], config["model_version"], {}),
    )
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for version_type, name, version, details in records:
                cursor.execute(
                    """
                    INSERT INTO rag_eval_versions(id, version_type, name, version, config, created_by)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT(version_type, name, version) DO NOTHING;
                    """,
                    (str(uuid4()), version_type, name, version, _json(details), created_by),
                )


def create_experiment(
    dataset_id: str,
    name: str,
    config: dict[str, Any] | None,
    created_by: str,
    baseline_experiment_id: str | None = None,
) -> dict[str, Any]:
    ensure_evaluation_schema()
    dataset = get_dataset(dataset_id, include_cases=False)
    if not dataset:
        raise ValueError("Benchmark dataset was not found.")
    config = normalise_experiment_config(config)
    experiment_id = str(uuid4())
    name = str(name or "").strip()
    if not 2 <= len(name) <= 160:
        raise ValueError("Experiment name must contain 2 to 160 characters.")
    if baseline_experiment_id:
        baseline = get_experiment(baseline_experiment_id, include_results=False)
        if not baseline or baseline["status"] != "COMPLETED":
            raise ValueError("Baseline experiment must exist and be completed.")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rag_eval_experiments(
                    id, dataset_id, baseline_experiment_id, name, status,
                    config, created_by
                ) VALUES (%s, %s, %s, %s, 'QUEUED', %s::jsonb, %s)
                RETURNING *;
                """,
                (experiment_id, dataset_id, baseline_experiment_id, name, _json(config), created_by),
            )
            experiment = _row(cursor.fetchone()) or {}
    _register_experiment_versions(config, created_by)
    return experiment


def set_experiment_running(experiment_id: str) -> None:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE rag_eval_experiments
                SET status = 'RUNNING', started_at = NOW(), completed_at = NULL, error = ''
                WHERE id = %s AND status = 'QUEUED';
                """,
                (experiment_id,),
            )


def fail_experiment(experiment_id: str, error: str) -> None:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE rag_eval_experiments
                SET status = 'FAILED', error = %s, completed_at = NOW()
                WHERE id = %s;
                """,
                (str(error or "Unknown experiment failure")[:4000], experiment_id),
            )


def get_experiment(experiment_id: str, include_results: bool = True) -> dict[str, Any] | None:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.*, d.name AS dataset_name,
                    (SELECT COUNT(*) FROM rag_eval_cases c WHERE c.dataset_id = e.dataset_id)::int AS case_count,
                    (SELECT COUNT(*) FROM rag_eval_results r WHERE r.experiment_id = e.id)::int AS completed_cases
                FROM rag_eval_experiments e
                JOIN rag_eval_datasets d ON d.id = e.dataset_id
                WHERE e.id = %s;
                """,
                (experiment_id,),
            )
            experiment = _row(cursor.fetchone())
            if not experiment:
                return None
            if include_results:
                cursor.execute(
                    """
                    SELECT r.*, c.ordinal, c.question, c.expected_answer,
                           c.relevant_documents, c.expected_citations, c.metadata,
                           COALESCE((
                               SELECT jsonb_build_object(
                                   'count', COUNT(*),
                                   'relevance', AVG(h.relevance),
                                   'faithfulness', AVG(h.faithfulness),
                                   'citation_correctness', AVG(h.citation_correctness),
                                   'completeness', AVG(h.completeness)
                               ) FROM rag_eval_human_reviews h WHERE h.result_id = r.id
                           ), '{}'::jsonb) AS human_review
                    FROM rag_eval_results r
                    JOIN rag_eval_cases c ON c.id = r.case_id
                    WHERE r.experiment_id = %s
                    ORDER BY c.ordinal;
                    """,
                    (experiment_id,),
                )
                experiment["results"] = [_row(dict(item)) or {} for item in cursor.fetchall()]
            return experiment


def list_experiments(limit: int = 100) -> list[dict[str, Any]]:
    ensure_evaluation_schema()
    limit = max(1, min(int(limit), 500))
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.*, d.name AS dataset_name,
                    (SELECT COUNT(*) FROM rag_eval_cases c WHERE c.dataset_id = e.dataset_id)::int AS case_count,
                    (SELECT COUNT(*) FROM rag_eval_results r WHERE r.experiment_id = e.id)::int AS completed_cases
                FROM rag_eval_experiments e
                JOIN rag_eval_datasets d ON d.id = e.dataset_id
                ORDER BY e.created_at DESC
                LIMIT %s;
                """,
                (limit,),
            )
            return [_row(dict(item)) or {} for item in cursor.fetchall()]


def experiment_cases(experiment_id: str) -> list[dict[str, Any]]:
    experiment = get_experiment(experiment_id, include_results=False)
    if not experiment:
        raise ValueError("Experiment was not found.")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM rag_eval_cases WHERE dataset_id = %s ORDER BY ordinal;",
                (experiment["dataset_id"],),
            )
            return [_row(dict(item)) or {} for item in cursor.fetchall()]


def _normalise_identifier(value: Any) -> str:
    return " ".join(re.findall(r"[^\W_]+", str(value or "").casefold(), flags=re.UNICODE))


def _document_identifiers(document: dict[str, Any]) -> list[str]:
    values = []
    for key in ("document_id", "source", "actual_pdf", "retrieval_collection", "office_code", "email"):
        value = document.get(key)
        if value:
            values.append(_normalise_identifier(value))
    return [item for item in values if item]


def _identifier_matches(expected: str, document: dict[str, Any]) -> bool:
    expected_key = _normalise_identifier(expected)
    if not expected_key:
        return False
    for actual_key in _document_identifiers(document):
        if expected_key == actual_key:
            return True
        shorter, longer = sorted((expected_key, actual_key), key=len)
        if len(shorter) >= 4 and shorter in longer:
            return True
    return False


def retrieval_metrics(
    relevant_documents: list[str],
    retrieved_documents: list[dict[str, Any]],
    k: int,
) -> dict[str, float]:
    k = max(1, int(k))
    expected = list(dict.fromkeys(item for item in relevant_documents if str(item).strip()))
    top = list(retrieved_documents[:k])
    relevance = [any(_identifier_matches(item, doc) for item in expected) for doc in top]
    found_expected = sum(
        1 for item in expected if any(_identifier_matches(item, doc) for doc in top)
    )
    precision = sum(relevance) / k
    recall = found_expected / len(expected) if expected else 1.0
    reciprocal_rank = next((1.0 / rank for rank, hit in enumerate(relevance, 1) if hit), 0.0)
    dcg = sum((1.0 if hit else 0.0) / math.log2(rank + 1) for rank, hit in enumerate(relevance, 1))
    ideal_hits = min(len(expected), k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    ndcg = dcg / ideal_dcg if ideal_dcg else 1.0
    return {
        f"precision_at_{k}": round(precision, 6),
        f"recall_at_{k}": round(recall, 6),
        "mrr": round(reciprocal_rank, 6),
        "ndcg": round(ndcg, 6),
    }


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[^\W_]{2,}", str(value or "").casefold(), flags=re.UNICODE)
        if token not in {"the", "and", "for", "with", "from", "this", "that", "are", "was"}
    }


def _coverage(reference: str, candidate: str) -> float:
    expected = _tokens(reference)
    if not expected:
        return 1.0
    return len(expected & _tokens(candidate)) / len(expected)


def fallback_quality_metrics(
    question: str,
    expected_answer: str,
    actual_answer: str,
    retrieved_documents: list[dict[str, Any]],
    expected_citations: list[str],
    actual_citations: list[str] | None = None,
) -> dict[str, float]:
    context = "\n".join(str(item.get("text") or item.get("content") or "") for item in retrieved_documents)
    answer_tokens = _tokens(actual_answer)
    support_tokens = _tokens(context)
    faithfulness = len(answer_tokens & support_tokens) / len(answer_tokens) if answer_tokens else 0.0
    context_relevance = _coverage(question, context)
    completeness = _coverage(expected_answer, actual_answer) if expected_answer else min(1.0, len(answer_tokens) / 20.0)
    if expected_citations:
        citation_documents = [
            {"source": citation}
            for citation in (actual_citations or [])
        ]
        citation_hits = sum(
            1 for citation in expected_citations
            if any(_identifier_matches(citation, doc) for doc in citation_documents)
        )
        citation_correctness = citation_hits / len(expected_citations)
    else:
        citation_correctness = 1.0 if (actual_citations or retrieved_documents) else 0.0
    return {
        "context_relevance": round(context_relevance, 6),
        "faithfulness": round(faithfulness, 6),
        "citation_correctness": round(citation_correctness, 6),
        "answer_completeness": round(completeness, 6),
        "hallucination_score": round(1.0 - faithfulness, 6),
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.I)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def judge_answer_quality(
    question: str,
    expected_answer: str,
    actual_answer: str,
    retrieved_documents: list[dict[str, Any]],
    expected_citations: list[str],
    actual_citations: list[str] | None = None,
    model_override: str | None = None,
) -> tuple[dict[str, float], dict[str, Any], list[dict[str, Any]]]:
    contexts = [
        {
            "source": item.get("source") or item.get("document_id"),
            "text": str(item.get("text") or item.get("content") or "")[:4000],
        }
        for item in retrieved_documents[:10]
    ]
    prompt = f"""
You are an impartial RAG evaluator. Score only from the supplied benchmark and
retrieved context. Do not reward fluent unsupported claims.

Definitions:
- context_relevance: retrieved context usefulness for the question.
- faithfulness: answer claims supported by retrieved context.
- citation_correctness: returned sources align with expected citations and claims.
- answer_completeness: expected answer information covered by the actual answer.
- hallucination_score: unsupported-claim risk; 0 is best and 1 is worst.

Return JSON only with scores from 0 to 1 and one brief reason.

QUESTION: {json.dumps(question, ensure_ascii=False)}
EXPECTED_ANSWER: {json.dumps(expected_answer, ensure_ascii=False)}
EXPECTED_CITATIONS: {_json(expected_citations)}
ACTUAL_CITATIONS: {_json(actual_citations or [])}
ACTUAL_ANSWER: {json.dumps(actual_answer, ensure_ascii=False)}
RETRIEVED_CONTEXTS: {_json(contexts)}
""".strip()
    with capture_llm_usage() as usage:
        response = generate_text(
            prompt=prompt,
            temperature=0.0,
            max_tokens=320,
            timeout_seconds=int(os.getenv("RAG_EVAL_JUDGE_TIMEOUT_SECONDS", "90")),
            json_mode=True,
            disable_reasoning=True,
            json_schema=QUALITY_SCHEMA,
            json_schema_name="rag_evaluation_scores",
            model_override=model_override,
        )
    parsed = _extract_json_object(response)
    metrics = {}
    for key in (
        "context_relevance", "faithfulness", "citation_correctness",
        "answer_completeness", "hallucination_score",
    ):
        try:
            metrics[key] = round(max(0.0, min(float(parsed[key]), 1.0)), 6)
        except (KeyError, TypeError, ValueError):
            raise LLMProviderError(f"Evaluation judge returned invalid '{key}'.")
    details = {"status": "completed", "reason": str(parsed.get("reason") or "")[:1000]}
    return metrics, details, usage


def summarise_usage(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    prompt = sum(int(item.get("prompt_tokens") or 0) for item in records)
    cached = sum(int(item.get("cached_prompt_tokens") or 0) for item in records)
    completion = sum(int(item.get("completion_tokens") or 0) for item in records)
    by_model: Counter[str] = Counter()
    for item in records:
        by_model[f"{item.get('provider', 'unknown')}:{item.get('model', 'unknown')}"] += int(item.get("total_tokens") or 0)
    return {
        "calls": len(records),
        "prompt_tokens": prompt,
        "cached_prompt_tokens": cached,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "by_model": dict(by_model),
        "records": records,
    }


def estimate_cost_inr(records: Iterable[dict[str, Any]]) -> float:
    input_rate = float(os.getenv("SARVAM_INPUT_COST_PER_1M_INR", "4"))
    cached_rate = float(os.getenv("SARVAM_CACHED_INPUT_COST_PER_1M_INR", "2.5"))
    output_rate = float(os.getenv("SARVAM_OUTPUT_COST_PER_1M_INR", "16"))
    total = 0.0
    for item in records:
        if str(item.get("provider")) != "sarvam":
            continue
        prompt = int(item.get("prompt_tokens") or 0)
        cached = min(prompt, int(item.get("cached_prompt_tokens") or 0))
        completion = int(item.get("completion_tokens") or 0)
        total += ((prompt - cached) * input_rate + cached * cached_rate + completion * output_rate) / 1_000_000
    return round(total, 8)


def evaluate_pipeline_output(
    case: dict[str, Any],
    output: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    documents = list(output.get("retrieved_documents") or [])
    expected_documents = list(case.get("relevant_documents") or [])
    expected_citations = list(case.get("expected_citations") or [])
    actual_citations = list(output.get("actual_citations") or [])
    top_k = int(config.get("top_k") or 5)
    metrics = retrieval_metrics(expected_documents, documents, top_k)
    quality = fallback_quality_metrics(
        case["question"], case.get("expected_answer") or "",
        output.get("answer") or "", documents, expected_citations,
        actual_citations,
    )
    judge_details: dict[str, Any] = {"status": "disabled"}
    judge_usage: list[dict[str, Any]] = []
    if config.get("judge_enabled") and not output.get("error"):
        try:
            quality, judge_details, judge_usage = judge_answer_quality(
                case["question"], case.get("expected_answer") or "",
                output.get("answer") or "", documents, expected_citations,
                actual_citations,
                model_override=str(config.get("judge_model") or "") or None,
            )
        except Exception as error:
            judge_details = {
                "status": "fallback",
                "error": f"{type(error).__name__}: {error}"[:1000],
            }
    metrics.update(quality)
    expected_route = str((case.get("metadata") or {}).get("expected_route") or "").upper()
    route_correctness = 1.0 if not expected_route else float(output.get("route") == expected_route)
    metrics["route_correctness"] = route_correctness
    metrics["latency_ms"] = round(float(output.get("latency_ms") or 0), 3)
    failure_tags: list[str] = []
    recall_key = f"recall_at_{top_k}"
    if output.get("error"):
        failure_tags.append("pipeline_error")
    if route_correctness == 0:
        failure_tags.append("routing_failure")
    if metrics.get(recall_key, 0) <= 0 and expected_documents:
        failure_tags.append("retrieval_miss")
    elif metrics.get("mrr", 0) < 0.5 and expected_documents:
        failure_tags.append("ranking_failure")
    if metrics["faithfulness"] < 0.65:
        failure_tags.append("hallucination_risk")
    if metrics["citation_correctness"] < 0.65:
        failure_tags.append("citation_failure")
    if metrics["answer_completeness"] < 0.65:
        failure_tags.append("incomplete_answer")
    latency_limit = float(os.getenv("RAG_EVAL_LATENCY_WARNING_MS", "15000"))
    if metrics["latency_ms"] > latency_limit:
        failure_tags.append("high_latency")
    failure_cluster = failure_tags[0] if failure_tags else "passed"
    generation_usage = list(output.get("usage_records") or [])
    all_usage = [*generation_usage, *judge_usage]
    token_usage = {
        "pipeline": summarise_usage(generation_usage),
        "judge": summarise_usage(judge_usage),
        "total": summarise_usage(all_usage),
    }
    return {
        "metrics": metrics,
        "judge_details": judge_details,
        "token_usage": token_usage,
        "estimated_cost_inr": estimate_cost_inr(all_usage),
        "failure_cluster": failure_cluster,
        "failure_tags": failure_tags,
    }


def save_result(
    experiment_id: str,
    case_id: str,
    output: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    result_id = str(uuid4())
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rag_eval_results(
                    id, experiment_id, case_id, actual_answer, route,
                    retrieved_documents, actual_citations, metrics, latency_ms,
                    token_usage, estimated_cost_inr, failure_cluster, failure_tags,
                    judge_details, error
                ) VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s,
                    %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s
                )
                ON CONFLICT(experiment_id, case_id) DO UPDATE SET
                    actual_answer = EXCLUDED.actual_answer,
                    route = EXCLUDED.route,
                    retrieved_documents = EXCLUDED.retrieved_documents,
                    actual_citations = EXCLUDED.actual_citations,
                    metrics = EXCLUDED.metrics,
                    latency_ms = EXCLUDED.latency_ms,
                    token_usage = EXCLUDED.token_usage,
                    estimated_cost_inr = EXCLUDED.estimated_cost_inr,
                    failure_cluster = EXCLUDED.failure_cluster,
                    failure_tags = EXCLUDED.failure_tags,
                    judge_details = EXCLUDED.judge_details,
                    error = EXCLUDED.error
                RETURNING *;
                """,
                (
                    result_id, experiment_id, case_id, str(output.get("answer") or ""),
                    str(output.get("route") or ""), _json(output.get("retrieved_documents") or []),
                    _json(output.get("actual_citations") or []), _json(evaluation["metrics"]),
                    float(output.get("latency_ms") or 0), _json(evaluation["token_usage"]),
                    evaluation["estimated_cost_inr"], evaluation["failure_cluster"],
                    _json(evaluation["failure_tags"]), _json(evaluation["judge_details"]),
                    str(output.get("error") or "")[:4000],
                ),
            )
            return _row(cursor.fetchone()) or {}


def _mean(values: Iterable[Any]) -> float:
    cleaned = []
    for value in values:
        try:
            cleaned.append(float(value))
        except (TypeError, ValueError):
            continue
    return round(statistics.fmean(cleaned), 6) if cleaned else 0.0


def aggregate_experiment(experiment_id: str) -> dict[str, Any]:
    experiment = get_experiment(experiment_id, include_results=True)
    if not experiment:
        raise ValueError("Experiment was not found.")
    results = experiment.get("results") or []
    metric_names = sorted({key for result in results for key in (result.get("metrics") or {})})
    aggregate = {
        key: _mean((result.get("metrics") or {}).get(key) for result in results)
        for key in metric_names
        if key != "latency_ms"
    }
    latencies = [float(result.get("latency_ms") or 0) for result in results]
    sorted_latency = sorted(latencies)
    aggregate.update({
        "case_count": len(results),
        "passed_cases": sum(1 for result in results if result.get("failure_cluster") == "passed"),
        "pass_rate": round(sum(1 for result in results if result.get("failure_cluster") == "passed") / len(results), 6) if results else 0.0,
        "mean_latency_ms": _mean(latencies),
        "p95_latency_ms": round(sorted_latency[min(len(sorted_latency) - 1, math.ceil(len(sorted_latency) * 0.95) - 1)], 3) if sorted_latency else 0.0,
        "total_tokens": sum(int(((result.get("token_usage") or {}).get("total") or {}).get("total_tokens") or 0) for result in results),
        "total_cost_inr": round(sum(float(result.get("estimated_cost_inr") or 0) for result in results), 8),
        "failure_clusters": dict(Counter(str(result.get("failure_cluster") or "unknown") for result in results)),
    })
    return aggregate


def _create_alert(
    experiment_id: str,
    severity: str,
    alert_type: str,
    message: str,
    metric_name: str = "",
    current_value: float | None = None,
    baseline_value: float | None = None,
) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rag_eval_alerts(
                    id, experiment_id, severity, alert_type, message,
                    metric_name, current_value, baseline_value
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (str(uuid4()), experiment_id, severity, alert_type, message, metric_name, current_value, baseline_value),
            )


def complete_experiment(experiment_id: str) -> dict[str, Any]:
    aggregate = aggregate_experiment(experiment_id)
    experiment = get_experiment(experiment_id, include_results=False)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE rag_eval_experiments
                SET status = 'COMPLETED', aggregate_metrics = %s::jsonb,
                    completed_at = NOW(), error = ''
                WHERE id = %s;
                """,
                (_json(aggregate), experiment_id),
            )
    if aggregate.get("faithfulness", 1.0) < 0.70:
        _create_alert(
            experiment_id, "WARNING", "HALLUCINATION_RISK",
            "Mean faithfulness fell below 0.70.", "faithfulness",
            aggregate.get("faithfulness"), 0.70,
        )
    baseline_id = (experiment or {}).get("baseline_experiment_id")
    if baseline_id:
        baseline = get_experiment(baseline_id, include_results=False)
        baseline_metrics = (baseline or {}).get("aggregate_metrics") or {}
        retrieval_metrics = sorted(
            metric for metric in aggregate
            if (
                metric.startswith("recall_at_")
                or metric.startswith("precision_at_")
            ) and metric in baseline_metrics
        )
        for metric in (
            *retrieval_metrics,
            "mrr",
            "ndcg",
            "faithfulness",
            "answer_completeness",
        ):
            if metric not in aggregate or metric not in baseline_metrics:
                continue
            current, previous = float(aggregate[metric]), float(baseline_metrics[metric])
            if current < previous - float(os.getenv("RAG_EVAL_REGRESSION_THRESHOLD", "0.05")):
                _create_alert(
                    experiment_id, "CRITICAL", "QUALITY_REGRESSION",
                    f"{metric} regressed from {previous:.3f} to {current:.3f}.",
                    metric, current, previous,
                )
        current_latency = float(aggregate.get("mean_latency_ms") or 0)
        baseline_latency = float(baseline_metrics.get("mean_latency_ms") or 0)
        if baseline_latency and current_latency > baseline_latency * 1.25:
            _create_alert(
                experiment_id, "WARNING", "LATENCY_REGRESSION",
                f"Mean latency increased from {baseline_latency:.0f} ms to {current_latency:.0f} ms.",
                "mean_latency_ms", current_latency, baseline_latency,
            )
    return aggregate


def list_versions() -> list[dict[str, Any]]:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM rag_eval_versions ORDER BY created_at DESC;")
            return [_row(dict(item)) or {} for item in cursor.fetchall()]


def create_version(
    version_type: str,
    name: str,
    version: str,
    config: dict[str, Any],
    created_by: str,
) -> dict[str, Any]:
    ensure_evaluation_schema()
    version_type = str(version_type or "").strip().casefold()
    if version_type not in ALLOWED_VERSION_TYPES:
        raise ValueError("Invalid version type.")
    name = str(name or "").strip()
    version = str(version or "").strip()
    if not 1 <= len(name) <= 160:
        raise ValueError("Version name must contain 1 to 160 characters.")
    if not 1 <= len(version) <= 120:
        raise ValueError("Version identifier must contain 1 to 120 characters.")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rag_eval_versions(id, version_type, name, version, config, created_by)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT(version_type, name, version) DO UPDATE SET config = EXCLUDED.config
                RETURNING *;
                """,
                (str(uuid4()), version_type, name, version, _json(config or {}), created_by),
            )
            return _row(cursor.fetchone()) or {}


def upsert_human_review(
    result_id: str,
    reviewer: str,
    scores: dict[str, Any],
    notes: str,
) -> dict[str, Any]:
    ensure_evaluation_schema()
    values = {}
    for key in ("relevance", "faithfulness", "citation_correctness", "completeness"):
        value = int(scores.get(key) or 0)
        if not 1 <= value <= 5:
            raise ValueError(f"{key} must be between 1 and 5.")
        values[key] = value
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rag_eval_human_reviews(
                    id, result_id, reviewer, relevance, faithfulness,
                    citation_correctness, completeness, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(result_id, reviewer) DO UPDATE SET
                    relevance = EXCLUDED.relevance,
                    faithfulness = EXCLUDED.faithfulness,
                    citation_correctness = EXCLUDED.citation_correctness,
                    completeness = EXCLUDED.completeness,
                    notes = EXCLUDED.notes,
                    updated_at = NOW()
                RETURNING *;
                """,
                (
                    str(uuid4()), result_id, reviewer, values["relevance"],
                    values["faithfulness"], values["citation_correctness"],
                    values["completeness"], str(notes or "")[:4000],
                ),
            )
            return _row(cursor.fetchone()) or {}


def compare_experiments(experiment_ids: list[str]) -> list[dict[str, Any]]:
    comparisons = []
    for experiment_id in list(dict.fromkeys(experiment_ids))[:10]:
        experiment = get_experiment(experiment_id, include_results=False)
        if experiment:
            comparisons.append({
                "id": experiment["id"],
                "name": experiment["name"],
                "dataset_name": experiment["dataset_name"],
                "status": experiment["status"],
                "config": experiment["config"],
                "metrics": experiment["aggregate_metrics"],
                "created_at": experiment["created_at"],
            })
    return comparisons


def dashboard_summary() -> dict[str, Any]:
    ensure_evaluation_schema()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM rag_eval_datasets)::int AS datasets,
                    (SELECT COUNT(*) FROM rag_eval_cases)::int AS cases,
                    (SELECT COUNT(*) FROM rag_eval_experiments)::int AS experiments,
                    (SELECT COUNT(*) FROM rag_eval_experiments WHERE status = 'RUNNING')::int AS running,
                    (SELECT COUNT(*) FROM rag_eval_alerts WHERE acknowledged = FALSE)::int AS open_alerts,
                    (SELECT COUNT(*) FROM rag_eval_human_reviews)::int AS human_reviews;
                """
            )
            counts = _row(cursor.fetchone()) or {}
            cursor.execute(
                """
                SELECT * FROM rag_eval_alerts
                ORDER BY created_at DESC LIMIT 25;
                """
            )
            alerts = [_row(dict(item)) or {} for item in cursor.fetchall()]
    return {
        "counts": counts,
        "recent_experiments": list_experiments(10),
        "alerts": alerts,
        "failure_clusters": _global_failure_clusters(),
    }


def _global_failure_clusters() -> dict[str, int]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT failure_cluster, COUNT(*)::int AS count
                FROM rag_eval_results
                GROUP BY failure_cluster ORDER BY count DESC;
                """
            )
            return {str(row["failure_cluster"]): int(row["count"]) for row in cursor.fetchall()}


def acknowledge_alert(alert_id: str) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE rag_eval_alerts SET acknowledged = TRUE WHERE id = %s;",
                (alert_id,),
            )
            return cursor.rowcount > 0


def experiment_csv(experiment_id: str) -> str:
    experiment = get_experiment(experiment_id, include_results=True)
    if not experiment:
        raise ValueError("Experiment was not found.")
    output = io.StringIO()
    fields = [
        "ordinal", "question", "expected_answer", "actual_answer", "route",
        "failure_cluster", "latency_ms", "estimated_cost_inr", "metrics",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for result in experiment.get("results") or []:
        writer.writerow({
            key: _csv_safe(
                _json(result.get(key)) if key == "metrics" else result.get(key, "")
            )
            for key in fields
        })
    return output.getvalue()


def _csv_safe(value: Any) -> Any:
    """Prevent benchmark text from becoming a spreadsheet formula on export."""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
