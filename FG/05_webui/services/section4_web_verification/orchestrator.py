from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import replace
from typing import Any, Callable, Mapping
from uuid import uuid4

from .adapters import AdapterError, BaseSourceAdapter
from .audit import Section4AuditLogger
from .cache import Section4Cache
from .config import Section4Config
from .evidence_validator import validate_document_evidence, validate_evidence_set
from .extractors import ExtractionError
from .query_analyser import build_search_plan
from .result_merger import (
    merge_verification_result,
    search_not_triggered_result,
    source_unavailable_result,
)
from .schemas import (
    EntityRef,
    EvidenceItem,
    SearchPlan,
    Section4TriggerResult,
    SearchedSource,
    SourceSearchStatus,
    TenderIntent,
    TriggerSource,
    VerificationResult,
)
from .security import SecurityError
from .source_registry import SourceRegistry, build_source_registry
from .trigger_detector import detect_section4_trigger


SemanticClassifier = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def _structured_semantic_classifier(query: str, legal_analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    """Ask the configured LLM only for a route recommendation, never a URL."""
    from services.llm_provider import generate_text

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["triggered", "trigger_type", "sub_clause", "confidence", "reason"],
        "properties": {
            "triggered": {"type": "boolean"},
            "trigger_type": {"type": ["string", "null"], "enum": ["SECTION_4_1_B", None]},
            "sub_clause": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
    }
    prompt = f"""
Classify whether this RTI question materially asks for verification of a
proactive disclosure obligation under Section 4(1)(b) of the RTI Act.
Do not propose websites, URLs, search terms, facts, or legal conclusions.
Return only the requested JSON route recommendation. Generic references to
another RTI section, a website, or online information are not sufficient.

<question>
{str(query or '')[:6000]}
</question>
<validated_legal_analysis>
{json.dumps(legal_analysis, ensure_ascii=False, sort_keys=True)[:12000]}
</validated_legal_analysis>
""".strip()
    generated = generate_text(
        prompt=prompt,
        temperature=0.0,
        max_tokens=350,
        timeout_seconds=min(60, int(os.getenv("PIO_LLM_TIMEOUT_SECONDS", "240"))),
        json_mode=True,
        reasoning_effort="low",
        json_schema=schema,
        json_schema_name="section4_route_recommendation",
    )
    text = str(generated or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def _entity_from_dict(value: Any) -> EntityRef:
    data = value if isinstance(value, Mapping) else {}
    return EntityRef(
        name=str(data["name"]) if data.get("name") is not None else None,
        aliases=tuple(str(item) for item in data.get("aliases", ())),
    )


def _plan_from_dict(value: Mapping[str, Any]) -> SearchPlan:
    tender_value = value.get("tender") if isinstance(value.get("tender"), Mapping) else {}
    tender = TenderIntent(
        tender_intent=bool(tender_value.get("tender_intent", False)),
        intent_type=str(tender_value["intent_type"]) if tender_value.get("intent_type") else None,
        organisation=str(tender_value["organisation"]) if tender_value.get("organisation") else None,
        company=str(tender_value["company"]) if tender_value.get("company") else None,
        project=str(tender_value["project"]) if tender_value.get("project") else None,
        tender_number=str(tender_value["tender_number"]) if tender_value.get("tender_number") else None,
        contract_number=str(tender_value["contract_number"]) if tender_value.get("contract_number") else None,
        date_from=str(tender_value["date_from"]) if tender_value.get("date_from") else None,
        date_to=str(tender_value["date_to"]) if tender_value.get("date_to") else None,
        requested_fields=tuple(str(item) for item in tender_value.get("requested_fields", ())),
    )
    return SearchPlan(
        organisation=_entity_from_dict(value.get("organisation")),
        public_authority=_entity_from_dict(value.get("public_authority")),
        department=_entity_from_dict(value.get("department")),
        company=_entity_from_dict(value.get("company")),
        project=_entity_from_dict(value.get("project")),
        district=_entity_from_dict(value.get("district")),
        scheme=_entity_from_dict(value.get("scheme")),
        tender_number=str(value["tender_number"]) if value.get("tender_number") else None,
        contract_number=str(value["contract_number"]) if value.get("contract_number") else None,
        date_from=str(value["date_from"]) if value.get("date_from") else None,
        date_to=str(value["date_to"]) if value.get("date_to") else None,
        requested_record_types=tuple(str(item) for item in value.get("requested_record_types", ())),
        requested_fields=tuple(str(item) for item in value.get("requested_fields", ())),
        sub_clause=str(value["sub_clause"]) if value.get("sub_clause") else None,
        category=str(value["category"]) if value.get("category") else None,
        search_concepts=tuple(str(item) for item in value.get("search_concepts", ())),
        search_queries=tuple(str(item) for item in value.get("search_queries", ())),
        tender=tender,
    )


def _trigger_from_dict(value: Mapping[str, Any]) -> Section4TriggerResult:
    try:
        source = TriggerSource(str(value.get("trigger_source", TriggerSource.NONE.value)))
    except ValueError:
        source = TriggerSource.NONE
    return Section4TriggerResult(
        triggered=bool(value.get("triggered", False)),
        trigger_type=str(value["trigger_type"]) if value.get("trigger_type") else None,
        trigger_source=source,
        sub_clause=str(value["sub_clause"]) if value.get("sub_clause") else None,
        confidence=float(value.get("confidence", 0.0)),
        reason=str(value.get("reason", ""))[:500],
        tender_intent=bool(value.get("tender_intent", False)),
        category=str(value["category"]) if value.get("category") else None,
        search_concepts=tuple(str(item) for item in value.get("search_concepts", ())),
    )


def _public_result(result: VerificationResult | Mapping[str, Any], trigger: Section4TriggerResult | None = None) -> dict[str, Any]:
    payload = result.to_dict() if isinstance(result, VerificationResult) else dict(result)
    payload["cached"] = bool(payload.get("cache_hit", False))
    if trigger is not None:
        payload["trigger"] = trigger.to_dict()
    return payload


class Section4VerificationService:
    def __init__(
        self,
        config: Section4Config | None = None,
        *,
        cache: Section4Cache | None = None,
        registry: SourceRegistry | None = None,
        audit: Section4AuditLogger | None = None,
        semantic_classifier: SemanticClassifier | None = None,
    ) -> None:
        self.config = config or Section4Config.from_env()
        self.audit = audit or Section4AuditLogger(chatbot_team=self.config.chatbot_team)
        self.semantic_classifier = semantic_classifier
        self.cache_error: str | None = None
        try:
            self.cache = cache or Section4Cache(self.config)
        except Exception:
            self.cache = None
            self.cache_error = "CACHE_UNAVAILABLE"
        self.registry = registry or build_source_registry(self.config, cache=self.cache)

    def _classifier(self) -> SemanticClassifier | None:
        if not self.config.semantic_classifier_enabled:
            return None
        return self.semantic_classifier or _structured_semantic_classifier

    @staticmethod
    def _subject(plan: SearchPlan) -> str | None:
        values = [
            plan.organisation.name,
            plan.company.name,
            plan.project.name,
            plan.tender_number,
            plan.contract_number,
            *plan.requested_fields[:6],
        ]
        subject = " ".join(str(item) for item in values if item).strip()
        return subject[:400] or plan.category

    @staticmethod
    def _cache_material(trigger: Section4TriggerResult, plan: SearchPlan) -> dict[str, Any]:
        return {"trigger": trigger.to_dict(), "search_plan": plan.to_dict()}

    def _document_ttl(self, document, adapter_id: str) -> int:
        if document.source_type == "pdf":
            return 10 * 365 * 24 * 60 * 60
        if "procurement" in adapter_id or "eproc" in adapter_id or "gem" in adapter_id:
            return self.config.tender_ttl_seconds
        if "disclosure" in adapter_id:
            return self.config.disclosure_ttl_seconds
        return self.config.static_ttl_seconds

    def _search_adapter(
        self,
        adapter: BaseSourceAdapter,
        plan: SearchPlan,
        request_id: str,
        verification_id: str,
        force_refresh: bool,
        cancel_event: threading.Event,
        deadline: float,
    ) -> tuple[SearchedSource, list[EvidenceItem], list[str]]:
        started = time.perf_counter()
        adapter_id = str(getattr(adapter, "adapter_id", "unknown"))
        domain = str(getattr(adapter, "domain", ""))
        warnings: list[str] = []
        candidates = []
        examined = 0
        evidence: list[EvidenceItem] = []
        error_code: str | None = None

        def deadline_reached() -> bool:
            return cancel_event.is_set() or time.perf_counter() >= deadline

        if not bool(getattr(adapter, "enabled", True)):
            source = SearchedSource(
                adapter_id=adapter_id,
                domain=domain,
                status=SourceSearchStatus.SKIPPED,
                error_code="SOURCE_NOT_CONFIGURED",
            )
            return source, [], []
        try:
            candidates = adapter.search(plan)
            if deadline_reached():
                raise AdapterError(
                    "VERIFICATION_DEADLINE",
                    "The bounded verification deadline was reached.",
                )
            maximum_fetches = max(1, int(os.getenv("SECTION4_MAX_FETCHES_PER_SOURCE", "3")))
            for candidate in candidates[:maximum_fetches]:
                if deadline_reached():
                    raise AdapterError(
                        "VERIFICATION_DEADLINE",
                        "The bounded verification deadline was reached.",
                    )
                document = None
                if self.cache is not None and not force_refresh:
                    try:
                        document = self.cache.get_document(candidate.url)
                    except Exception:
                        document = None
                if document is None:
                    document = adapter.fetch(candidate)
                if deadline_reached():
                    raise AdapterError(
                        "VERIFICATION_DEADLINE",
                        "The bounded verification deadline was reached.",
                    )
                examined += 1
                if self.cache is not None:
                    try:
                        self.cache.put_document(
                            document,
                            ttl_seconds=self._document_ttl(document, adapter_id),
                        )
                    except Exception:
                        warnings.append("CACHE_WRITE_FAILED")
                evidence.extend(validate_document_evidence(document, plan, self.config))
                warnings.extend(document.warnings)
                self.audit.emit(
                    "document_retrieved",
                    request_id=request_id,
                    verification_id=verification_id,
                    requested_url=document.final_url or document.url,
                    adapter_id=adapter_id,
                    domain=document.domain,
                    http_status=document.http_status,
                    byte_count=document.byte_count,
                    extraction_method=document.extraction_method,
                    ocr_used=any(page.ocr_used for page in document.pages),
                )
                if len(evidence) >= self.config.max_verified_results:
                    break
            status = SourceSearchStatus.SUCCESS if examined else SourceSearchStatus.NO_RESULTS
        except (AdapterError, SecurityError, ExtractionError) as error:
            error_code = str(getattr(error, "code", "SOURCE_UNAVAILABLE"))[:80]
            status = SourceSearchStatus.UNAVAILABLE
        except Exception:
            error_code = "SOURCE_UNAVAILABLE"
            status = SourceSearchStatus.UNAVAILABLE

        source = SearchedSource(
            adapter_id=adapter_id,
            domain=domain,
            status=status,
            results_examined=examined,
            candidates_found=len(candidates),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error_code=error_code,
        )
        self.audit.emit(
            "source_completed",
            request_id=request_id,
            verification_id=verification_id,
            adapter_id=adapter_id,
            domain=domain,
            status=status.value,
            candidate_count=len(candidates),
            results_examined=examined,
            verified_item_count=len(evidence),
            error_code=error_code,
            elapsed_ms=source.elapsed_ms,
        )
        return source, evidence, warnings

    def _execute(
        self,
        trigger: Section4TriggerResult,
        plan: SearchPlan,
        *,
        subject: str | None,
        request_id: str,
        verification_id: str | None = None,
        force_refresh: bool = False,
    ) -> VerificationResult:
        execution_started = time.perf_counter()
        result_id = verification_id or str(uuid4())
        local_documents = []
        if self.cache is not None and self.config.local_index_enabled and not force_refresh:
            try:
                local_query = " ".join(plan.search_queries or plan.search_concepts)
                local_documents = [
                    hit.document
                    for hit in self.cache.search_documents(
                        local_query,
                        limit=self.config.max_verified_results * 2,
                    )
                ]
            except Exception:
                local_documents = []
        evidence = validate_evidence_set(local_documents, plan, self.config)
        searched_sources: list[SearchedSource] = []
        warnings: list[str] = []
        adapters = self.registry.select(plan, enabled_only=False)
        if adapters:
            workers = min(4, len(adapters))
            executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="section4-source")
            cancel_event = threading.Event()
            deadline = execution_started + float(self.config.total_timeout_seconds)
            futures = {
                executor.submit(
                    self._search_adapter,
                    adapter,
                    plan,
                    request_id,
                    result_id,
                    force_refresh,
                    cancel_event,
                    deadline,
                ): adapter
                for adapter in adapters
            }
            completed = set()
            remaining = max(
                0.001,
                float(self.config.total_timeout_seconds)
                - (time.perf_counter() - execution_started),
            )
            try:
                for future in as_completed(futures, timeout=remaining):
                    completed.add(future)
                    try:
                        source, source_evidence, source_warnings = future.result()
                    except Exception:
                        adapter = futures[future]
                        source = SearchedSource(
                            adapter_id=str(getattr(adapter, "adapter_id", "unknown")),
                            domain=str(getattr(adapter, "domain", "")),
                            status=SourceSearchStatus.UNAVAILABLE,
                            error_code="SOURCE_WORKER_FAILED",
                        )
                        source_evidence, source_warnings = [], []
                    searched_sources.append(source)
                    evidence.extend(source_evidence)
                    warnings.extend(source_warnings)
            except FuturesTimeoutError:
                cancel_event.set()
                warnings.append("VERIFICATION_DEADLINE_REACHED")
            finally:
                for future, adapter in futures.items():
                    if future in completed:
                        continue
                    future.cancel()
                    searched_sources.append(
                        SearchedSource(
                            adapter_id=str(getattr(adapter, "adapter_id", "unknown")),
                            domain=str(getattr(adapter, "domain", "")),
                            status=SourceSearchStatus.UNAVAILABLE,
                            elapsed_ms=int((time.perf_counter() - execution_started) * 1000),
                            error_code="VERIFICATION_DEADLINE",
                        )
                    )
                # Running HTTP calls retain their own strict per-request timeout,
                # but must not hold the synchronous PIO response past this
                # verifier-wide deadline.
                executor.shutdown(wait=False, cancel_futures=True)

        # Deterministic deduplication after concurrent source completion.
        unique: dict[tuple[str, int | None, tuple[str, ...]], EvidenceItem] = {}
        for item in evidence:
            key = (item.document_hash or item.url, item.page_number, item.supported_fields)
            previous = unique.get(key)
            if previous is None or item.relevance_score > previous.relevance_score:
                unique[key] = item
        ordered_evidence = sorted(unique.values(), key=lambda item: item.relevance_score, reverse=True)[
            : self.config.max_verified_results
        ]
        searched_sources.sort(key=lambda item: item.adapter_id)
        result = merge_verification_result(
            trigger,
            plan,
            searched_sources,
            ordered_evidence,
            subject=subject,
        )
        result = replace(result, verification_id=result_id)
        combined_warnings = tuple(dict.fromkeys((*result.warnings, *warnings)))
        if self.cache_error:
            combined_warnings = (*combined_warnings, self.cache_error)
        return replace(result, warnings=combined_warnings)

    def verify(
        self,
        query: str,
        rti_extraction: Mapping[str, Any] | None = None,
        legal_analysis: Mapping[str, Any] | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        query_text = str(query or "").strip()
        trigger = detect_section4_trigger(
            query_text,
            legal_analysis or {},
            semantic_classifier=self._classifier(),
        )
        self.audit.emit(
            "trigger_decision",
            request_id=request_id,
            query=query_text,
            triggered=trigger.triggered,
            trigger_reason=trigger.reason,
            trigger_source=trigger.trigger_source.value,
        )
        if not self.config.enabled or not trigger.triggered:
            result = search_not_triggered_result(trigger)
            return _public_result(result, trigger)

        plan = build_search_plan(query_text, rti_extraction or {}, trigger)
        subject = self._subject(plan)
        material = self._cache_material(trigger, plan)
        cache_key = Section4Cache.query_cache_key(material)
        if self.cache is not None and not force_refresh:
            try:
                cached = self.cache.get_query_result(cache_key)
            except Exception:
                cached = None
            if cached:
                cached["cache_hit"] = True
                cached["cached"] = True
                cached.setdefault("trigger", trigger.to_dict())
                self.audit.emit(
                    "verification_completed",
                    request_id=request_id,
                    verification_id=str(cached.get("verification_id") or ""),
                    cache_hit=True,
                    final_status=cached.get("status"),
                    verified_item_count=len(cached.get("found_items", [])),
                )
                return cached

        verification_id = str(uuid4())
        self.audit.emit(
            "verification_started",
            request_id=request_id,
            verification_id=verification_id,
            generated_search_terms=plan.search_queries,
            selected_sources=[getattr(item, "domain", "") for item in self.registry.select(plan)],
        )
        try:
            result = self._execute(
                trigger,
                plan,
                subject=subject,
                request_id=request_id,
                verification_id=verification_id,
                force_refresh=force_refresh,
            )
        except Exception:
            result = source_unavailable_result(
                trigger,
                organisation=plan.organisation.name or plan.public_authority.name,
                subject=subject,
                error_code="ORCHESTRATOR_FAILED",
            )
            result = replace(result, verification_id=verification_id)
        payload = _public_result(result, trigger)
        if self.cache is not None:
            context = {
                "trigger": trigger.to_dict(),
                "search_plan": plan.to_dict(),
                "subject": subject,
            }
            try:
                self.cache.put_query_result(cache_key, payload)
                self.cache.put_verification_result(
                    result,
                    context=context,
                    query_cache_key=cache_key,
                    ttl_seconds=max(self.config.cache_ttl_seconds, 86_400),
                )
            except Exception:
                payload.setdefault("warnings", []).append("CACHE_WRITE_FAILED")
        self.audit.emit(
            "verification_completed",
            request_id=request_id,
            verification_id=verification_id,
            cache_hit=False,
            final_status=payload.get("status"),
            verified_item_count=len(payload.get("found_items", [])),
        )
        return payload

    def sources(self, verification_id: str) -> dict[str, Any] | None:
        if self.cache is None:
            return None
        result = self.cache.get_verification_result(str(verification_id or "").strip())
        if result is None:
            return None
        return {
            "verification_id": result.verification_id,
            "status": result.status.value,
            "found_items": [item.to_dict() for item in result.found_items if item.verified],
            "verification_timestamp": result.verification_timestamp,
        }

    def retry(self, verification_id: str) -> dict[str, Any] | None:
        if self.cache is None:
            return None
        key = str(verification_id or "").strip()
        context = self.cache.get_verification_context(key)
        if not context:
            return None
        trigger_value = context.get("trigger")
        plan_value = context.get("search_plan")
        if not isinstance(trigger_value, Mapping) or not isinstance(plan_value, Mapping):
            return None
        trigger = _trigger_from_dict(trigger_value)
        plan = _plan_from_dict(plan_value)
        request_id = str(uuid4())
        result = self._execute(
            trigger,
            plan,
            subject=str(context.get("subject") or "")[:400] or None,
            request_id=request_id,
            verification_id=key,
            force_refresh=True,
        )
        material = self._cache_material(trigger, plan)
        cache_key = Section4Cache.query_cache_key(material)
        payload = _public_result(result, trigger)
        self.cache.put_query_result(cache_key, payload)
        self.cache.put_verification_result(
            result,
            context={"trigger": trigger.to_dict(), "search_plan": plan.to_dict(), "subject": context.get("subject")},
            query_cache_key=cache_key,
            ttl_seconds=max(self.config.cache_ttl_seconds, 86_400),
        )
        return payload

    def health(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "live_verification_enabled": self.config.live_verification_enabled,
            "local_index_enabled": self.config.local_index_enabled,
            "cache": "ready" if self.cache is not None else "unavailable",
            "sources": [item.to_dict() for item in self.registry.health_check()],
        }


_default_service: Section4VerificationService | None = None
_default_lock = threading.Lock()


def get_default_service() -> Section4VerificationService:
    global _default_service
    if _default_service is None:
        with _default_lock:
            if _default_service is None:
                _default_service = Section4VerificationService()
    return _default_service


def verify_section4(
    query: str,
    rti_extraction: Mapping[str, Any] | None = None,
    legal_analysis: Mapping[str, Any] | None = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    try:
        return get_default_service().verify(
            query,
            rti_extraction,
            legal_analysis,
            force_refresh=force_refresh,
        )
    except Exception:
        trigger = detect_section4_trigger(str(query or ""), legal_analysis or {})
        result = (
            source_unavailable_result(trigger, error_code="VERIFIER_UNAVAILABLE")
            if trigger.triggered
            else search_not_triggered_result(trigger)
        )
        return _public_result(result, trigger)


def get_verification_sources(verification_id: str) -> dict[str, Any] | None:
    return get_default_service().sources(verification_id)


def retry_section4_verification(verification_id: str) -> dict[str, Any] | None:
    return get_default_service().retry(verification_id)


def section4_health() -> dict[str, Any]:
    return get_default_service().health()
