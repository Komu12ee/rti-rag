from __future__ import annotations
from typing import Any, Iterator
import os
from pathlib import Path
import json
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
    temperature: float,
    max_tokens: int,
    timeout_seconds: int,
    json_mode: bool,
    reasoning_effort: str | None,
    json_schema: dict[str, Any] | None = None,
    json_schema_name: str | None = None,
) -> str:
    """Send a request to Sarvam Chat Completions with optional JSON mode."""
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

    if reasoning_effort not in {None, "low", "medium", "high"}:
        raise LLMProviderError(
            "Invalid reasoning_effort. Use low, medium, high, or None."
        )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort

    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": json_schema_name or "structured_response",
                "schema": json_schema,
            },
        }
    elif json_mode:
        payload["response_format"] = {
            "type": "json_object"
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
            f"{response.text[:1000]}"
        )

    try:
        data = response.json()

        choice = data["choices"][0]
        message = choice.get("message") or {}

        answer = message.get("content")
        finish_reason = choice.get("finish_reason")
        refusal = message.get("refusal")
        reasoning_content = message.get("reasoning_content")

    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise LLMProviderError(
            f"Sarvam returned an unexpected response format: {response.text[:1500]}"
        ) from error

    answer = str(answer or "").strip()

    if not answer:
        debug_info = {
            "finish_reason": finish_reason,
            "refusal": refusal,
            "has_reasoning_content": bool(reasoning_content),
            "reasoning_length": len(str(reasoning_content or "")),
            "message_keys": list(message.keys()),
            "usage": data.get("usage"),
        }

        raise LLMProviderError(
            f"Sarvam returned empty content. Diagnostic: "
            f"{json.dumps(debug_info, ensure_ascii=False)}"
        )
    
    return answer


def _sarvam_stream_delta(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""

    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    if isinstance(delta, dict):
        content = delta.get("content")
        if content:
            return str(content)

    message = choice.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if content:
            return str(content)

    content = choice.get("content")
    return str(content or "")


def _stream_with_sarvam(
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_seconds: int,
    reasoning_effort: str | None,
) -> Iterator[str]:
    """Stream visible text from Sarvam Chat Completions SSE."""
    api_key = os.getenv("SARVAM_API_KEY", "").strip()
    model = os.getenv("SARVAM_MODEL", "sarvam-105b").strip()
    url = os.getenv(
        "SARVAM_API_URL",
        "https://api.sarvam.ai/v1/chat/completions",
    ).strip()

    if not api_key:
        raise LLMProviderError("SARVAM_API_KEY is missing in .env.")

    if reasoning_effort not in {None, "low", "medium", "high"}:
        raise LLMProviderError(
            "Invalid reasoning_effort. Use low, medium, high, or None."
        )

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort

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
            stream=True,
        )
    except requests.RequestException as error:
        raise LLMProviderError(
            f"Sarvam streaming request failed: {error}"
        ) from error

    with response:
        if response.status_code != 200:
            raise LLMProviderError(
                f"Sarvam returned HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

        saw_text = False
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            line = str(raw_line).strip()
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue

            payload_text = line[5:].strip()
            if payload_text == "[DONE]":
                break

            try:
                event_data = json.loads(payload_text)
            except ValueError as error:
                raise LLMProviderError(
                    f"Sarvam returned invalid stream JSON: {payload_text[:500]}"
                ) from error

            if event_data.get("error"):
                raise LLMProviderError(
                    "Sarvam stream returned an error: "
                    f"{json.dumps(event_data['error'], ensure_ascii=False)}"
                )

            delta = _sarvam_stream_delta(event_data)
            if delta:
                saw_text = True
                yield delta

        if not saw_text:
            raise LLMProviderError("Sarvam stream returned no visible text.")


def generate_text(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 350,
    timeout_seconds: int = 180,
    json_mode: bool = False,
    reasoning_effort: str | None = None,
    json_schema: dict[str, Any] | None = None,
    json_schema_name: str | None = None,
) -> str:
    """
    One provider entry point for answer generation and Router B.

    LLM_MODE=ollama -> local Ollama
    LLM_MODE=sarvam -> Sarvam API

    json_mode=True:
    - Ollama uses format="json"
    - Sarvam uses response_format={"type": "json_object"}
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
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=sarvam_timeout,
            json_mode=json_mode,
            reasoning_effort=reasoning_effort,
            json_schema=json_schema,
            json_schema_name=json_schema_name,
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


def stream_text(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 350,
    timeout_seconds: int = 180,
    reasoning_effort: str | None = None,
) -> Iterator[str]:
    """
    Stream only visible user-facing text.

    Structured JSON calls intentionally remain on generate_text(), because a
    streamed partial JSON object is not useful to the validators.
    """
    mode = get_llm_mode()

    if mode == "sarvam":
        sarvam_timeout = int(
            os.getenv(
                "SARVAM_TIMEOUT_SECONDS",
                str(timeout_seconds),
            )
        )

        yield from _stream_with_sarvam(
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=sarvam_timeout,
            reasoning_effort=reasoning_effort,
        )
        return

    yield generate_text(
        prompt=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        json_mode=False,
        reasoning_effort=reasoning_effort,
    )
