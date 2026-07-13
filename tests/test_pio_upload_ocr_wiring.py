import io
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "FG" / "05_webui"
sys.path.insert(0, str(WEBUI_DIR))

import app as web_app  # noqa: E402


def _fake_pio_result() -> dict:
    return {
        "validation": {"is_valid_rti": True},
        "rti_extraction": {"subject": "Test RTI"},
        "legal_analysis": {"recommended_action": "reply"},
        "pio_advisory_report": "Test PIO advisory",
    }


def test_upload_passes_sarvam_to_smart_extraction_without_provider_calls(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OCR_MODEL", "sarvam")
    monkeypatch.setattr(web_app, "PIO_PDF_UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(
        web_app,
        "analyze_pio_application",
        lambda **_kwargs: _fake_pio_result(),
    )
    monkeypatch.setattr(web_app, "_precedent_collection_status", lambda: ([], []))

    captured_command = []

    def fake_subprocess_run(command, **_kwargs):
        captured_command.extend(command)
        pdf_path = Path(command[2])
        output_root = Path(command[command.index("--output") + 1])
        structured_md = output_root / pdf_path.stem / "structured.md"
        structured_md.parent.mkdir(parents=True, exist_ok=True)
        structured_md.write_text("Extracted RTI application", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="Smart extraction completed",
            stderr="",
        )

    monkeypatch.setattr(web_app.subprocess, "run", fake_subprocess_run)

    response = web_app.app.test_client().post(
        "/api/pio/upload-pdf",
        data={
            "pdf": (io.BytesIO(b"%PDF-1.4\nunit-test"), "scanned-rti.pdf"),
            "answer_language": "en",
        },
        content_type="multipart/form-data",
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["source_pdf"] == "scanned-rti.pdf"
    assert payload["ocr_model"] == "sarvam"
    assert payload["route"] == "PIO_ADVISORY"
    assert "structured_md_path" not in payload
    assert "preprocess_stdout" not in payload
    assert "preprocess_stderr" not in payload
    assert captured_command[0] == sys.executable
    assert captured_command[1] == str(web_app.SMART_EXTRACT_SCRIPT)
    assert captured_command[captured_command.index("--ocr-model") + 1] == "sarvam"


def test_health_reports_sarvam_configuration_problem(monkeypatch):
    monkeypatch.setenv("OCR_MODEL", "sarvam")
    monkeypatch.setenv("SARVAM_API_KEY", "   ")

    response = web_app.app.test_client().get("/api/health")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["ocr_model"] == "sarvam"
    assert payload["ocr_ready"] is False
    assert "SARVAM_API_KEY is missing or blank" in payload["ocr_error"]


def test_health_reports_local_ollama_outage(monkeypatch):
    monkeypatch.setenv("OCR_MODEL", "ollama")
    monkeypatch.setattr(
        web_app.requests,
        "get",
        Mock(side_effect=web_app.requests.ConnectionError("connection refused")),
    )

    response = web_app.app.test_client().get("/api/health")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["ocr_model"] == "ollama"
    assert payload["ocr_ready"] is False
    assert "local Ollama service is unavailable" in payload["ocr_error"]


def test_upload_returns_concise_503_when_sarvam_sdk_is_unavailable(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OCR_MODEL", "sarvam")
    monkeypatch.setattr(web_app, "PIO_PDF_UPLOAD_ROOT", tmp_path)
    analyze = Mock()
    monkeypatch.setattr(web_app, "analyze_pio_application", analyze)

    child_log = (
        "13:42:09 | INFO | Input: C:\\uploads\\scanned-rti.pdf\n"
        "13:42:09 | ERROR | [ERROR] Smart extraction failed: scanned-rti.pdf: "
        "sarvam OCR failed on page 2: OCR_MODEL=sarvam requires the Sarvam "
        "Document Intelligence SDK in the same Python environment used for OCR.\n"
        "13:42:09 | ERROR | Sarvam extraction failed for 1 PDF(s)."
    )
    monkeypatch.setattr(
        web_app.subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr=child_log,
            )
        ),
    )

    response = web_app.app.test_client().post(
        "/api/pio/upload-pdf",
        data={"pdf": (io.BytesIO(b"%PDF-1.4\nunit-test"), "scanned-rti.pdf")},
        content_type="multipart/form-data",
    )

    payload = response.get_json()
    assert response.status_code == 503
    assert payload["ocr_model"] == "sarvam"
    assert payload["error"].startswith("Sarvam OCR cannot start on page 2:")
    assert "Flask Python environment" in payload["error"]
    assert "13:42:09" not in payload["error"]
    assert "Input:" not in payload["error"]
    assert sys.executable not in payload["error"]
    assert "preprocess_stderr" not in payload
    analyze.assert_not_called()


def test_preprocessing_error_summary_removes_raw_log_noise():
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr=(
            "13:42:09 | ERROR | [ERROR] Smart extraction failed: example.pdf: "
            "sarvam OCR failed on page 2: sarvam OCR failed on page 2: "
            "OCR_MODEL=sarvam requires the Sarvam Document Intelligence SDK\n"
            "13:42:09 | ERROR | Sarvam extraction failed for 1 PDF(s)."
        ),
    )

    assert web_app._preprocessing_error_summary(completed) == (
        "sarvam OCR failed on page 2: "
        "OCR_MODEL=sarvam requires the Sarvam Document Intelligence SDK"
    )
