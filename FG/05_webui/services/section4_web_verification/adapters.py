from __future__ import annotations

import re
import socket
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from typing import Any, TYPE_CHECKING
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connectionpool import HTTPSConnectionPool

from .config import Section4Config
from .extractors import (
    DownloadedPayload,
    ExtractionError,
    extract_document,
    extract_links,
    utc_now_iso,
)
from .schemas import RetrievedDocument, SearchCandidate, SearchPlan, SourceHealth
from .rate_limiter import (
    CircuitOpenError,
    DailyRequestLimitError,
    SyncDomainRateLimiter,
)
from .security import (
    Resolver,
    SecurityError,
    enforce_content_length,
    normalize_hostname,
    validate_content_type,
    validate_public_url,
)

if TYPE_CHECKING:
    from .cache import Section4Cache


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SAFE_CONDITIONAL_HEADERS = frozenset({"if-none-match", "if-modified-since"})
_TOKEN_PATTERN = re.compile(r"[^\W_]{2,}", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "and",
        "for",
        "from",
        "information",
        "official",
        "please",
        "section",
        "the",
        "under",
        "with",
        "about",
        "that",
        "this",
        "का",
        "की",
        "के",
        "और",
        "लिए",
    }
)


class AdapterError(RuntimeError):
    """A bounded, user-safe source adapter failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code or "ADAPTER_ERROR")[:80]


class HttpNotModified(AdapterError):
    def __init__(self, final_url: str, domain: str):
        super().__init__("HTTP_NOT_MODIFIED", "The official source was not modified.")
        self.final_url = final_url
        self.domain = domain


class _RetryableHttpStatus(requests.RequestException):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"retryable official-source status: {status_code}")


def _header(headers: Mapping[str, Any], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == target:
            cleaned = str(value).strip()
            return cleaned or None
    return None


def _conditional_headers(values: Mapping[str, Any] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (values or {}).items():
        normalised = str(key).strip().casefold()
        if normalised not in _SAFE_CONDITIONAL_HEADERS:
            continue
        cleaned = str(value or "").strip()
        if not cleaned or "\r" in cleaned or "\n" in cleaned:
            continue
        canonical = "If-None-Match" if normalised == "if-none-match" else "If-Modified-Since"
        result[canonical] = cleaned[:512]
    return result


class _PinnedHTTPSAdapter(HTTPAdapter):
    """Connect to one validated public IP while verifying the original host.

    The URL and Host header remain the approved government hostname. Only the
    TCP destination is pinned, closing the DNS-validation/connection TOCTOU
    gap without weakening TLS SNI or certificate hostname verification.
    """

    def __init__(self, hostname: str, address: str, port: int) -> None:
        super().__init__(pool_connections=1, pool_maxsize=1, max_retries=0, pool_block=True)
        self.hostname = hostname
        self.address = address
        self.port = port
        self._direct_pools: list[HTTPSConnectionPool] = []

    def get_connection(self, url: str, proxies=None):  # noqa: ARG002
        parsed = urlsplit(url)
        if parsed.scheme.casefold() != "https" or normalize_hostname(parsed.hostname or "") != self.hostname:
            raise requests.exceptions.InvalidURL("Pinned adapter host mismatch")
        pool = HTTPSConnectionPool(
            host=self.address,
            port=self.port,
            maxsize=1,
            block=True,
            assert_hostname=self.hostname,
            server_hostname=self.hostname,
        )
        self._direct_pools.append(pool)
        return pool

    def close(self) -> None:
        for pool in self._direct_pools:
            pool.close()
        self._direct_pools.clear()
        super().close()


def _preferred_public_address(addresses: Iterable[str]) -> str:
    values = tuple(str(item) for item in addresses)
    if not values:
        raise SecurityError("DNS_NO_ADDRESSES", "Approved hostname resolved to no usable address.")
    # Prefer IPv4 where both families are advertised because several public
    # government hosts publish IPv6 without a consistently reachable route.
    return next((item for item in values if ":" not in item), values[0])


class SafeHttpClient:
    """Small synchronous HTTP client enforcing the reviewed source boundary.

    A new session is requested for every top-level fetch. Redirects are followed
    manually, and cookies are cleared before and after every hop.
    """

    def __init__(
        self,
        config: Section4Config,
        *,
        resolver: Resolver = socket.getaddrinfo,
        session_factory: Callable[[], requests.Session] = requests.Session,
        rate_limiter: SyncDomainRateLimiter | None = None,
    ) -> None:
        self.config = config
        self.resolver = resolver
        self.session_factory = session_factory
        self.rate_limiter = rate_limiter or SyncDomainRateLimiter(config)

    @staticmethod
    def _clear_cookies(session: Any) -> None:
        cookies = getattr(session, "cookies", None)
        clear = getattr(cookies, "clear", None)
        if callable(clear):
            clear()

    @staticmethod
    def _close_response(response: Any) -> None:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    def fetch(
        self,
        url: str,
        *,
        allowed_domains: Iterable[str] | None = None,
        conditional_headers: Mapping[str, Any] | None = None,
    ) -> DownloadedPayload:
        domains = frozenset(allowed_domains or self.config.allowed_domains)
        if not domains:
            raise AdapterError("SOURCE_NOT_CONFIGURED", "No approved source host is configured.")

        requested = validate_public_url(
            url,
            domains,
            resolver=self.resolver,
        ).url
        current_url = requested
        safe_conditionals = _conditional_headers(conditional_headers)
        session = self.session_factory()
        response: Any | None = None
        pinned_adapters: list[_PinnedHTTPSAdapter] = []

        try:
            session.trust_env = False
            if hasattr(session, "auth"):
                session.auth = None
            session_headers = getattr(session, "headers", None)
            clear_headers = getattr(session_headers, "clear", None)
            if callable(clear_headers):
                clear_headers()

            for redirect_count in range(self.config.max_redirects + 1):
                validated = validate_public_url(
                    current_url,
                    domains,
                    resolver=self.resolver,
                )
                headers = {
                    "User-Agent": self.config.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/pdf,application/xml,text/xml;q=0.9,*/*;q=0.1",
                }
                if redirect_count == 0:
                    headers.update(safe_conditionals)

                try:
                    def request_once():
                        # Retries are new outbound requests too. Resolve and
                        # validate again so a DNS change cannot bypass the
                        # public-address policy between attempts.
                        request_target = validate_public_url(
                            validated.url,
                            domains,
                            resolver=self.resolver,
                        )
                        request_headers = dict(headers)
                        request_headers["Host"] = request_target.hostname
                        if isinstance(session, requests.Session):
                            pinned = _PinnedHTTPSAdapter(
                                request_target.hostname,
                                _preferred_public_address(request_target.resolved_addresses),
                                request_target.port,
                            )
                            session.mount(f"https://{request_target.hostname}/", pinned)
                            pinned_adapters.append(pinned)
                        self._clear_cookies(session)
                        try:
                            result = session.get(
                                request_target.url,
                                headers=request_headers,
                                allow_redirects=False,
                                stream=True,
                                timeout=(
                                    self.config.connect_timeout_seconds,
                                    self.config.request_timeout_seconds,
                                ),
                                verify=True,
                            )
                            status = int(getattr(result, "status_code", 0) or 0)
                            if status == 429 or 500 <= status < 600:
                                self._close_response(result)
                                raise _RetryableHttpStatus(status)
                            return result
                        finally:
                            self._clear_cookies(session)

                    response = self.rate_limiter.run(
                        validated.hostname,
                        request_once,
                        retry_if=lambda error: isinstance(
                            error,
                            (requests.Timeout, requests.ConnectionError, _RetryableHttpStatus),
                        ),
                    )
                except CircuitOpenError as error:
                    raise AdapterError(
                        "CIRCUIT_OPEN",
                        "The official source is temporarily unavailable.",
                    ) from error
                except DailyRequestLimitError as error:
                    raise AdapterError(
                        "DAILY_REQUEST_LIMIT",
                        "The approved daily request budget for this official source has been reached.",
                    ) from error
                except _RetryableHttpStatus as error:
                    code = "HTTP_RATE_LIMITED" if error.status_code == 429 else "HTTP_SERVER_ERROR"
                    raise AdapterError(
                        code,
                        "The official source remained temporarily unavailable after bounded retries.",
                    ) from error
                except requests.Timeout as error:
                    raise AdapterError("HTTP_TIMEOUT", "The official source request timed out.") from error
                except requests.RequestException as error:
                    raise AdapterError(
                        "HTTP_REQUEST_FAILED",
                        "The official source request could not be completed.",
                    ) from error
                status_code = int(getattr(response, "status_code", 0) or 0)
                response_headers = getattr(response, "headers", {}) or {}

                if status_code in _REDIRECT_STATUSES:
                    location = _header(response_headers, "location")
                    self._close_response(response)
                    response = None
                    if not location:
                        raise AdapterError(
                            "REDIRECT_LOCATION_MISSING",
                            "The official source returned an invalid redirect.",
                        )
                    if redirect_count >= self.config.max_redirects:
                        raise AdapterError(
                            "REDIRECT_LIMIT_EXCEEDED",
                            "The official source exceeded the redirect limit.",
                        )
                    current_url = urljoin(validated.url, location)
                    # The target is deliberately revalidated at the top of the
                    # next loop before any network request is made.
                    continue

                if status_code == 304:
                    self._close_response(response)
                    response = None
                    raise HttpNotModified(validated.url, validated.hostname)

                if not 200 <= status_code < 300:
                    self._close_response(response)
                    response = None
                    if 400 <= status_code < 500:
                        code = "HTTP_CLIENT_ERROR"
                    elif 500 <= status_code < 600:
                        code = "HTTP_SERVER_ERROR"
                    else:
                        code = "HTTP_STATUS_REJECTED"
                    raise AdapterError(code, "The official source returned an unusable status.")

                content_type = validate_content_type(_header(response_headers, "content-type"))
                maximum = (
                    self.config.max_pdf_bytes
                    if content_type == "application/pdf"
                    else self.config.max_html_bytes
                )
                enforce_content_length(_header(response_headers, "content-length"), maximum)

                chunks: list[bytes] = []
                byte_count = 0
                try:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        value = bytes(chunk)
                        byte_count += len(value)
                        if byte_count > maximum:
                            raise SecurityError(
                                "RESPONSE_TOO_LARGE",
                                "Response exceeds the configured size limit.",
                            )
                        chunks.append(value)
                except SecurityError:
                    raise
                except requests.RequestException as error:
                    raise AdapterError(
                        "HTTP_STREAM_FAILED",
                        "The official source response could not be read safely.",
                    ) from error

                safe_headers = {
                    key: value
                    for key in ("etag", "last-modified", "content-length", "content-type")
                    if (value := _header(response_headers, key)) is not None
                }
                payload = DownloadedPayload(
                    requested_url=requested,
                    final_url=validated.url,
                    domain=validated.hostname,
                    status_code=status_code,
                    content_type=content_type,
                    content=b"".join(chunks),
                    retrieved_at=utc_now_iso(),
                    headers=safe_headers,
                )
                self._close_response(response)
                response = None
                return payload

            raise AdapterError(
                "REDIRECT_LIMIT_EXCEEDED",
                "The official source exceeded the redirect limit.",
            )
        finally:
            if response is not None:
                self._close_response(response)
            self._clear_cookies(session)
            close_session = getattr(session, "close", None)
            if callable(close_session):
                close_session()
            for pinned in pinned_adapters:
                pinned.close()

    get = fetch


class BaseSourceAdapter(ABC):
    @abstractmethod
    def search(self, search_plan: SearchPlan) -> list[SearchCandidate]:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, candidate: SearchCandidate) -> RetrievedDocument:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> SourceHealth:
        raise NotImplementedError


class ConfiguredSourceAdapter(BaseSourceAdapter):
    adapter_id = ""
    domains: tuple[str, ...] = ()
    seed_urls: tuple[str, ...] = ()
    source_type = "page"
    supports_link_discovery = True
    official_search_templates: tuple[str, ...] = ()

    def __init__(
        self,
        config: Section4Config,
        *,
        http_client: SafeHttpClient | None = None,
        cache: Section4Cache | None = None,
    ) -> None:
        if not self.adapter_id or not self.domains or not self.seed_urls:
            raise TypeError("Configured adapters require an ID, domains, and fixed seeds")
        self.config = config
        self.http_client = http_client or SafeHttpClient(config)
        self.cache = cache
        configured = {normalize_hostname(item) for item in config.allowed_domains}
        self.active_domains = tuple(
            domain
            for value in self.domains
            if (domain := normalize_hostname(value)) in configured
        )
        self._last_error_code: str | None = None
        self._last_checked_at: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self.active_domains)

    @property
    def domain(self) -> str:
        return self.active_domains[0] if self.active_domains else normalize_hostname(self.domains[0])

    def _record_success(self) -> None:
        self._last_error_code = None
        self._last_checked_at = utc_now_iso()

    def _record_error(self, error: Exception) -> None:
        self._last_error_code = str(getattr(error, "code", "SOURCE_UNAVAILABLE"))[:80]
        self._last_checked_at = utc_now_iso()

    def _normalise_candidate_url(self, url: str) -> str | None:
        raw = str(url or "").strip()
        if not raw or len(raw) > 2048 or "\\" in raw:
            return None
        try:
            parsed = urlsplit(raw)
            host = normalize_hostname(parsed.hostname or "")
            port = parsed.port
        except (SecurityError, ValueError):
            return None
        if (
            parsed.scheme.casefold() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or host not in self.active_domains
            or port not in (None, 443)
        ):
            return None
        return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))

    @staticmethod
    def _plan_terms(search_plan: SearchPlan) -> tuple[str, ...]:
        values: list[str] = [*search_plan.search_queries, *search_plan.search_concepts]
        for entity in (
            search_plan.organisation,
            search_plan.public_authority,
            search_plan.department,
            search_plan.company,
            search_plan.project,
            search_plan.district,
            search_plan.scheme,
        ):
            if entity.name:
                values.append(entity.name)
            values.extend(entity.aliases)
        values.extend(search_plan.requested_record_types)
        values.extend(search_plan.requested_fields)
        values.extend(
            item
            for item in (search_plan.tender_number, search_plan.contract_number)
            if item
        )
        tokens = (
            match.group(0).casefold()
            for value in values
            for match in _TOKEN_PATTERN.finditer(str(value))
        )
        return tuple(dict.fromkeys(token for token in tokens if token not in _STOP_WORDS))[:80]

    @classmethod
    def _score(cls, title: str, url: str, terms: tuple[str, ...]) -> float:
        if not terms:
            return 0.01
        title_value = str(title or "").casefold()
        url_value = str(url or "").casefold()
        matched = sum(
            (3.0 if term in title_value else 0.0) + (1.0 if term in url_value else 0.0)
            for term in terms
        )
        return round(matched / max(1, len(terms)), 6)

    def _cached_candidates(self, search_plan: SearchPlan) -> list[SearchCandidate]:
        if self.cache is None or not self.config.local_index_enabled:
            return []
        query = " ".join(search_plan.search_queries or search_plan.search_concepts).strip()
        if not query:
            return []
        try:
            hits = self.cache.search_documents(
                query,
                limit=self.config.max_results_per_source * 2,
            )
        except Exception:
            return []
        candidates: list[SearchCandidate] = []
        for hit in hits:
            document = hit.document
            url = self._normalise_candidate_url(document.final_url or document.url)
            if url is None:
                continue
            candidates.append(
                SearchCandidate(
                    adapter_id=self.adapter_id,
                    url=url,
                    title=document.title,
                    source_type=document.source_type or self.source_type,
                    discovered_from="local_index",
                    lexical_score=float(hit.score),
                )
            )
        return candidates

    def _official_search_entries(self, search_plan: SearchPlan) -> tuple[str, ...]:
        """Build bounded, same-host official search URLs from server templates."""
        if not self.official_search_templates or not self.config.live_verification_enabled:
            return ()
        queries = search_plan.search_queries or search_plan.search_concepts
        entries: list[str] = []
        for query in queries[:2]:
            cleaned = re.sub(r"\s+", " ", str(query or "")).strip()[:240]
            if not cleaned:
                continue
            encoded = quote_plus(cleaned)
            for template in self.official_search_templates:
                candidate = self._normalise_candidate_url(template.format(query=encoded))
                if candidate and candidate not in entries:
                    entries.append(candidate)
        return tuple(entries)

    def search(self, search_plan: SearchPlan) -> list[SearchCandidate]:
        if not isinstance(search_plan, SearchPlan):
            raise TypeError("search_plan must be a SearchPlan")
        if not self.enabled:
            return []

        terms = self._plan_terms(search_plan)
        found: dict[str, SearchCandidate] = {
            item.url: item for item in self._cached_candidates(search_plan)
        }
        successful_entry = False

        entry_urls = tuple((url, "fixed_seed") for url in self.seed_urls) + tuple(
            (url, "official_search") for url in self._official_search_entries(search_plan)
        )
        seen_entries: set[str] = set()
        for entry_url, entry_kind in entry_urls:
            seed = self._normalise_candidate_url(entry_url)
            if seed in seen_entries:
                continue
            if seed is None:
                continue
            seen_entries.add(seed)
            found.setdefault(
                seed,
                SearchCandidate(
                    adapter_id=self.adapter_id,
                    url=seed,
                    title=seed.rsplit("/", 1)[-1] or self.adapter_id,
                    source_type=self.source_type,
                    discovered_from=entry_kind,
                    lexical_score=self._score("", seed, terms),
                ),
            )
            if not self.config.live_verification_enabled or not self.supports_link_discovery:
                continue
            try:
                payload = self.http_client.fetch(seed, allowed_domains=self.active_domains)
                successful_entry = True
                if payload.content_type not in {
                    "text/html",
                    "application/xhtml+xml",
                    "application/xml",
                    "text/xml",
                }:
                    continue
                for title, discovered_url in extract_links(payload)[
                    : self.config.max_results_per_source * 5
                ]:
                    candidate_url = self._normalise_candidate_url(discovered_url)
                    if candidate_url is None:
                        continue
                    source_type = "pdf" if urlsplit(candidate_url).path.casefold().endswith(".pdf") else self.source_type
                    candidate = SearchCandidate(
                        adapter_id=self.adapter_id,
                        url=candidate_url,
                        title=str(title or "")[:300] or None,
                        source_type=source_type,
                        discovered_from=seed,
                        lexical_score=self._score(title, candidate_url, terms),
                    )
                    previous = found.get(candidate_url)
                    if previous is None or candidate.lexical_score > previous.lexical_score:
                        found[candidate_url] = candidate
            except (AdapterError, SecurityError, ExtractionError) as error:
                self._record_error(error)

        if successful_entry:
            self._record_success()
        ranked = sorted(
            found.values(),
            key=lambda item: (-item.lexical_score, item.title or "", item.url),
        )
        return ranked[: self.config.max_results_per_source]

    def _conditional_document_headers(self, url: str) -> dict[str, str]:
        if self.cache is None:
            return {}
        try:
            metadata = self.cache.get_document_metadata(url)
        except Exception:
            return {}
        if not metadata:
            return {}
        values: dict[str, str] = {}
        if metadata.get("etag"):
            values["If-None-Match"] = str(metadata["etag"])
        if metadata.get("last_modified"):
            values["If-Modified-Since"] = str(metadata["last_modified"])
        return values

    def fetch(self, candidate: SearchCandidate) -> RetrievedDocument:
        if not isinstance(candidate, SearchCandidate):
            raise TypeError("candidate must be a SearchCandidate")
        if candidate.adapter_id != self.adapter_id:
            raise AdapterError("ADAPTER_MISMATCH", "The candidate belongs to another source adapter.")
        candidate_url = self._normalise_candidate_url(candidate.url)
        if not self.enabled or candidate_url is None:
            raise AdapterError("SOURCE_NOT_CONFIGURED", "The source URL is not configured for this adapter.")

        if not self.config.live_verification_enabled:
            cached = self.cache.get_document(candidate_url) if self.cache is not None else None
            if cached is not None:
                return cached
            raise AdapterError(
                "LIVE_RETRIEVAL_DISABLED",
                "Live retrieval is disabled and no cached public document is available.",
            )

        conditional = self._conditional_document_headers(candidate_url)
        try:
            payload = self.http_client.fetch(
                candidate_url,
                allowed_domains=self.active_domains,
                conditional_headers=conditional,
            )
        except HttpNotModified as error:
            cached = (
                self.cache.get_document(candidate_url, include_expired=True)
                if self.cache is not None
                else None
            )
            if cached is None:
                failure = AdapterError(
                    "CACHE_MISS_ON_304",
                    "The source returned not-modified without a usable cached document.",
                )
                self._record_error(failure)
                raise failure from error
            self.cache.touch_document(candidate_url)
            self._record_success()
            return cached
        except (AdapterError, SecurityError) as error:
            self._record_error(error)
            raise

        try:
            document = extract_document(payload, self.adapter_id, self.config)
        except ExtractionError as error:
            self._record_error(error)
            raise
        if self.cache is not None:
            try:
                self.cache.put_document(document)
            except Exception:
                # Retrieval success must not be rewritten as source failure when
                # the optional local cache is unavailable.
                pass
        self._record_success()
        return document

    def health_check(self) -> SourceHealth:
        if not self.config.enabled:
            status = "disabled"
            error_code = "FEATURE_DISABLED"
        elif not self.active_domains:
            status = "unconfigured"
            error_code = "SOURCE_NOT_CONFIGURED"
        elif self._last_error_code:
            status = "degraded"
            error_code = self._last_error_code
        else:
            status = "ready"
            error_code = None
        return SourceHealth(
            adapter_id=self.adapter_id,
            domain=self.domain,
            enabled=self.enabled,
            status=status,
            checked_at=self._last_checked_at,
            error_code=error_code,
        )


class SupremeCourtAdapter(ConfiguredSourceAdapter):
    adapter_id = "sci_public"
    domains = ("www.sci.gov.in", "sci.gov.in")
    seed_urls = (
        "https://www.sci.gov.in/sitemap/",
        "https://www.sci.gov.in/rti/",
        "https://www.sci.gov.in/notice-category/tenders/",
        "https://www.sci.gov.in/judgements-case-no/",
        "https://www.sci.gov.in/daily-order-case-no/",
    )
    # Public WordPress search. CAPTCHA-protected judgment forms remain excluded.
    official_search_templates = ("https://www.sci.gov.in/?s={query}",)
    source_type = "official_page"


class CentralInformationCommissionAdapter(ConfiguredSourceAdapter):
    adapter_id = "cic_disclosures"
    domains = ("cic.gov.in", "www.cic.gov.in")
    seed_urls = (
        "https://cic.gov.in/sitemap",
        "https://cic.gov.in/rti-disclosoures",
        "https://cic.gov.in/tender-notification",
        "https://cic.gov.in/archive-tender-notification",
        "https://cic.gov.in/decision",
    )
    source_type = "disclosure_page"


class ChhattisgarhSICAdapter(ConfiguredSourceAdapter):
    adapter_id = "siccg_disclosures"
    domains = ("siccg.gov.in", "www.siccg.gov.in")
    seed_urls = ("https://siccg.gov.in/sec_4_1_XV_13.html",)
    source_type = "disclosure_page"


class ChhattisgarhRTIOnlineAdapter(ConfiguredSourceAdapter):
    adapter_id = "cg_rti_online"
    domains = ("rtionline.cg.gov.in", "www.rtionline.cg.gov.in")
    seed_urls = (
        "https://rtionline.cg.gov.in/",
        "https://www.rtionline.cg.gov.in/pioRegstration",
    )
    source_type = "public_gateway"
    supports_link_discovery = False


class DepartmentWebsiteAdapter(ConfiguredSourceAdapter):
    """One operator-configured official department root; never query-derived."""

    source_type = "department_page"

    def __init__(
        self,
        config: Section4Config,
        domain: str,
        *,
        http_client: SafeHttpClient | None = None,
        cache: Section4Cache | None = None,
    ) -> None:
        normalised = normalize_hostname(domain)
        if normalised not in {
            normalize_hostname(item) for item in config.department_domains
        }:
            raise ValueError("Department sources must come from operator configuration")
        self.adapter_id = f"department_{normalised.replace('.', '_')}"
        self.domains = (normalised,)
        self.seed_urls = (f"https://{normalised}/",)
        super().__init__(config, http_client=http_client, cache=cache)


class ChhattisgarhEprocCurrentAdapter(ConfiguredSourceAdapter):
    adapter_id = "cg_eproc_current"
    domains = ("cgeproc.cgstate.gov.in",)
    seed_urls = (
        "https://cgeproc.cgstate.gov.in/nicgep/app",
        "https://cgeproc.cgstate.gov.in/nicgep/app?page=FrontEndAdvancedSearch&service=page",
        "https://cgeproc.cgstate.gov.in/nicgep/app?page=FrontEndLatestActiveTenders&service=page",
        "https://cgeproc.cgstate.gov.in/nicgep/app?page=FrontEndListTendersbyDate&service=page",
        "https://cgeproc.cgstate.gov.in/nicgep/app?page=FrontEndLatestActiveCorrigendums&service=page",
        "https://cgeproc.cgstate.gov.in/nicgep/app?page=ResultOfTenders&service=page",
        "https://cgeproc.cgstate.gov.in/nicgep/app?page=WebAwards&service=page",
        "https://cgeproc.cgstate.gov.in/nicgep/app?page=SiteMap&service=page",
    )
    source_type = "procurement_page"


class ChhattisgarhEprocLegacyAdapter(ConfiguredSourceAdapter):
    adapter_id = "cg_eproc_legacy"
    domains = ("eproc.cgstate.gov.in",)
    seed_urls = (
        "https://eproc.cgstate.gov.in/",
        "https://eproc.cgstate.gov.in/CHEPS/security/getSignInAction.do",
    )
    source_type = "procurement_page"


class GovernmentEMarketplaceAdapter(ConfiguredSourceAdapter):
    adapter_id = "gem_procurement"
    domains = ("gem.gov.in", "bidplus.gem.gov.in")
    seed_urls = (
        "https://gem.gov.in/sitemap",
        "https://gem.gov.in/sitemap.xml",
        "https://bidplus.gem.gov.in/all-bids",
        "https://gem.gov.in/view_contracts",
    )
    # Derived from the public GET search form on the approved GeM domain.
    official_search_templates = ("https://gem.gov.in/searchresult/query/?q={query}",)
    source_type = "procurement_page"


class CentralPublicProcurementAdapter(ConfiguredSourceAdapter):
    adapter_id = "cppp_procurement"
    domains = ("eprocure.gov.in",)
    seed_urls = (
        "https://eprocure.gov.in/eprocure/app",
        "https://eprocure.gov.in/eprocure/app?page=FrontEndAdvancedSearch&service=page",
        "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page",
        "https://eprocure.gov.in/eprocure/app?page=FrontEndListTendersbyDate&service=page",
        "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveCorrigendums&service=page",
        "https://eprocure.gov.in/eprocure/app?page=FrontEndTendersInArchive&service=page",
        "https://eprocure.gov.in/eprocure/app?page=SiteMap&service=page",
        "https://eprocure.gov.in/epublish/app?service=home",
    )
    source_type = "procurement_page"
