"""Tests for local-only answer generation."""

from types import SimpleNamespace

import pytest

from backend.local_answer import LocalAnswerError, LocalAnswerGenerator


class FakeOllamaClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


def test_generates_answer_with_local_model_and_measures_generation_time():
    client = FakeOllamaClient("  2 + 2 = 4.  ")
    generator = LocalAnswerGenerator(client=client)

    result = generator.generate("What is 2 + 2?")

    assert result.answer == "2 + 2 = 4."
    assert result.model == "qwen2.5:1.5b"
    assert result.latency_ms >= 0
    assert result.processing_location == "local"
    assert result.external_llm_api_used is False
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "qwen2.5:1.5b"
    assert client.calls[0]["keep_alive"] == "30m"


def test_rejects_empty_text_without_calling_model():
    client = FakeOllamaClient("unused")
    generator = LocalAnswerGenerator(client=client)

    with pytest.raises(ValueError, match="non-empty"):
        generator.generate(" ")

    assert client.calls == []


def test_reports_empty_model_response_clearly():
    generator = LocalAnswerGenerator(client=FakeOllamaClient("  "))

    with pytest.raises(LocalAnswerError, match="empty answer") as error:
        generator.generate("What is 2 + 2?")

    assert error.value.latency_ms is not None


def test_reports_local_model_failure_with_separate_latency():
    class FailingClient:
        def chat(self, **kwargs):
            raise OSError("Ollama is unavailable")

    generator = LocalAnswerGenerator(client=FailingClient())

    with pytest.raises(LocalAnswerError, match="could not generate") as error:
        generator.generate("What is 2 + 2?")

    assert error.value.latency_ms is not None
    assert error.value.latency_ms >= 0
