"""Local-only request classification through the Ollama runtime."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import ollama


LOCAL_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:1.5b"
MODEL_KEEP_ALIVE = "30m"


class RequestCategory(str, Enum):
    """The three request types recognized by the router."""

    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"
    COMMAND = "COMMAND"


class ClassificationError(RuntimeError):
    """Raised when the local model cannot return a valid classification."""


@dataclass(frozen=True)
class ClassificationResult:
    """A validated classification and metadata from the local inference call."""

    category: RequestCategory
    reason: str
    model: str
    latency_ms: float
    reason_source: str = "model"
    processing_location: str = "local"
    external_llm_api_used: bool = False


_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": [category.value for category in RequestCategory],
        },
        "reason": {"type": "string"},
    },
    "required": ["category", "reason"],
}

_SYSTEM_PROMPT = """Classify the user's request into exactly one category.
SIMPLE: a short, direct question or task answerable locally.
COMPLEX: lengthy generation, nuanced analysis, or a task likely to need a
more capable model.
COMMAND: a request to take an action, such as turning a device on or off.
Do not perform the task. Return only JSON matching the supplied schema. Keep
the reason brief and do not include any sensitive information from the request.
"""


def _get_response_content(response: Any) -> str:
    """Read response content from Ollama's object or dictionary response."""

    message = getattr(response, "message", None)
    if message is None and isinstance(response, dict):
        message = response.get("message")

    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ClassificationError("The local model returned an empty response.")
    return content


def classify_request(
    request_text: str,
    *,
    model: str = DEFAULT_MODEL,
    client: Any | None = None,
) -> ClassificationResult:
    """Classify text using the local Ollama model only.

    The default client is pinned to the loopback Ollama service. The optional
    client argument exists for isolated tests and should not be used to route
    production classification to a remote host.
    """

    if not isinstance(request_text, str) or not request_text.strip():
        raise ValueError("request_text must be a non-empty string")

    ollama_client = client or ollama.Client(host=LOCAL_OLLAMA_HOST)
    started_at = time.perf_counter()
    try:
        response = ollama_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": request_text.strip()},
            ],
            format=_CLASSIFICATION_SCHEMA,
            options={"temperature": 0},
            keep_alive=MODEL_KEEP_ALIVE,
        )
        payload = json.loads(_get_response_content(response))
        if not isinstance(payload, dict):
            raise ClassificationError("The local model response must be a JSON object.")

        raw_category = payload.get("category")
        raw_reason = payload.get("reason")
        if not isinstance(raw_category, str):
            raise ClassificationError("The local model response has no valid category.")
        if not isinstance(raw_reason, str) or not raw_reason.strip():
            raise ClassificationError("The local model response has no valid reason.")

        try:
            category = RequestCategory(raw_category.strip().upper())
        except ValueError as error:
            raise ClassificationError("The local model returned an unknown category.") from error

        return ClassificationResult(
            category=category,
            reason=raw_reason.strip(),
            model=model,
            latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            reason_source="model",
        )
    except ClassificationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ClassificationError("The local model returned malformed classification data.") from error
    except Exception as error:
        raise ClassificationError("The local Ollama classification request failed.") from error
