import socket
import sys
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "FG" / "05_webui"
sys.path.insert(0, str(WEBUI_DIR))

from services.section4_web_verification.adapters import (  # noqa: E402
    AdapterError,
    CentralInformationCommissionAdapter,
    ChhattisgarhEprocCurrentAdapter,
    ChhattisgarhEprocLegacyAdapter,
    DepartmentWebsiteAdapter,
    GovernmentEMarketplaceAdapter,
    HttpNotModified,
    SafeHttpClient,
    SupremeCourtAdapter,
)
from services.section4_web_verification.config import Section4Config  # noqa: E402
from services.section4_web_verification.extractors import DownloadedPayload  # noqa: E402
from services.section4_web_verification.rate_limiter import (  # noqa: E402
    SyncDomainRateLimiter,
)
from services.section4_web_verification.schemas import (  # noqa: E402
    RetrievedDocument,
    SearchCandidate,
    SearchPlan,
    TenderIntent,
)
from services.section4_web_verification.security import SecurityError  # noqa: E402
from services.section4_web_verification.source_registry import (  # noqa: E402
    NORMAL_ADAPTER_IDS,
    TENDER_ADAPTER_IDS,
    SourceRegistry,
)


def _resolver(address="93.184.216.34", calls=None):
    def resolve(host, port, type=socket.SOCK_STREAM):
        if calls is not None:
            calls.append((host, port))
        return [(socket.AF_INET, type, 6, "", (address, port))]

    return resolve


class _Cookies:
    def __init__(self):
        self.clear_count = 0

    def clear(self):
        self.clear_count += 1


class _Response:
    def __init__(self, status_code, *, headers=None, chunks=()):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.closed = False

    def iter_content(self, chunk_size):
        assert chunk_size == 64 * 1024
        yield from self._chunks

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.trust_env = True
        self.auth = ("should", "be-cleared")
        self.headers = {"Cookie": "must-not-leak", "Authorization": "must-not-leak"}
        self.cookies = _Cookies()
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.scripted.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


class _RecordingRequestsSession(requests.Session):
    def __init__(self, response):
        super().__init__()
        self.response = response
        self.calls = []
        self.pinned_mounts = []

    def mount(self, prefix, adapter):
        super().mount(prefix, adapter)
        if hasattr(adapter, "address"):
            self.pinned_mounts.append((prefix, adapter))

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class _Limiter:
    def __init__(self):
        self.domains = []

    def run(self, domain, operation, **kwargs):
        self.domains.append(domain)
        return operation()


def _client(session, **config_values):
    config = Section4Config(
        allowed_domains=frozenset({"cic.gov.in"}),
        **config_values,
    )
    limiter = _Limiter()
    client = SafeHttpClient(
        config,
        resolver=_resolver(),
        session_factory=lambda: session,
        rate_limiter=limiter,
    )
    client.test_limiter = limiter
    return client


def test_safe_http_client_disables_environment_credentials_and_streams_response():
    response = _Response(
        200,
        headers={
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": "13",
            "ETag": '"v1"',
            "Set-Cookie": "secret=must-not-be-returned",
        },
        chunks=(b"<html>", b"ok</html>"),
    )
    session = _Session([response])

    client = _client(session)
    payload = client.fetch(
        "https://cic.gov.in/start#ignored",
        allowed_domains={"cic.gov.in"},
    )

    assert payload.content == b"<html>ok</html>"
    assert payload.final_url == "https://cic.gov.in/start"
    assert payload.headers == {
        "etag": '"v1"',
        "content-length": "13",
        "content-type": "text/html; charset=utf-8",
    }
    assert session.trust_env is False
    assert session.auth is None
    assert session.headers == {}
    assert session.cookies.clear_count >= 3
    assert session.closed is True
    assert response.closed is True
    _, request_options = session.calls[0]
    assert request_options["allow_redirects"] is False
    assert request_options["stream"] is True
    assert request_options["verify"] is True
    assert "Cookie" not in request_options["headers"]
    assert "Authorization" not in request_options["headers"]
    assert client.test_limiter.domains == ["cic.gov.in"]


def test_real_requests_session_pins_validated_ip_and_preserves_tls_hostname():
    response = _Response(
        200,
        headers={"Content-Type": "text/html", "Content-Length": "2"},
        chunks=(b"ok",),
    )
    session = _RecordingRequestsSession(response)
    config = Section4Config(allowed_domains=frozenset({"cic.gov.in"}))
    client = SafeHttpClient(
        config,
        resolver=_resolver("93.184.216.34"),
        session_factory=lambda: session,
        rate_limiter=_Limiter(),
    )

    payload = client.fetch("https://cic.gov.in/sitemap")

    assert payload.content == b"ok"
    assert session.pinned_mounts
    prefix, adapter = session.pinned_mounts[-1]
    assert prefix == "https://cic.gov.in/"
    assert adapter.address == "93.184.216.34"
    assert adapter.hostname == "cic.gov.in"
    assert session.calls[0][1]["headers"]["Host"] == "cic.gov.in"
    assert response.closed is True


