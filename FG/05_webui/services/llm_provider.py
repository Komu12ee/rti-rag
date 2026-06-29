from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv


WEBUI_DIR = Path(__file__).resolve().parents[1]
load_dotenv(WEBUI_DIR / ".env", override=False)


class LLMProviderError(RuntimeError):
    """Raised when the selected LLM provider cannot generate a response."""


def get_llm_mode() -> str:
    mode = os.getenv("LLM_MODE", "ollama").strip().casefold()

    if mode not in {"ollama", "sarvam"}:
        raise LLMProviderError(
            "Invalid LLM_MODE. Use either 'ollama' or 'sarvam'."
        )

    return mode


def current_llm_label() -> str:
    mode = get_llm_mode()

    if mode == "sarvam":
        model = os.getenv("SARVAM_MODEL", "sarvam-105b").strip()
        return f"Sarvam ({model})"

    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip()
    return f"Ollama ({model})"


def _generate_with_ollama(
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_seconds: int,
    json_mode: bool,
) -> str:
    host = os.getenv("OLLAMA_HOST", "localhost").strip()
    port = os.getenv("OLLAMA_PORT", "11434").strip()
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip()

    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    url = f"{host.rstrip('/')}:{port}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "repeat_penalty": 1.1,
        },
    }

    if json_mode:
        payload["format"] = "json"

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=timeout_seconds,
        )
    except requests.RequestException as error:
        raise LLMProviderError(
            f"Ollama request failed: {error}"
        ) from error

    if response.status_code != 200:
        raise LLMProviderError(
            f"Ollama returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        data = response.json()
    except ValueError as error:
        raise LLMProviderError(
            "Ollama returned invalid JSON."
        ) from error

    answer = str(data.get("response", "")).strip()

    if not answer:
        raise LLMProviderError("Ollama returned an empty response.")

    return answer


def _generate_with_sarvam(
    prompt: str,
    timeout_seconds: int,
) -> str:
    api_key = os.getenv("SARVAM_API_KEY", "").strip()
    model = os.getenv("SARVAM_MODEL", "sarvam-105b").strip()
    url = os.getenv(
        "SARVAM_API_URL",
        "https://api.sarvam.ai/v1/chat/completions",
    ).strip()

    if not api_key:
        raise LLMProviderError(
            "SARVAM_API_KEY is missing in .env."
        )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
    except requests.RequestException as error:
        raise LLMProviderError(
            f"Sarvam request failed: {error}"
        ) from error

    if response.status_code != 200:
        raise LLMProviderError(
            f"Sarvam returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        data = response.json()
        answer = (
            data["choices"][0]["message"]["content"]
        )
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise LLMProviderError(
            "Sarvam returned an unexpected response format."
        ) from error

    answer = str(answer or "").strip()

    if not answer:
        raise LLMProviderError("Sarvam returned an empty response.")

    return answer


def generate_text(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 350,
    timeout_seconds: int = 180,
    json_mode: bool = False,
) -> str:
    """
    One provider entry point for answer generation and Router B.

    LLM_MODE=ollama → local Ollama
    LLM_MODE=sarvam → Sarvam API
    """
    mode = get_llm_mode()

    if mode == "sarvam":
        sarvam_timeout = int(
            os.getenv(
                "SARVAM_TIMEOUT_SECONDS",
                str(timeout_seconds),
            )
        )

        return _generate_with_sarvam(
            prompt=prompt,
            timeout_seconds=sarvam_timeout,
        )

    ollama_timeout = int(
        os.getenv(
            "OLLAMA_TIMEOUT_SECONDS",
            str(timeout_seconds),
        )
    )

    return _generate_with_ollama(
        prompt=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=ollama_timeout,
        json_mode=json_mode,
    )