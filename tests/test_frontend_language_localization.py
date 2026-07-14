import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "FG" / "05_webui" / "nodejs" / "public"
APP_JS = PUBLIC_DIR / "app.js"
INDEX_HTML = PUBLIC_DIR / "index.html"


def _source_between(source: str, start: str, end: str) -> str:
    start_at = source.index(start)
    end_at = source.index(end, start_at)
    return source[start_at:end_at]


def _translation_keys(catalog_section: str) -> set[str]:
    return set(re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*:\s*['\"]", catalog_section))


def test_every_localized_html_attribute_has_english_and_hindi_catalog_entries():
    html = INDEX_HTML.read_text(encoding="utf-8")
    javascript = APP_JS.read_text(encoding="utf-8")
    catalog = _source_between(javascript, "const TRANSLATIONS = {", "const CG_GOV_LOGO")
    english = _source_between(catalog, "  en: {", "  hi: {")
    hindi = catalog[catalog.index("  hi: {") :]

    html_keys = set(
        re.findall(
            r'data-i18n(?:-aria-label|-title|-placeholder|-alt)?="([A-Za-z0-9_]+)"',
            html,
        )
    )
    english_keys = _translation_keys(english)
    hindi_keys = _translation_keys(hindi)

    assert len(html_keys) >= 30
    assert html_keys <= english_keys
    assert html_keys <= hindi_keys
    assert english_keys == hindi_keys


def test_locale_change_applies_static_translation_and_rerenders_dynamic_ui_only():
    javascript = APP_JS.read_text(encoding="utf-8")
    apply_body = _source_between(
        javascript,
        "function applyTranslations()",
        "const KNOWN_UI_MESSAGE_KEYS",
    )
    update_body = _source_between(
        javascript,
        "function updateLanguageModeUi()",
        "function setLanguageMode(mode)",
    )
    setter_body = _source_between(
        javascript,
        "function setLanguageMode(mode)",
        "function autoResize()",
    )

    assert "document.querySelectorAll('[data-i18n]')" in apply_body
    assert "data-i18n-placeholder" in apply_body
    assert "applyTranslations();" in update_body + setter_body
    assert "renderAll();" in update_body + setter_body

    # The catalog translates UI chrome; stored user/assistant messages remain untouched.
    assert "state.conversations" not in apply_body
    assert "state.conversations" not in setter_body


def test_precedent_requests_and_callers_preserve_current_answer_language():
    javascript = APP_JS.read_text(encoding="utf-8")
    api_body = _source_between(javascript, "const api = {", "function nowIso()")

    precedent_request = _source_between(
        api_body,
        "pioPrecedents:",
        "pioPrecedentsStream:",
    )
    precedent_stream_request = _source_between(
        api_body,
        "pioPrecedentsStream:",
        "pioPrecedentAdvisoryStream:",
    )
    advisory_stream_request = _source_between(
        api_body,
        "pioPrecedentAdvisoryStream:",
        "async uploadPioPdf",
    )

    for request_body in (
        precedent_request,
        precedent_stream_request,
        advisory_stream_request,
    ):
        assert "answerLanguage" in request_body
        assert "answer_language: normaliseLanguageMode(answerLanguage)" in request_body

    assert re.search(
        r"api\.pioPrecedentsStream\(\s*advisoryMessage\.advisoryId,\s*5,\s*"
        r"state\.languageMode,",
        javascript,
    )
    assert re.search(
        r"api\.pioPrecedentAdvisoryStream\(\s*advisoryMessage\.advisoryId,\s*"
        r"state\.languageMode,",
        javascript,
    )

