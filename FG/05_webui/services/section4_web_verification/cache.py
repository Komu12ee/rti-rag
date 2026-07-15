from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .config import Section4Config
from .schemas import (
    DocumentPage,
    EvidenceItem,
    RetrievedDocument,
    SearchedSource,
    SourceSearchStatus,
    TriggerSource,
    VerificationResult,
    VerificationStatus,
)


_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z\u0900-\u097f]+", re.UNICODE)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "body",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "password",
        "raw_query",
        "request_body",
        "rti_text",
        "secret",
        "token",
    }
)


@dataclass(frozen=True)
class LexicalDocumentHit:
    document: RetrievedDocument
    score: float
    matched_terms: tuple[str, ...]


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported cache value type: {type(value).__name__}")


def _json_dumps(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _assert_public_context(value: Any, path: str = "context") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().casefold()
            if key in _FORBIDDEN_CONTEXT_KEYS:
                raise ValueError(f"Sensitive field is not permitted in retry context: {path}.{key}")
            _assert_public_context(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            _assert_public_context(item, f"{path}[{index}]")


def _document_from_dict(data: Mapping[str, Any]) -> RetrievedDocument:
    pages = tuple(
        DocumentPage(
            page_number=int(page.get("page_number", 0)),
            text=str(page.get("text", "")),
            ocr_used=bool(page.get("ocr_used", False)),
            section_headings=tuple(str(item) for item in page.get("section_headings", ())),
        )
        for page in data.get("pages", ())
        if isinstance(page, Mapping)
    )
    return RetrievedDocument(
        source_id=str(data.get("source_id", "")),
        title=str(data.get("title", "")),
        url=str(data.get("url", "")),
        final_url=str(data.get("final_url", "")),
        domain=str(data.get("domain", "")),
        source_type=str(data.get("source_type", "page")),
        publication_date=(
            str(data["publication_date"]) if data.get("publication_date") is not None else None
        ),
        retrieved_at=str(data.get("retrieved_at", "")),
        content_type=str(data.get("content_type", "")),
        document_hash=str(data.get("document_hash", "")),
        pages=pages,
        http_status=(int(data["http_status"]) if data.get("http_status") is not None else None),
        byte_count=int(data.get("byte_count", 0)),
        etag=str(data["etag"]) if data.get("etag") is not None else None,
        last_modified=(
            str(data["last_modified"]) if data.get("last_modified") is not None else None
        ),
        extraction_method=str(data.get("extraction_method", "")),
        warnings=tuple(str(item) for item in data.get("warnings", ())),
    )


def _verification_from_dict(data: Mapping[str, Any]) -> VerificationResult:
    searched_sources = tuple(
        SearchedSource(
            adapter_id=str(item.get("adapter_id", "")),
            domain=str(item.get("domain", "")),
            status=SourceSearchStatus(str(item.get("status", SourceSearchStatus.SKIPPED.value))),
            results_examined=int(item.get("results_examined", 0)),
            candidates_found=int(item.get("candidates_found", 0)),
            elapsed_ms=int(item.get("elapsed_ms", 0)),
            error_code=(str(item["error_code"]) if item.get("error_code") is not None else None),
        )
        for item in data.get("searched_sources", ())
        if isinstance(item, Mapping)
    )
    found_items = tuple(
        EvidenceItem(
            evidence_id=str(item.get("evidence_id", "")),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            domain=str(item.get("domain", "")),
            document_type=str(item.get("document_type", "page")),
            publication_date=(
                str(item["publication_date"])
                if item.get("publication_date") is not None
                else None
            ),
            page_number=(
                int(item["page_number"]) if item.get("page_number") is not None else None
            ),
            section_heading=(
                str(item["section_heading"])
                if item.get("section_heading") is not None
                else None
            ),
            matched_text=str(item.get("matched_text", "")),
            matched_entities=tuple(str(value) for value in item.get("matched_entities", ())),
            supported_fields=tuple(str(value) for value in item.get("supported_fields", ())),
            relevance_score=float(item.get("relevance_score", 0.0)),
            verified=bool(item.get("verified", False)),
            document_hash=str(item.get("document_hash", "")),
        )
        for item in data.get("found_items", ())
        if isinstance(item, Mapping)
    )
    errors = tuple(
        {str(key): str(value) for key, value in item.items()}
        for item in data.get("errors", ())
        if isinstance(item, Mapping)
    )
    return VerificationResult(
        verification_id=str(data.get("verification_id", "")),
        triggered=bool(data.get("triggered", False)),
        trigger_reason=(
            str(data["trigger_reason"]) if data.get("trigger_reason") is not None else None
        ),
        trigger_source=TriggerSource(str(data.get("trigger_source", TriggerSource.NONE.value))),
        sub_clause=str(data["sub_clause"]) if data.get("sub_clause") is not None else None,
        status=VerificationStatus(
            str(data.get("status", VerificationStatus.SEARCH_NOT_TRIGGERED.value))
        ),
        organisation=(
            str(data["organisation"]) if data.get("organisation") is not None else None
        ),
        subject=str(data["subject"]) if data.get("subject") is not None else None,
        searched_sources=searched_sources,
        found_items=found_items,
        available_fields=tuple(str(item) for item in data.get("available_fields", ())),
        missing_fields=tuple(str(item) for item in data.get("missing_fields", ())),
        verification_timestamp=str(data.get("verification_timestamp", "")),
        warnings=tuple(str(item) for item in data.get("warnings", ())),
        errors=errors,
        cache_hit=bool(data.get("cache_hit", False)),
    )


class Section4Cache:
    """SQLite-backed cache containing only JSON and extracted public-source text."""

    def __init__(
        self,
        config: Section4Config,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self.path = Path(config.cache_path)
        self.default_ttl_seconds = int(config.cache_ttl_seconds)
        self.local_index_enabled = bool(config.local_index_enabled)
        self._now = now or time.time
        self._write_lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @staticmethod
    def query_cache_key(value: Any) -> str:
        if isinstance(value, str):
            normalised = " ".join(value.split()).casefold()
            if _SHA256_PATTERN.fullmatch(normalised):
                return normalised
            material = normalised.encode("utf-8")
        else:
            material = _json_dumps(value).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def _ttl(self, ttl_seconds: int | float | None) -> float:
        value = self.default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        return max(0.0, value)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=5.0,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialise(self) -> None:
        with self._write_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS query_results (
                    cache_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    url TEXT PRIMARY KEY,
                    final_url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    public_text TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    etag TEXT,
                    last_modified TEXT,
                    document_hash TEXT NOT NULL,
                    retrieved_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_documents_hash
                    ON documents(document_hash);
                CREATE INDEX IF NOT EXISTS idx_documents_domain
                    ON documents(domain);
                CREATE INDEX IF NOT EXISTS idx_documents_expiry
                    ON documents(expires_at);

                CREATE TABLE IF NOT EXISTS verification_results (
                    verification_id TEXT PRIMARY KEY,
                    query_cache_key TEXT,
                    result_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_verification_query_key
                    ON verification_results(query_cache_key);
                CREATE INDEX IF NOT EXISTS idx_verification_expiry
                    ON verification_results(expires_at);
                """
            )

    def put_query_result(
        self,
        cache_key: Any,
        result: VerificationResult | Mapping[str, Any],
        *,
        ttl_seconds: int | float | None = None,
    ) -> str:
        key = self.query_cache_key(cache_key)
        now = float(self._now())
        expires_at = now + self._ttl(ttl_seconds)
        payload_value = _json_value(result)
        _assert_public_context(payload_value, "query_result")
        payload = _json_dumps(payload_value)
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO query_results(cache_key, payload_json, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (key, payload, now, expires_at),
            )
        return key

    def get_query_result(self, cache_key: Any) -> dict[str, Any] | None:
        key = self.query_cache_key(cache_key)
        now = float(self._now())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json, expires_at FROM query_results WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None or float(row["expires_at"]) <= now:
            return None
        payload = json.loads(str(row["payload_json"]))
        return payload if isinstance(payload, dict) else None

    def put_document(
        self,
        document: RetrievedDocument | Mapping[str, Any],
        *,
        ttl_seconds: int | float | None = None,
    ) -> str:
        value = document if isinstance(document, RetrievedDocument) else _document_from_dict(document)
        url = (value.url or value.final_url).strip()
        if not url:
            raise ValueError("A public document URL is required")
        final_url = (value.final_url or url).strip()
        public_text = "\n\n".join(page.text for page in value.pages if page.text).strip()
        document_hash = value.document_hash or hashlib.sha256(
            public_text.encode("utf-8")
        ).hexdigest()
        payload = value.to_dict()
        payload["document_hash"] = document_hash
        now = float(self._now())
        expires_at = now + self._ttl(ttl_seconds)

        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents(
                    url, final_url, domain, title, content_type, public_text,
                    document_json, etag, last_modified, document_hash,
                    retrieved_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    final_url = excluded.final_url,
                    domain = excluded.domain,
                    title = excluded.title,
                    content_type = excluded.content_type,
                    public_text = excluded.public_text,
                    document_json = excluded.document_json,
                    etag = excluded.etag,
                    last_modified = excluded.last_modified,
                    document_hash = excluded.document_hash,
                    retrieved_at = excluded.retrieved_at,
                    expires_at = excluded.expires_at
                """,
                (
                    url,
                    final_url,
                    value.domain,
                    value.title,
                    value.content_type,
                    public_text,
                    _json_dumps(payload),
                    value.etag,
                    value.last_modified,
                    document_hash,
                    now,
                    expires_at,
                ),
            )
        return document_hash

    def get_document(
        self,
        url: str,
        *,
        include_expired: bool = False,
    ) -> RetrievedDocument | None:
        now = float(self._now())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document_json, expires_at FROM documents WHERE url = ? OR final_url = ? LIMIT 1",
                (url, url),
            ).fetchone()
        if row is None or (not include_expired and float(row["expires_at"]) <= now):
            return None
        payload = json.loads(str(row["document_json"]))
        return _document_from_dict(payload)

    def touch_document(
        self,
        url: str,
        *,
        ttl_seconds: int | float | None = None,
    ) -> bool:
        """Refresh expiry after a safe conditional 304 without replacing public text."""
        now = float(self._now())
        expires_at = now + self._ttl(ttl_seconds)
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE documents
                SET retrieved_at = ?, expires_at = ?
                WHERE url = ? OR final_url = ?
                """,
                (now, expires_at, url, url),
            )
        return int(cursor.rowcount) > 0

    def get_document_by_hash(self, document_hash: str) -> RetrievedDocument | None:
        now = float(self._now())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT document_json
                FROM documents
                WHERE document_hash = ? AND expires_at > ?
                ORDER BY retrieved_at DESC
                LIMIT 1
                """,
                (str(document_hash), now),
            ).fetchone()
        if row is None:
            return None
        return _document_from_dict(json.loads(str(row["document_json"])))

    def get_document_metadata(self, url: str) -> dict[str, Any] | None:
        now = float(self._now())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT url, final_url, domain, content_type, etag, last_modified,
                       document_hash, retrieved_at, expires_at
                FROM documents
                WHERE url = ? OR final_url = ?
                LIMIT 1
                """,
                (url, url),
            ).fetchone()
        if row is None:
            return None
        metadata = dict(row)
        metadata["is_expired"] = float(row["expires_at"]) <= now
        return metadata

    def search_documents(self, query: str, *, limit: int = 10) -> list[LexicalDocumentHit]:
        if not self.local_index_enabled:
            return []
        terms = tuple(dict.fromkeys(_TOKEN_PATTERN.findall(str(query).casefold())))
        if not terms:
            return []
        bounded_limit = max(1, min(50, int(limit)))
        now = float(self._now())
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT title, public_text, document_json, retrieved_at
                FROM documents
                WHERE expires_at > ?
                ORDER BY retrieved_at DESC
                LIMIT 500
                """,
                (now,),
            ).fetchall()

        ranked: list[tuple[float, float, tuple[str, ...], RetrievedDocument]] = []
        phrase = " ".join(terms)
        for row in rows:
            title = str(row["title"] or "").casefold()
            public_text = str(row["public_text"] or "").casefold()
            matched = tuple(term for term in terms if term in title or term in public_text)
            if not matched:
                continue
            score = sum(
                (3.0 if term in title else 0.0) + min(5, public_text.count(term))
                for term in matched
            ) / len(terms)
            if phrase and phrase in public_text:
                score += 2.0
            document = _document_from_dict(json.loads(str(row["document_json"])))
            ranked.append((score, float(row["retrieved_at"]), matched, document))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            LexicalDocumentHit(document=item[3], score=item[0], matched_terms=item[2])
            for item in ranked[:bounded_limit]
        ]

    def put_verification_result(
        self,
        result: VerificationResult | Mapping[str, Any],
        *,
        context: Mapping[str, Any] | None = None,
        query_cache_key: Any | None = None,
        ttl_seconds: int | float | None = None,
    ) -> str:
        payload = _json_value(result)
        if not isinstance(payload, Mapping):
            raise TypeError("Verification result must be a mapping-compatible schema")
        _assert_public_context(payload, "verification_result")
        verification_id = str(payload.get("verification_id", "")).strip()
        if not verification_id:
            raise ValueError("verification_id is required")
        retry_context = dict(context or {})
        _assert_public_context(retry_context)
        cache_key = (
            self.query_cache_key(query_cache_key) if query_cache_key is not None else None
        )
        now = float(self._now())
        expires_at = now + self._ttl(ttl_seconds)
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO verification_results(
                    verification_id, query_cache_key, result_json, context_json,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(verification_id) DO UPDATE SET
                    query_cache_key = excluded.query_cache_key,
                    result_json = excluded.result_json,
                    context_json = excluded.context_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (
                    verification_id,
                    cache_key,
                    _json_dumps(payload),
                    _json_dumps(retry_context),
                    now,
                    expires_at,
                ),
            )
        return verification_id

    def get_verification_result(self, verification_id: str) -> VerificationResult | None:
        now = float(self._now())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT result_json, expires_at
                FROM verification_results
                WHERE verification_id = ?
                """,
                (str(verification_id),),
            ).fetchone()
        if row is None or float(row["expires_at"]) <= now:
            return None
        return _verification_from_dict(json.loads(str(row["result_json"])))

    def get_verification_context(self, verification_id: str) -> dict[str, Any] | None:
        now = float(self._now())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT context_json, query_cache_key, expires_at
                FROM verification_results
                WHERE verification_id = ?
                """,
                (str(verification_id),),
            ).fetchone()
        if row is None or float(row["expires_at"]) <= now:
            return None
        context = json.loads(str(row["context_json"]))
        if not isinstance(context, dict):
            return None
        if row["query_cache_key"]:
            context.setdefault("query_cache_key", str(row["query_cache_key"]))
        return context

    def purge_expired(self) -> dict[str, int]:
        now = float(self._now())
        removed: dict[str, int] = {}
        with self._write_lock, self._connect() as connection:
            for table in ("query_results", "documents", "verification_results"):
                cursor = connection.execute(
                    f"DELETE FROM {table} WHERE expires_at <= ?",  # noqa: S608 - fixed table list
                    (now,),
                )
                removed[table] = max(0, int(cursor.rowcount))
        return removed
