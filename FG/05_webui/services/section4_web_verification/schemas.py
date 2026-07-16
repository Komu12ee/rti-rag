from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


class TriggerSource(str, Enum):
    EXPLICIT_REFERENCE = "EXPLICIT_REFERENCE"
    LEGAL_ANALYSIS = "LEGAL_ANALYSIS"
    SEMANTIC_CLASSIFIER = "SEMANTIC_CLASSIFIER"
    NONE = "NONE"


class VerificationStatus(str, Enum):
    FOUND = "FOUND"
    PARTIALLY_FOUND = "PARTIALLY_FOUND"
    NOT_FOUND = "NOT_FOUND"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SEARCH_NOT_TRIGGERED = "SEARCH_NOT_TRIGGERED"


class SourceSearchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RESULTS = "NO_RESULTS"
    UNAVAILABLE = "UNAVAILABLE"
    SKIPPED = "SKIPPED"


def _serialise(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _serialise(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _serialise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialise(item) for item in value]
    return value


class SerializableSchema:
    def to_dict(self) -> dict[str, Any]:
        return _serialise(self)


@dataclass(frozen=True)
class EntityRef(SerializableSchema):
    name: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TenderIntent(SerializableSchema):
    tender_intent: bool = False
    intent_type: str | None = None
    organisation: str | None = None
    company: str | None = None
    project: str | None = None
    tender_number: str | None = None
    contract_number: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    requested_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Section4TriggerResult(SerializableSchema):
    triggered: bool
    trigger_type: str | None = None
    trigger_source: TriggerSource = TriggerSource.NONE
    sub_clause: str | None = None
    confidence: float = 0.0
    reason: str = ""
    tender_intent: bool = False
    category: str | None = None
    search_concepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchPlan(SerializableSchema):
    organisation: EntityRef = field(default_factory=EntityRef)
    public_authority: EntityRef = field(default_factory=EntityRef)
    department: EntityRef = field(default_factory=EntityRef)
    company: EntityRef = field(default_factory=EntityRef)
    project: EntityRef = field(default_factory=EntityRef)
    district: EntityRef = field(default_factory=EntityRef)
    scheme: EntityRef = field(default_factory=EntityRef)
    tender_number: str | None = None
    contract_number: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    requested_record_types: tuple[str, ...] = ()
    requested_fields: tuple[str, ...] = ()
    sub_clause: str | None = None
    category: str | None = None
    search_concepts: tuple[str, ...] = ()
    search_queries: tuple[str, ...] = ()
    tender: TenderIntent = field(default_factory=TenderIntent)


@dataclass(frozen=True)
class SearchCandidate(SerializableSchema):
    adapter_id: str
    url: str
    title: str | None = None
    source_type: str = "page"
    discovered_from: str | None = None
    lexical_score: float = 0.0


@dataclass(frozen=True)
class DocumentPage(SerializableSchema):
    page_number: int
    text: str
    ocr_used: bool = False
    section_headings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievedDocument(SerializableSchema):
    source_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    url: str = ""
    final_url: str = ""
    domain: str = ""
    source_type: str = "page"
    publication_date: str | None = None
    retrieved_at: str = ""
    content_type: str = ""
    document_hash: str = ""
    pages: tuple[DocumentPage, ...] = ()
    http_status: int | None = None
    byte_count: int = 0
    etag: str | None = None
    last_modified: str | None = None
    extraction_method: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceItem(SerializableSchema):
    evidence_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    url: str = ""
    domain: str = ""
    document_type: str = "page"
    publication_date: str | None = None
    page_number: int | None = None
    section_heading: str | None = None
    matched_text: str = ""
    matched_entities: tuple[str, ...] = ()
    supported_fields: tuple[str, ...] = ()
    relevance_score: float = 0.0
    verified: bool = False
    document_hash: str = ""


@dataclass(frozen=True)
class SearchedSource(SerializableSchema):
    adapter_id: str
    domain: str
    status: SourceSearchStatus
    results_examined: int = 0
    candidates_found: int = 0
    elapsed_ms: int = 0
    error_code: str | None = None


@dataclass(frozen=True)
class SourceHealth(SerializableSchema):
    adapter_id: str
    domain: str
    enabled: bool
    status: str
    checked_at: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class VerificationResult(SerializableSchema):
    verification_id: str = field(default_factory=lambda: str(uuid4()))
    triggered: bool = False
    trigger_reason: str | None = None
    trigger_source: TriggerSource = TriggerSource.NONE
    sub_clause: str | None = None
    status: VerificationStatus = VerificationStatus.SEARCH_NOT_TRIGGERED
    organisation: str | None = None
    subject: str | None = None
    searched_sources: tuple[SearchedSource, ...] = ()
    found_items: tuple[EvidenceItem, ...] = ()
    available_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    verification_timestamp: str = ""
    warnings: tuple[str, ...] = ()
    errors: tuple[dict[str, str], ...] = ()
    cache_hit: bool = False