def test_redirect_target_is_revalidated_before_second_request():
    redirect = _Response(302, headers={"Location": "https://evil.example/private"})
    session = _Session([redirect])

    with pytest.raises(SecurityError) as raised:
        _client(session).fetch("https://cic.gov.in/start")

    assert raised.value.code == "HOST_NOT_ALLOWED"
    assert len(session.calls) == 1
    assert redirect.closed is True


def test_allowed_redirect_is_manual_and_drops_conditional_headers_on_next_hop():
    redirect = _Response(302, headers={"Location": "/final"})
    final = _Response(
        200,
        headers={"Content-Type": "text/html"},
        chunks=(b"<html>public</html>",),
    )
    session = _Session([redirect, final])
    dns_calls = []
    config = Section4Config(allowed_domains=frozenset({"cic.gov.in"}))
    client = SafeHttpClient(
        config,
        resolver=_resolver(calls=dns_calls),
        session_factory=lambda: session,
        rate_limiter=_Limiter(),
    )

    payload = client.fetch(
        "https://cic.gov.in/start",
        conditional_headers={
            "If-None-Match": '"v1"',
            "Cookie": "ignored",
        },
    )

    assert payload.final_url == "https://cic.gov.in/final"
    assert len(session.calls) == 2
    assert session.calls[0][1]["headers"]["If-None-Match"] == '"v1"'
    assert "If-None-Match" not in session.calls[1][1]["headers"]
    assert all(host == "cic.gov.in" for host, _port in dns_calls)


def test_conditional_304_is_a_typed_non_error_signal():
    response = _Response(304, headers={"ETag": '"v1"'})
    session = _Session([response])

    with pytest.raises(HttpNotModified) as raised:
        _client(session).fetch(
            "https://cic.gov.in/disclosure",
            conditional_headers={"If-None-Match": '"v1"'},
        )

    assert raised.value.code == "HTTP_NOT_MODIFIED"
    assert raised.value.domain == "cic.gov.in"
    assert session.calls[0][1]["headers"]["If-None-Match"] == '"v1"'


def test_retry_revalidates_dns_and_rate_limits_each_outbound_get():
    response = _Response(
        200,
        headers={"Content-Type": "text/html"},
        chunks=(b"<html>ok</html>",),
    )
    session = _Session([requests.Timeout("first attempt"), response])
    dns_calls = []
    config = Section4Config(
        allowed_domains=frozenset({"cic.gov.in"}),
        circuit_failure_threshold=10,
    )
    limiter = SyncDomainRateLimiter(
        config,
        max_attempts=2,
        sleep=lambda _delay: None,
    )
    client = SafeHttpClient(
        config,
        resolver=_resolver(calls=dns_calls),
        session_factory=lambda: session,
        rate_limiter=limiter,
    )

    payload = client.fetch("https://cic.gov.in/retry")

    assert payload.content == b"<html>ok</html>"
    assert len(session.calls) == 2
    assert len(dns_calls) >= 4
    assert all(host == "cic.gov.in" for host, _port in dns_calls)


def test_stream_limit_is_enforced_when_content_length_is_missing():
    response = _Response(
        200,
        headers={"Content-Type": "text/html"},
        chunks=(b"123", b"456"),
    )
    session = _Session([response])

    with pytest.raises(SecurityError) as raised:
        _client(session, max_html_bytes=5).fetch("https://cic.gov.in/large")

    assert raised.value.code == "RESPONSE_TOO_LARGE"
    assert response.closed is True


def test_mime_type_and_timeout_failures_are_sanitized():
    bad_mime = _Session(
        [_Response(200, headers={"Content-Type": "application/octet-stream"})]
    )
    with pytest.raises(SecurityError) as mime_error:
        _client(bad_mime).fetch("https://cic.gov.in/file")
    assert mime_error.value.code == "MIME_NOT_ALLOWED"

    timeout = _Session([requests.Timeout("internal host detail")])
    with pytest.raises(AdapterError) as timeout_error:
        _client(timeout).fetch("https://cic.gov.in/slow")
    assert timeout_error.value.code == "HTTP_TIMEOUT"
    assert "internal host detail" not in str(timeout_error.value)


class _StubHttpClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.payload


class _Cache:
    def __init__(self, *, metadata=None, document=None):
        self.metadata = metadata
        self.document = document
        self.put = []

    def get_document_metadata(self, url):
        return self.metadata

    def get_document(self, url, *, include_expired=False):
        return self.document

    def touch_document(self, url):
        self.touched = getattr(self, "touched", [])
        self.touched.append(url)
        return True

    def put_document(self, document):
        self.put.append(document)

    def search_documents(self, query, *, limit):
        return []


