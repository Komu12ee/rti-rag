import base64
import sys
from pathlib import Path
from unittest.mock import Mock, patch, sentinel

import pytest


ROOT = Path(__file__).resolve().parents[1]
PREPROCESSING_DIR = ROOT / "FG" / "01_preprocessing"
sys.path.insert(0, str(PREPROCESSING_DIR))

from stage2_ocr import ollama_ocr  # noqa: E402
from stage2_ocr import pipeline as pipeline_module  # noqa: E402
from page_classifier import classify_page  # noqa: E402


@pytest.mark.parametrize("value", [None, ""])
def test_normalize_ocr_model_defaults_to_ollama(value):
    assert pipeline_module.normalize_ocr_model(value) == "ollama"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ollama", "ollama"),
        (" OLLAMA ", "ollama"),
        ("sarvam", "sarvam"),
        (" SARVAM ", "sarvam"),
    ],
)
def test_normalize_ocr_model_accepts_supported_values(value, expected):
    assert pipeline_module.normalize_ocr_model(value) == expected


@pytest.mark.parametrize("value", ["easyocr", "tesseract", "   "])
def test_normalize_ocr_model_rejects_invalid_values(value):
    with pytest.raises(
        ValueError,
        match="Invalid OCR_MODEL.*'ollama'.*'sarvam'",
    ):
        pipeline_module.normalize_ocr_model(value)


def test_process_single_image_routes_exclusively_to_ollama(tmp_path):
    image_path = tmp_path / "page.png"
    ocr_pipeline = pipeline_module.OCRPipeline(
        output_dir=tmp_path,
        ocr_model="ollama",
    )

    with (
        patch.object(
            pipeline_module,
            "run_ollama_page_ocr",
            return_value=sentinel.ollama_result,
        ) as run_ollama,
        patch.object(
            pipeline_module,
            "_run_sarvam_single_page",
            return_value=sentinel.sarvam_result,
        ) as run_sarvam,
    ):
        result = ocr_pipeline.process_single_image(image_path, page_num=2)

    assert result is sentinel.ollama_result
    run_ollama.assert_called_once_with(image_path, 2)
    run_sarvam.assert_not_called()


def test_process_single_image_routes_exclusively_to_sarvam(tmp_path):
    image_path = tmp_path / "page.png"
    ocr_pipeline = pipeline_module.OCRPipeline(
        output_dir=tmp_path,
        ocr_model="sarvam",
    )

    with (
        patch.object(
            pipeline_module,
            "run_ollama_page_ocr",
            return_value=sentinel.ollama_result,
        ) as run_ollama,
        patch.object(
            pipeline_module,
            "_run_sarvam_single_page",
            return_value=sentinel.sarvam_result,
        ) as run_sarvam,
    ):
        result = ocr_pipeline.process_single_image(image_path, page_num=2)

    assert result is sentinel.sarvam_result
    run_sarvam.assert_called_once_with(
        image_path=image_path,
        page_num=2,
        output_dir=tmp_path,
    )
    run_ollama.assert_not_called()


@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_sarvam_ocr_rejects_missing_or_blank_api_key(
    tmp_path,
    monkeypatch,
    api_key,
):
    if api_key is None:
        monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("SARVAM_API_KEY", api_key)

    with pytest.raises(
        pipeline_module.OCRProviderError,
        match="SARVAM_API_KEY is missing or blank",
    ):
        pipeline_module._run_sarvam_fallback(
            output_dir=tmp_path,
            page_image_paths={},
            page_confidences={},
            threshold=1.0,
            strict=True,
        )


def test_sarvam_ocr_missing_sdk_reports_exact_python_install_command(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(
        pipeline_module.importlib,
        "import_module",
        Mock(side_effect=ImportError("No module named 'sarvamai'")),
    )

    with pytest.raises(pipeline_module.OCRProviderError) as exc_info:
        pipeline_module._run_sarvam_fallback(
            output_dir=tmp_path,
            page_image_paths={},
            page_confidences={},
            threshold=1.0,
            strict=True,
        )

    message = str(exc_info.value)
    assert "OCR_MODEL=sarvam requires the Sarvam Document Intelligence SDK" in message
    assert sys.executable in message
    assert (
        f'"{sys.executable}" -m pip install '
        f'"{pipeline_module.SARVAM_SDK_REQUIREMENT}"'
    ) in message


def test_page_without_images_bypasses_ocr():
    page = classify_page(
        page_num=1,
        direct_text="Short selectable RTI text",
        image_count=0,
    )

    assert page["needs_ocr"] is False
    assert page["extraction_method"] == "direct_text"
    assert page["final_text"] == "Short selectable RTI text"


def test_image_bearing_page_is_routed_to_ocr():
    page = classify_page(
        page_num=1,
        direct_text="",
        image_count=1,
    )

    assert page["needs_ocr"] is True
    assert page["extraction_method"] == "ocr"


def test_run_ollama_page_ocr_builds_vision_chat_request_and_cleans_fence(
    tmp_path,
    monkeypatch,
):
    image_bytes = b"unit-test-page-image"
    image_path = tmp_path / "page.png"
    image_path.write_bytes(image_bytes)

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test:11434/")
    monkeypatch.setenv("OLLAMA_OCR_MODEL", "unit-vision:latest")
    monkeypatch.setenv("OLLAMA_OCR_TIMEOUT_SECONDS", "37")
    monkeypatch.setenv("OLLAMA_OCR_MAX_TOKENS", "2048")

    response = Mock(status_code=200)
    response.json.return_value = {
        "message": {
            "content": "```markdown\n# RTI application\nRequested information\n```"
        }
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(ollama_ocr.requests, "post", post)

    result = ollama_ocr.run_ollama_page_ocr(image_path, page_num=4)

    post.assert_called_once()
    url = post.call_args.args[0]
    request_kwargs = post.call_args.kwargs
    payload = request_kwargs["json"]

    assert url == "http://ollama.test:11434/api/chat"
    assert request_kwargs["timeout"] == 37
    assert payload["model"] == "unit-vision:latest"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {
        "temperature": 0,
        "num_predict": 2048,
    }
    assert payload["messages"] == [
        {
            "role": "user",
            "content": ollama_ocr.OCR_PROMPT,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
        }
    ]
    assert result.page_num == 4
    assert result.raw_text == "# RTI application\nRequested information"
    assert result.elements[0].text == result.raw_text


def test_run_ollama_page_ocr_reports_request_failure(tmp_path, monkeypatch):
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"unit-test-page-image")

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test:11434")
    monkeypatch.setenv("OLLAMA_OCR_TIMEOUT_SECONDS", "5")
    monkeypatch.setattr(
        ollama_ocr.requests,
        "post",
        Mock(side_effect=ollama_ocr.requests.ConnectionError("connection refused")),
    )

    with pytest.raises(ollama_ocr.OllamaOCRError) as exc_info:
        ollama_ocr.run_ollama_page_ocr(image_path, page_num=0)

    message = str(exc_info.value)
    assert "Local Ollama OCR request failed" in message
    assert "http://ollama.test:11434/api/chat" in message
    assert "connection refused" in message
    assert "Ensure Ollama is running" in message
