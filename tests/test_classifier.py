"""Tests for local-only classification behavior."""

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.classifier import (
    ClassificationError,
    LOCAL_OLLAMA_HOST,
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
    assert result.reason_source == "model"
    assert result.model == "qwen2.5:1.5b"
    assert result.latency_ms >= 0
    assert result.processing_location == "local"
    assert result.external_llm_api_used is False
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["model"] == "qwen2.5:1.5b"
    assert fake_client.calls[0]["options"] == {"temperature": 0}
    assert fake_client.calls[0]["keep_alive"] == "30m"


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

    with pytest.raises(ClassificationError, match="local Ollama") as error:
        classify_request("What is 2 + 2?", client=FailingClient())

    assert error.value.latency_ms is not None
    assert error.value.latency_ms >= 0


def test_default_classification_uses_loopback_and_makes_no_external_network_call(monkeypatch):
    requested_hosts = []

    def guarded_request(_client, method, url, *args, **kwargs):
        resolved_url = _client.base_url.join(httpx.URL(url))
        host = resolved_url.host
        requested_hosts.append(host)
        if host not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"Classification attempted external host: {host}")
        response_payload = {
            "model": "qwen2.5:1.5b",
            "created_at": "2026-01-01T00:00:00Z",
            "done": True,
            "done_reason": "stop",
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {"category": "SIMPLE", "reason": "Mocked local response."}
                ),
            },
        }
        request = httpx.Request(method, resolved_url)
        return httpx.Response(200, json=response_payload, request=request)

    monkeypatch.setattr(httpx.Client, "request", guarded_request)

    result = classify_request("What is 2 + 2?")

    assert result.category is RequestCategory.SIMPLE
    assert LOCAL_OLLAMA_HOST == "http://127.0.0.1:11434"
    assert requested_hosts == ["127.0.0.1"]