def _html_payload(content, url="https://cic.gov.in/sitemap"):
    return DownloadedPayload(
        requested_url=url,
        final_url=url,
        domain="cic.gov.in",
        status_code=200,
        content_type="text/html",
        content=content,
        retrieved_at="2026-07-14T00:00:00+00:00",
        headers={"etag": '"v2"'},
    )


def test_adapter_discovers_and_ranks_links_only_on_its_active_hosts():
    payload = _html_payload(
        b"""
        <html><body>
          <a href='/section-4-disclosure'>Section 4 disclosure register</a>
          <a href='https://evil.example/section-4'>Section 4 copied page</a>
          <a href='https://www.cic.gov.in/other'>Other approved CIC page</a>
        </body></html>
        """
    )
    stub = _StubHttpClient(payload=payload)
    config = Section4Config(
        allowed_domains=frozenset({"cic.gov.in", "www.cic.gov.in"}),
        max_results_per_source=10,
    )
    adapter = CentralInformationCommissionAdapter(config, http_client=stub)

    candidates = adapter.search(
        SearchPlan(
            search_queries=("Section 4 disclosure",),
            search_concepts=("disclosure",),
        )
    )

    assert candidates
    assert candidates[0].url == "https://cic.gov.in/section-4-disclosure"
    assert all("evil.example" not in candidate.url for candidate in candidates)
    assert all(
        candidate.url.startswith(("https://cic.gov.in/", "https://www.cic.gov.in/"))
        for candidate in candidates
    )
    assert all(call[1]["allowed_domains"] == adapter.active_domains for call in stub.calls)


@pytest.mark.parametrize(
    ("adapter_class", "expected_url"),
    (
        (SupremeCourtAdapter, "https://www.sci.gov.in/?s=CHiPS+BharatNet"),
        (
            GovernmentEMarketplaceAdapter,
            "https://gem.gov.in/searchresult/query/?q=CHiPS+BharatNet",
        ),
    ),
)
def test_site_specific_official_search_uses_plan_terms_on_approved_host(
    adapter_class,
    expected_url,
):
    stub = _StubHttpClient(
        payload=_html_payload(b"<html><body>No results</body></html>")
    )
    config = Section4Config(max_results_per_source=20)
    adapter = adapter_class(config, http_client=stub)

    adapter.search(SearchPlan(search_queries=("CHiPS BharatNet",)))

    called_urls = [call[0] for call in stub.calls]
    assert expected_url in called_urls
    assert all(call[1]["allowed_domains"] == adapter.active_domains for call in stub.calls)


def test_adapter_fetch_uses_conditional_headers_and_cached_document_on_304():
    cached = RetrievedDocument(
        source_id="cic_disclosures",
        title="Cached disclosure",
        url="https://cic.gov.in/disclosure",
        final_url="https://cic.gov.in/disclosure",
        domain="cic.gov.in",
        retrieved_at="2026-07-14T00:00:00+00:00",
        content_type="text/html",
    )
    cache = _Cache(
        metadata={
            "etag": '"v1"',
            "last_modified": "Mon, 13 Jul 2026 00:00:00 GMT",
            "is_expired": False,
        },
        document=cached,
    )
    stub = _StubHttpClient(
        error=HttpNotModified("https://cic.gov.in/disclosure", "cic.gov.in")
    )
    adapter = CentralInformationCommissionAdapter(
        Section4Config(allowed_domains=frozenset({"cic.gov.in"})),
        http_client=stub,
        cache=cache,
    )
    candidate = SearchCandidate(
        adapter_id="cic_disclosures",
        url="https://cic.gov.in/disclosure",
    )

    result = adapter.fetch(candidate)

    assert result is cached
    assert stub.calls[0][1]["conditional_headers"] == {
        "If-None-Match": '"v1"',
        "If-Modified-Since": "Mon, 13 Jul 2026 00:00:00 GMT",
    }
    assert cache.touched == ["https://cic.gov.in/disclosure"]


def test_expired_cache_validators_are_sent_and_304_refreshes_the_cached_entry():
    cached = RetrievedDocument(
        source_id="cic_disclosures",
        title="Stale but valid disclosure",
        url="https://cic.gov.in/disclosure",
        final_url="https://cic.gov.in/disclosure",
        domain="cic.gov.in",
        retrieved_at="2026-07-13T00:00:00+00:00",
        content_type="text/html",
    )
    cache = _Cache(
        metadata={"etag": '"stale"', "is_expired": True},
        document=cached,
    )
    stub = _StubHttpClient(
        error=HttpNotModified("https://cic.gov.in/disclosure", "cic.gov.in")
    )
    adapter = CentralInformationCommissionAdapter(
        Section4Config(allowed_domains=frozenset({"cic.gov.in"})),
        http_client=stub,
        cache=cache,
    )

    result = adapter.fetch(
        SearchCandidate(
            adapter_id="cic_disclosures",
            url="https://cic.gov.in/disclosure",
        )
    )

    assert result is cached
    assert stub.calls[0][1]["conditional_headers"] == {
        "If-None-Match": '"stale"'
    }
    assert cache.touched == ["https://cic.gov.in/disclosure"]


