import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "FG" / "05_webui" / "nodejs" / "public"
APP_JS = PUBLIC_DIR / "app.js"
STYLE_CSS = PUBLIC_DIR / "style.css"


def _source_between(source: str, start: str, end: str) -> str:
    start_at = source.index(start)
    end_at = source.index(end, start_at)
    return source[start_at:end_at]


def _translation_keys(catalog_section: str) -> set[str]:
    return set(re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*:\s*['\"]", catalog_section))


REQUIRED_TRANSLATION_KEYS = {
    "publicDomainVerification",
    "verificationStatus",
    "verificationFound",
    "verificationPartiallyFound",
    "verificationNotFound",
    "verificationSourceUnavailable",
    "verifiedOfficialDocuments",
    "searchedOfficialDomains",
    "lastChecked",
    "availableFields",
    "missingFields",
    "officialSource",
    "publicationDate",
    "pageNumber",
    "sectionHeading",
    "matchedEvidence",
    "openOfficialSource",
    "retryUnavailableSources",
    "retryingVerification",
    "verificationRetryFailed",
    "searchOfficialWeb",
    "searchingOfficialWeb",
    "officialWebSearchFailed",
}


def test_verification_card_labels_exist_in_both_language_catalogs():
    javascript = APP_JS.read_text(encoding="utf-8")
    catalog = _source_between(javascript, "const TRANSLATIONS = {", "const CG_GOV_LOGO")
    english = _source_between(catalog, "  en: {", "  hi: {")
    hindi = catalog[catalog.index("  hi: {") :]

    assert REQUIRED_TRANSLATION_KEYS <= _translation_keys(english)
    assert REQUIRED_TRANSLATION_KEYS <= _translation_keys(hindi)
    assert re.search(r"[\u0900-\u097F]", hindi)


def test_primary_response_retains_verification_and_renders_before_pio_details():
    javascript = APP_JS.read_text(encoding="utf-8")
    response_builder = _source_between(
        javascript,
        "function buildAssistantResponseMessage",
        "async function sendQuery",
    )
    message_renderer = _source_between(
        javascript,
        "function createMessageElement",
        "function formatMessageText",
    )

    assert "webVerification: data.web_verification || null" in response_builder
    card_at = message_renderer.index("createWebVerificationCard(message)")
    pio_details_at = message_renderer.index("createPioAnalysisDetails(message.pioDetails)")
    assert card_at < pio_details_at


def test_only_four_statuses_are_visible_and_search_not_triggered_has_no_card():
    javascript = APP_JS.read_text(encoding="utf-8")
    statuses = _source_between(
        javascript,
        "const WEB_VERIFICATION_VISIBLE_STATUSES",
        "const WEB_VERIFICATION_STATUS_KEYS",
    )
    normalizer = _source_between(
        javascript,
        "function normaliseWebVerificationStatus",
        "function isOfficialVerificationHostname",
    )
    card_renderer = _source_between(
        javascript,
        "function createWebVerificationCard",
        "async function handleWebVerificationRetry",
    )

    assert set(re.findall(r"'([A-Z_]+)'", statuses)) == {
        "FOUND",
        "PARTIALLY_FOUND",
        "NOT_FOUND",
        "SOURCE_UNAVAILABLE",
    }
    assert "SEARCH_NOT_TRIGGERED" in normalizer
    assert "if (!WEB_VERIFICATION_VISIBLE_STATUSES.has(status)) return null" in card_renderer


def test_source_links_require_official_https_and_use_safe_external_link_attributes():
    javascript = APP_JS.read_text(encoding="utf-8")
    url_validator = _source_between(
        javascript,
        "function officialVerificationUrl",
        "function verificationValues",
    )
    hostname_validator = _source_between(
        javascript,
        "function isOfficialVerificationHostname",
        "function officialVerificationUrl",
    )
    source_renderer = _source_between(
        javascript,
        "function createWebVerificationSource",
        "function createWebVerificationCard",
    )

    assert "url.protocol !== 'https:'" in url_validator
    assert "url.username || url.password" in url_validator
    assert "url.port && url.port !== '443'" in url_validator
    assert ".endsWith('.gov.in')" in hostname_validator
    assert ".endsWith('.nic.in')" in hostname_validator
    assert "link.target = '_blank'" in source_renderer
    assert "link.rel = 'noopener noreferrer'" in source_renderer
    assert "domain: url.hostname" in source_renderer
    assert "openDrawer" not in source_renderer


def test_card_renders_fields_domains_timestamp_and_bounded_evidence():
    javascript = APP_JS.read_text(encoding="utf-8")
    card_renderer = _source_between(
        javascript,
        "function createWebVerificationCard",
        "async function handleWebVerificationRetry",
    )
    source_renderer = _source_between(
        javascript,
        "function createWebVerificationSource",
        "function createWebVerificationCard",
    )
    timestamp_formatter = _source_between(
        javascript,
        "function formatVerificationTimestamp",
        "function formatVerificationDate",
    )
    source_selector = _source_between(
        javascript,
        "function verifiedWebSources",
        "function searchedOfficialDomains",
    )

    assert "verification?.found_items" in source_selector
    assert "source.verified !== true" in source_selector
    assert "searchedOfficialDomains(verification, sources)" in card_renderer
    assert "verification.available_fields || verification.supported_fields" in card_renderer
    assert "verification.missing_fields || verification.unsupported_fields" in card_renderer
    assert "formatVerificationTimestamp(checkedAt)" in card_renderer
    assert "timeZone: 'Asia/Kolkata'" in timestamp_formatter
    assert "source.matched_text || source.matched_passage" in source_renderer
    assert ",\n    480\n  )" in source_renderer


def test_retry_is_source_unavailable_only_uses_encoded_path_and_preserves_result_on_failure():
    javascript = APP_JS.read_text(encoding="utf-8")
    api_body = _source_between(javascript, "const api = {", "function nowIso()")
    card_renderer = _source_between(
        javascript,
        "function createWebVerificationCard",
        "async function handleWebVerificationRetry",
    )
    retry_handler = _source_between(
        javascript,
        "async function handleWebVerificationRetry",
        "function loadConversations",
    )
    catch_body = _source_between(retry_handler, "  } catch (_) {", "  } finally {")

    assert "encodeURIComponent(verificationId)" in api_body
    assert "/api/web-verification/${encodeURIComponent(verificationId)}/retry" in api_body
    assert "if (status === 'SOURCE_UNAVAILABLE' && verificationId)" in card_renderer
    assert "!== 'SOURCE_UNAVAILABLE'" in retry_handler
    assert "message.webVerification = refreshed" in retry_handler
    assert "message.webVerification" not in catch_body
    assert "toast(t('verificationRetryFailed'), 'error')" in catch_body


def test_verification_css_has_textual_status_hooks_and_mobile_layout():
    css = STYLE_CSS.read_text(encoding="utf-8")

    for status in ("FOUND", "PARTIALLY_FOUND", "NOT_FOUND", "SOURCE_UNAVAILABLE"):
        assert f'.web-verification-card[data-status="{status}"]' in css

    assert ".web-verification-status" in css
    assert ".web-verification-source-link:focus-visible" in css
    assert ".web-verification-retry:focus-visible" in css
    assert "@media (max-width: 520px)" in css


def test_web_search_is_an_explicit_advisory_action():
    javascript = APP_JS.read_text(encoding="utf-8")
    api_body = _source_between(javascript, "const api = {", "function nowIso()")
    controls = _source_between(
        javascript,
        "function createPrecedentActionControls",
        "function normaliseConfirmation",
    )
    response_builder = _source_between(
        javascript,
        "function buildAssistantResponseMessage",
        "async function sendQuery",
    )

    assert "advisory_id: advisoryId" in api_body
    assert "handleWebSearch(message.id)" in controls
    assert "api.webVerification(advisoryMessage.advisoryId)" in controls
    assert "webSearchAvailable: Boolean(data.advisory_id)" in response_builder
