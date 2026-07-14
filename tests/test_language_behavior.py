import io
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "FG" / "05_webui"
sys.path.insert(0, str(WEBUI_DIR))

import app as web_app  # noqa: E402
from services import pio_precedent_service  # noqa: E402
from services.unified_answer_service import UnifiedAnswer  # noqa: E402


def _fake_pio_result(*, extraction_language: str = "English") -> dict:
    return {
        "validation": {"is_valid_rti": True},
        "rti_extraction": {
            "subject": "Test RTI",
            "language": extraction_language,
            "information_points": [],
        },
        "legal_analysis": {"recommended_action": "reply", "point_analysis": []},
        "pio_advisory_report": "Test PIO advisory",
    }


def _fake_precedent_result(answer_language: str) -> dict:
    return {
        "answer": f"precedent answer ({answer_language})",
        "results": [],
        "result_count": 0,
        "available_collections": ["cic"],
        "warnings": [],
    }


def _sse_events(response) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"

    for line in response.get_data(as_text=True).splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((event_name, json.loads(line.removeprefix("data: "))))

    return events


@pytest.fixture(autouse=True)
def clear_pio_advisory_cache():
    with web_app.pio_advisory_cache_lock:
        web_app.pio_advisory_cache.clear()
    yield
    with web_app.pio_advisory_cache_lock:
        web_app.pio_advisory_cache.clear()


