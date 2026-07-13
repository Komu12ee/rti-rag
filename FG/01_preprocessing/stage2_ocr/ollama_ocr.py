"""Ollama vision OCR adapter for prepared PDF page images."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .models import DocumentElement, ElementType, PageOCRResult


DEFAULT_OLLAMA_OCR_MODEL = "qwen3-vl:4b-instruct"
DEFAULT_OLLAMA_OCR_TIMEOUT_SECONDS = 180
DEFAULT_OLLAMA_OCR_MAX_TOKENS = 4096

OCR_PROMPT = """Transcribe this RTI document page into Markdown.

Rules:
- Copy every readable word exactly as shown, including Hindi and English.
- Preserve headings, paragraphs, numbered lists, and tables.
- Do not translate, summarize, explain, or answer the document.
- Use [illegible] only where text genuinely cannot be read.
- Return only the page transcription in Markdown.
"""

_OUTER_FENCE_RE = re.compile(
    r"\A\s*```(?:markdown|md|text)?\s*\n?(.*?)\n?```\s*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)


class OllamaOCRError(RuntimeError):
    """Raised when the local Ollama vision OCR request cannot complete."""


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise OllamaOCRError(f"{name} must be a positive integer.") from error
    if value <= 0:
        raise OllamaOCRError(f"{name} must be a positive integer.")
    return value


def _ollama_chat_url() -> str:
    """Build the local Ollama chat endpoint from the shared env settings."""
    configured_base_url = os.getenv("OLLAMA_BASE_URL", "").strip()
    if configured_base_url:
        base_url = configured_base_url
    else:
        host = os.getenv("OLLAMA_HOST", "localhost").strip() or "localhost"
        port = os.getenv("OLLAMA_PORT", "11434").strip() or "11434"
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"

        try:
            parsed_host = urlsplit(host)
            has_port = parsed_host.port is not None
        except ValueError as error:
            raise OllamaOCRError("OLLAMA_HOST contains an invalid port.") from error

        base_url = host if has_port else f"{host.rstrip('/')}:{port}"

    if not base_url.startswith(("http://", "https://")):
        base_url = f"http://{base_url}"
    return f"{base_url.rstrip('/')}/api/chat"


def _clean_markdown_response(text: str) -> str:
    """Remove one model-added outer Markdown fence without altering content."""
    cleaned = text.strip()
    match = _OUTER_FENCE_RE.fullmatch(cleaned)
    return match.group(1).strip() if match else cleaned


def run_ollama_page_ocr(
    image_path: str | Path,
    page_num: int,
) -> PageOCRResult:
    """Transcribe one prepared page image with a local Ollama vision model."""
    image_path = Path(image_path)
    if not image_path.is_file():
        raise OllamaOCRError(f"OCR page image was not found: {image_path}")

    model = (
        os.getenv("OLLAMA_OCR_MODEL", "").strip()
        or DEFAULT_OLLAMA_OCR_MODEL
    )
    if os.getenv("OLLAMA_OCR_TIMEOUT_SECONDS", "").strip():
        timeout_seconds = _positive_int_env(
            "OLLAMA_OCR_TIMEOUT_SECONDS",
            DEFAULT_OLLAMA_OCR_TIMEOUT_SECONDS,
        )
    else:
        timeout_seconds = _positive_int_env(
            "OLLAMA_TIMEOUT_SECONDS",
            DEFAULT_OLLAMA_OCR_TIMEOUT_SECONDS,
        )
    max_tokens = _positive_int_env(
        "OLLAMA_OCR_MAX_TOKENS",
        DEFAULT_OLLAMA_OCR_MAX_TOKENS,
    )

    try:
        encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError as error:
        raise OllamaOCRError(f"Could not read OCR page image: {image_path}") from error

    url = _ollama_chat_url()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": OCR_PROMPT,
                "images": [encoded_image],
            }
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": max_tokens,
        },
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout_seconds)
    except requests.RequestException as error:
        raise OllamaOCRError(
            f"Local Ollama OCR request failed at {url}: {error}. "
            "Ensure Ollama is running."
        ) from error

    if response.status_code != 200:
        detail = str(getattr(response, "text", ""))[:500]
        raise OllamaOCRError(
            f"Ollama OCR model {model!r} returned HTTP {response.status_code}: "
            f"{detail}. Ensure it is a vision model and run `ollama pull {model}`."
        )

    try:
        response_data = response.json()
    except ValueError as error:
        raise OllamaOCRError("Ollama OCR returned invalid JSON.") from error
    if not isinstance(response_data, dict):
        raise OllamaOCRError("Ollama OCR returned an unexpected JSON response.")

    message = response_data.get("message")
    raw_text = ""
    if isinstance(message, dict):
        raw_text = str(message.get("content") or "")
    raw_text = _clean_markdown_response(raw_text)
    if not raw_text:
        raise OllamaOCRError("Ollama OCR returned an empty transcription.")

    return PageOCRResult(
        page_num=page_num,
        elements=[
            DocumentElement(
                element_type=ElementType.PARAGRAPH,
                text=raw_text,
                page_num=page_num,
            )
        ],
        raw_text=raw_text,
        confidence=None,
    )
