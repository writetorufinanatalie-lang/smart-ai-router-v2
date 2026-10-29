"""Local answer generation through the configured Ollama model."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import ollama

from backend.classifier import DEFAULT_MODEL, LOCAL_OLLAMA_HOST, MODEL_KEEP_ALIVE


_ANSWER_SYSTEM_PROMPT = (
    "Answer the user's request helpfully and directly. Keep the answer concise "
    "unless the user asks for more detail. Do not claim to have performed real-world actions."
)


class LocalAnswerError(RuntimeError):
    """Raised when local answer generation fails or returns no answer."""

    def __init__(self, message: str, *, latency_ms: float | None = None) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms


@dataclass(frozen=True)
class LocalAnswerResult:
    answer: str
    model: str
    latency_ms: float
    processing_location: str = "local"
    external_llm_api_used: bool = False


class LocalAnswerGenerator:
    """Generate answer text using only the local Ollama service."""

    def __init__(self, *, client: Any | None = None, model: str = DEFAULT_MODEL) -> None:
        self._client = client or ollama.Client(host=LOCAL_OLLAMA_HOST)
        self._model = model

    def generate(self, request_text: str) -> LocalAnswerResult:
        if not isinstance(request_text, str) or not request_text.strip():
            raise ValueError("request_text must be a non-empty string")

        started_at = time.perf_counter()
        try:
            response = self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": request_text.strip()},
                ],
                options={"temperature": 0},
                keep_alive=MODEL_KEEP_ALIVE,
            )
            message = getattr(response, "message", None)
            if message is None and isinstance(response, dict):
                message = response.get("message")
            answer = getattr(message, "content", None)
            if answer is None and isinstance(message, dict):
                answer = message.get("content")
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            if not isinstance(answer, str) or not answer.strip():
                raise LocalAnswerError(
                    "The local model returned an empty answer.",
                    latency_ms=latency_ms,
                )
            return LocalAnswerResult(
                answer=answer.strip(),
                model=self._model,
                latency_ms=latency_ms,
            )
        except LocalAnswerError:
            raise
        except Exception as error:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            raise LocalAnswerError(
                "The local model could not generate an answer.",
                latency_ms=latency_ms,
            ) from error
