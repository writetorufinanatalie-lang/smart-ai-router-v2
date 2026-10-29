"""Tests for local-only classification behavior."""

import json
from types import SimpleNamespace

import pytest

from backend.classifier import (
    ClassificationError,
    RequestCategory,
    classify_request,
)


class FakeOllamaClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


@pytest.mark.parametrize(
    ("category", "query_text"),
    [
        (RequestCategory.SIMPLE, "What is 2 + 2?"),
        (RequestCategory.COMPLEX, "Write a 500-word story about a dragon."),
        (RequestCategory.COMMAND, "Turn on the desk light."),
    ],
)
def test_classifies_all_supported_categories(category, query_text):
    fake_client = FakeOllamaClient(
        json.dumps({"category": category.value, "reason": "Test classification."})
    )

    result = classify_request(query_text, client=fake_client)

    assert result.category is category
    assert result.reason == "Test classification."
    assert result.model == "qwen2.5:1.5b"
    assert result.latency_ms >= 0
    assert result.processing_location == "local"
    assert result.external_llm_api_used is False
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["model"] == "qwen2.5:1.5b"
    assert fake_client.calls[0]["options"] == {"temperature": 0}


def test_rejects_empty_request_without_calling_model():
    fake_client = FakeOllamaClient('{}')

    with pytest.raises(ValueError, match="non-empty"):
        classify_request("  ", client=fake_client)

    assert fake_client.calls == []


@pytest.mark.parametrize(
    "response",
    [
        "not JSON",
        "[]",
        '{"category":"UNKNOWN","reason":"Not supported."}',
        '{"category":"SIMPLE","reason":""}',
        '{"reason":"Missing category."}',
    ],
)
def test_rejects_malformed_or_invalid_classification(response):
    with pytest.raises(ClassificationError):
        classify_request("Explain gravity briefly.", client=FakeOllamaClient(response))


def test_reports_local_model_failure_without_inventing_category():
    class FailingClient:
        def chat(self, **kwargs):
            raise OSError("Ollama is unavailable")

    with pytest.raises(ClassificationError, match="local Ollama"):
        classify_request("What is 2 + 2?", client=FailingClient())
