"""
Thin wrapper around the `ollama` Python client so the rest of the codebase
never touches the raw API directly. Swappable later for llama.cpp / vLLM
by writing another class with the same `generate()` signature - nothing
else in the pipeline needs to change (they all use JSON-schema output
against an OpenAI-compatible-ish interface).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "model.yaml"


def _load_config() -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "The 'PyYAML' package is not installed. "
            "Run: pip install -r requirements.txt"
        ) from exc

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class OllamaStructuredClient:
    def __init__(self, config: dict | None = None):
        self.config = config or _load_config()
        self.model_name = self.config["model"]["name"]
        self.temperature = self.config["model"].get("temperature", 0)
        self.num_ctx = self.config["model"].get("num_ctx", 16384)
        self.thinking_mode = self.config["model"].get("thinking_mode", False)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        thinking: bool | None = None,
    ) -> T:
        try:
            from ollama import chat
        except ImportError as exc:
            raise RuntimeError(
                "The 'ollama' package is not installed. "
                "Run: pip install -r requirements.txt"
            ) from exc

        schema = response_model.model_json_schema()
        use_thinking = self.thinking_mode if thinking is None else thinking

        options = {
            "temperature": self.temperature,
            "num_ctx": self.num_ctx,
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = dict(
            model=self.model_name,
            messages=messages,
            format=schema,
            options=options,
        )
        # Qwen3 supports a /think or /no_think style toggle via the
        # 'think' kwarg in recent ollama-python versions; guarded so this
        # still works on older client versions.
        if use_thinking is not None:
            kwargs["think"] = use_thinking

        try:
            response = chat(**kwargs)
        except TypeError:
            # Older ollama-python without `think=` support
            kwargs.pop("think", None)
            response = chat(**kwargs)

        raw_content = response.message.content

        try:
            return response_model.model_validate_json(raw_content)
        except ValidationError:
            # Some models wrap JSON in fences despite instructions; try a
            # forgiving strip-and-retry once before giving up loudly.
            cleaned = raw_content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:]
            try:
                return response_model.model_validate_json(cleaned)
            except ValidationError as exc2:
                raise RuntimeError(
                    f"Model did not return valid {response_model.__name__} "
                    f"JSON.\nRaw content:\n{raw_content}\n\nError: {exc2}"
                ) from exc2