def test_main_query_passes_normalised_answer_language_to_answer_service(monkeypatch):
    route = SimpleNamespace(value="UNCLEAR")
    retrieval = SimpleNamespace(
        combined_evidence=[],
        errors=[],
        resolution=SimpleNamespace(
            final=SimpleNamespace(route=route),
            router_a=SimpleNamespace(route=route),
            used_llm_fallback=False,
        ),
    )
    captured: dict = {}

    monkeypatch.setattr(web_app, "retrieve_from_all_sources", lambda **_kwargs: retrieval)

    def fake_generate_unified_answer(**kwargs):
        captured.update(kwargs)
        return UnifiedAnswer(
            answer="हिंदी उत्तर",
            used_llm=False,
            needs_clarification=False,
            sources=[],
        )

    monkeypatch.setattr(web_app, "generate_unified_answer", fake_generate_unified_answer)

    response = web_app.app.test_client().post(
        "/api/query",
        json={"query": "RTI समय सीमा क्या है?", "answer_language": "Hindi"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert captured["answer_language"] == "hi"
    assert payload["answer_language"] == "hi"


def test_main_pio_query_caches_selected_answer_language(monkeypatch):
    captured: dict = {}

    def fake_analyze_pio_application(**kwargs):
        captured.update(kwargs)
        return _fake_pio_result(extraction_language="English")

    monkeypatch.setattr(web_app, "_is_pio_advisory_request", lambda _query: True)
    monkeypatch.setattr(web_app, "_extract_rti_application_text", lambda query: query)
    monkeypatch.setattr(web_app, "analyze_pio_application", fake_analyze_pio_application)
    monkeypatch.setattr(web_app, "_precedent_collection_status", lambda: (["cic"], []))

    response = web_app.app.test_client().post(
        "/api/query",
        json={
            "query": "Prepare a PIO response for this complete RTI application.",
            "pio_mode": True,
            "answer_language": "hi",
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert captured["answer_language"] == "hi"
    assert payload["answer_language"] == "hi"
    assert web_app._get_pio_advisory(payload["advisory_id"])["answer_language"] == "hi"


def test_pdf_upload_passes_and_caches_selected_answer_language(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_MODEL", "ollama")
    monkeypatch.setattr(web_app, "PIO_PDF_UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(web_app, "_precedent_collection_status", lambda: (["cic"], []))
    captured: dict = {}

    def fake_analyze_pio_application(**kwargs):
        captured.update(kwargs)
        return _fake_pio_result(extraction_language="English")

    def fake_subprocess_run(command, **_kwargs):
        pdf_path = Path(command[2])
        output_root = Path(command[command.index("--output") + 1])
        structured_md = output_root / pdf_path.stem / "structured.md"
        structured_md.parent.mkdir(parents=True, exist_ok=True)
        structured_md.write_text("Extracted RTI application", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "completed", "")

    monkeypatch.setattr(web_app, "analyze_pio_application", fake_analyze_pio_application)
    monkeypatch.setattr(web_app.subprocess, "run", fake_subprocess_run)

    response = web_app.app.test_client().post(
        "/api/pio/upload-pdf",
        data={
            "pdf": (io.BytesIO(b"%PDF-1.4\nunit-test"), "english-rti.pdf"),
            "answer_language": "hi",
        },
        content_type="multipart/form-data",
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert captured["answer_language"] == "hi"
    assert payload["answer_language"] == "hi"
    assert web_app._get_pio_advisory(payload["advisory_id"])["answer_language"] == "hi"


def test_precedent_endpoint_defaults_to_cached_language_and_avoids_cross_language_cache(
    monkeypatch,
):
    advisory_id = web_app._store_pio_advisory(_fake_pio_result(), "en")
    calls: list[str] = []
    monkeypatch.setattr(web_app, "_load_rag_module", lambda: object())

    def fake_retrieve(**kwargs):
        calls.append(kwargs["answer_language"])
        return _fake_precedent_result(kwargs["answer_language"])

    monkeypatch.setattr(web_app, "retrieve_pio_precedent_references", fake_retrieve)
    client = web_app.app.test_client()

    hindi = client.post(
        "/api/pio/precedents",
        json={"advisory_id": advisory_id, "answer_language": "hi"},
    ).get_json()
    hindi_cached = client.post(
        "/api/pio/precedents",
        json={"advisory_id": advisory_id, "answer_language": "hi"},
    ).get_json()
    english = client.post(
        "/api/pio/precedents",
        json={"advisory_id": advisory_id},
    ).get_json()

    assert calls == ["hi", "en"]
    assert hindi["answer_language"] == "hi"
    assert hindi_cached["answer_language"] == "hi"
    assert hindi_cached["cached"] is True
    assert english["answer_language"] == "en"
    assert english["answer"] == "precedent answer (en)"
    assert english["cached"] is False


def test_streamed_precedent_routes_preserve_cached_answer_language(monkeypatch):
    advisory_id = web_app._store_pio_advisory(_fake_pio_result(), "hi")
    captured: dict[str, str] = {}
    monkeypatch.setattr(web_app, "_load_rag_module", lambda: object())

    def fake_reference_stream(**kwargs):
        captured["references"] = kwargs["answer_language"]
        result = _fake_precedent_result(kwargs["answer_language"])
        yield "token", result["answer"]
        yield "result", result

    def fake_advisory_stream(**kwargs):
        captured["advisory"] = kwargs["answer_language"]
        yield "संशोधित परामर्श"

    monkeypatch.setattr(
        web_app,
        "retrieve_pio_precedent_references_stream",
        fake_reference_stream,
    )
    monkeypatch.setattr(
        web_app,
        "stream_precedent_informed_advisory",
        fake_advisory_stream,
    )
    client = web_app.app.test_client()

    reference_response = client.post(
        "/api/pio/precedents/stream",
        json={"advisory_id": advisory_id},
        buffered=True,
    )
    reference_done = dict(_sse_events(reference_response))["done"]

    advisory_response = client.post(
        "/api/pio/precedent-advisory/stream",
        json={"advisory_id": advisory_id},
        buffered=True,
    )
    advisory_done = dict(_sse_events(advisory_response))["done"]

    assert captured == {"references": "hi", "advisory": "hi"}
    assert reference_done["answer_language"] == "hi"
    assert advisory_done["answer_language"] == "hi"


def test_explicit_english_precedent_prompt_overrides_hindi_document_language():
    prompt = pio_precedent_service._build_precedent_prompt(
        rti_extraction={"language": "Hindi", "information_points": []},
        legal_analysis={"point_analysis": []},
        results=[],
        answer_language="en",
    )

    assert "REQUIRED ANSWER LANGUAGE:\nEnglish" in prompt
    assert "REQUIRED ANSWER LANGUAGE:\nHindi" not in prompt


def test_english_precedent_advisory_prompt_has_no_conflicting_hindi_instruction():
    prompt = pio_precedent_service._build_precedent_informed_advisory_prompt(
        rti_extraction={"language": "Hindi", "information_points": []},
        legal_analysis={"point_analysis": []},
        original_advisory="Original advisory",
        precedent_result={"answer": "Reference note", "results": []},
        answer_language="en",
    )

    assert "Write the entire visible advisory in professional English." in prompt
    assert "natural professional Hindi" not in prompt
    assert "in Hindi --" not in prompt
    assert re.search(r"[\u0900-\u097F]", prompt) is None