def test_adapter_fetch_extracts_and_caches_successful_official_html():
    payload = _html_payload(
        b"<html><head><title>Disclosure</title></head><body><h1>Manual</h1><p>Public record</p></body></html>",
        url="https://cic.gov.in/disclosure",
    )
    cache = _Cache()
    adapter = CentralInformationCommissionAdapter(
        Section4Config(allowed_domains=frozenset({"cic.gov.in"})),
        http_client=_StubHttpClient(payload=payload),
        cache=cache,
    )

    document = adapter.fetch(
        SearchCandidate(
            adapter_id="cic_disclosures",
            url="https://cic.gov.in/disclosure",
        )
    )

    assert document.source_id == "cic_disclosures"
    assert document.title == "Disclosure"
    assert "Public record" in document.pages[0].text
    assert cache.put == [document]


def test_registry_adds_procurement_sources_only_for_explicit_tender_intent():
    config = Section4Config(
        allowed_domains=frozenset(
            {
                "www.sci.gov.in",
                "sci.gov.in",
                "cic.gov.in",
                "www.cic.gov.in",
                "siccg.gov.in",
                "www.siccg.gov.in",
                "rtionline.cg.gov.in",
                "www.rtionline.cg.gov.in",
                "cgeproc.cgstate.gov.in",
                "eproc.cgstate.gov.in",
                "gem.gov.in",
                "bidplus.gem.gov.in",
                "eprocure.gov.in",
            }
        )
    )
    registry = SourceRegistry(config, http_client=_StubHttpClient())

    plain = registry.select(SearchPlan(search_queries=("tender",)))
    tender = registry.select(
        SearchPlan(tender=TenderIntent(tender_intent=True, intent_type="tender"))
    )

    assert tuple(adapter.adapter_id for adapter in plain) == NORMAL_ADAPTER_IDS
    assert tuple(adapter.adapter_id for adapter in tender) == (
        NORMAL_ADAPTER_IDS + TENDER_ADAPTER_IDS
    )
    assert len(registry) == 8


def test_registry_keeps_current_and_legacy_chhattisgarh_portals_distinct():
    config = Section4Config(
        allowed_domains=frozenset(
            {"cgeproc.cgstate.gov.in", "eproc.cgstate.gov.in"}
        )
    )
    current = ChhattisgarhEprocCurrentAdapter(config, http_client=_StubHttpClient())
    legacy = ChhattisgarhEprocLegacyAdapter(config, http_client=_StubHttpClient())

    assert current.adapter_id != legacy.adapter_id
    assert current.domain == "cgeproc.cgstate.gov.in"
    assert legacy.domain == "eproc.cgstate.gov.in"
    assert all("eproc.cgstate.gov.in/CHEPS" not in url for url in current.seed_urls)
    assert any("/CHEPS/" in url for url in legacy.seed_urls)


def test_operator_department_adapter_uses_only_the_configured_https_root_seed():
    config = Section4Config(
        allowed_domains=frozenset({"education.gov.in"}),
        department_domains=frozenset({"education.gov.in"}),
    )
    registry = SourceRegistry(config, http_client=_StubHttpClient())

    selected_ids = tuple(
        adapter.adapter_id for adapter in registry.select(SearchPlan())
    )
    department = registry.get("department_education_gov_in")

    assert "department_education_gov_in" in selected_ids
    assert isinstance(department, DepartmentWebsiteAdapter)
    assert department.domains == ("education.gov.in",)
    assert department.seed_urls == ("https://education.gov.in/",)


def test_department_adapter_rejects_non_operator_domain_even_if_globally_allowed():
    config = Section4Config(
        allowed_domains=frozenset({"education.gov.in", "evil.gov.in"}),
        department_domains=frozenset({"education.gov.in"}),
    )

    with pytest.raises(ValueError):
        DepartmentWebsiteAdapter(config, "evil.gov.in", http_client=_StubHttpClient())


def test_health_check_does_not_make_an_http_request():
    stub = _StubHttpClient(error=AssertionError("HTTP must not be called"))
    adapter = CentralInformationCommissionAdapter(
        Section4Config(allowed_domains=frozenset({"cic.gov.in"})),
        http_client=stub,
    )

    health = adapter.health_check()

    assert health.adapter_id == "cic_disclosures"
    assert health.status == "ready"
    assert stub.calls == []
