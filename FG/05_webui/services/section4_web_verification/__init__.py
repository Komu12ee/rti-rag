"""Restricted Section 4(1)(b) government-source verification primitives."""

from .config import BUILTIN_APPROVED_DOMAINS, Section4Config
from .query_analyser import build_search_plan
from .schemas import (
    DocumentPage,
    EntityRef,
    EvidenceItem,
    RetrievedDocument,
    SearchCandidate,
    SearchPlan,
    Section4TriggerResult,
    SearchedSource,
    SourceHealth,
    SourceSearchStatus,
    TenderIntent,
    TriggerSource,
    VerificationResult,
    VerificationStatus,
)
from .security import (
    SecurityError,
    ValidatedURL,
    normalize_hostname,
    resolve_public_addresses,
    validate_content_type,
    validate_public_url,
)
from .trigger_detector import detect_section4_trigger, detect_tender_intent
from .orchestrator import (
    Section4VerificationService,
    get_default_service,
    get_verification_sources,
    retry_section4_verification,
    section4_health,
    verify_section4,
)

__all__ = [
    "BUILTIN_APPROVED_DOMAINS",
    "DocumentPage",
    "EntityRef",
    "EvidenceItem",
    "RetrievedDocument",
    "SearchCandidate",
    "SearchPlan",
    "Section4Config",
    "Section4TriggerResult",
    "Section4VerificationService",
    "SearchedSource",
    "SecurityError",
    "SourceHealth",
    "SourceSearchStatus",
    "TenderIntent",
    "TriggerSource",
    "ValidatedURL",
    "VerificationResult",
    "VerificationStatus",
    "build_search_plan",
    "detect_section4_trigger",
    "detect_tender_intent",
    "get_default_service",
    "get_verification_sources",
    "normalize_hostname",
    "retry_section4_verification",
    "resolve_public_addresses",
    "validate_content_type",
    "validate_public_url",
    "section4_health",
    "verify_section4",
]
