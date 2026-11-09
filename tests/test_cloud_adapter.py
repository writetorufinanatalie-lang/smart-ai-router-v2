"""Mocked tests for the Anthropic cloud adapter and routing boundary."""

import logging

import httpx
import pytest

from backend.classifier import ClassificationResult, RequestCategory
from backend.cloud_adapter import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_MESSAGES_URL,
    CLOUD_FAILURE_MESSAGE,
    CloudAdapter,
)
from backend.local_answer import LocalAnswerResult
from backend.router import FinalRoute, SmartRouter


API_KEY = "never-log-this-test-key"
MODEL = "example-model"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {
            "content": [{"type": "text", "text": "A useful answer."}],
            "usage": {"input_tokens": 5, "output_tokens": 8},
        }
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


def configured_adapter(monkeypatch, **kwargs):
    monkeypatch.setenv("CLOUD_MODEL", MODEL)
    return CloudAdapter(api_key=API_KEY, **kwargs)


def test_success_sends_documented_messages_request_and_reads_text(monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse()

    monkeypatch.setattr("backend.cloud_adapter.httpx.post", fake_post)
    adapter = configured_adapter(monkeypatch)

    result = adapter.process("Explain how rainbows form.")

    assert result.answer == "A useful answer."
    assert result.status == "completed"
    assert result.request_sent_to_cloud is True
    assert result.cloud_latency_ms is not None
    url, headers, body, timeout = calls[0]
    assert url == ANTHROPIC_MESSAGES_URL
    assert headers == {
        "x-api-key": API_KEY,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    assert body == {
        "model": MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Explain how rainbows form."}],
    }
    assert timeout > 0


def test_missing_key_does_not_send_request(monkeypatch):
    monkeypatch.setenv("CLOUD_MODEL", MODEL)
    calls = []
    monkeypatch.setattr("backend.cloud_adapter.httpx.post", lambda *args, **kwargs: calls.append(1))

    result = CloudAdapter(api_key="").process("Explain rainbows.")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.reason_code == "missing_api_key"
    assert result.request_sent_to_cloud is False
    assert calls == []


@pytest.mark.parametrize(
    ("status_code", "reason_code"),
    [
        (401, "authentication_error"),
        (403, "authentication_error"),
        (400, "billing_or_request_error"),
        (402, "billing_or_request_error"),
        (404, "model_not_found"),
        (429, "rate_limited"),
        (500, "provider_error"),
    ],
)
def test_provider_http_errors_return_safe_reason(monkeypatch, status_code, reason_code):
    monkeypatch.setattr(
        "backend.cloud_adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(status_code=status_code),
    )

    result = configured_adapter(monkeypatch).process("Confidential request text")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.answer is None
    assert result.reason_code == reason_code
    assert result.status == reason_code
    assert result.request_sent_to_cloud is True
    assert "Confidential request text" not in repr(result)
    assert API_KEY not in repr(result)


def test_network_failure_is_safe_and_not_marked_as_sent(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError(f"failure included {API_KEY}")

    monkeypatch.setattr("backend.cloud_adapter.httpx.post", fail)
    result = configured_adapter(monkeypatch).process("Do not retain this request")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.reason_code == "network_failure"
    assert result.request_sent_to_cloud is False
    assert API_KEY not in repr(result)
    assert "Do not retain this request" not in repr(result)


def test_timeout_after_send_is_safe_and_records_sent(monkeypatch):
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout(f"failure included {API_KEY}")

    monkeypatch.setattr("backend.cloud_adapter.httpx.post", timeout)
    result = configured_adapter(monkeypatch).process("Do not retain this request")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.reason_code == "provider_timeout"
    assert result.request_sent_to_cloud is True
    assert result.cloud_latency_ms is not None
    assert API_KEY not in repr(result)


def test_unexpected_provider_error_does_not_leak_exception(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise RuntimeError(f"provider error {API_KEY}: private request details")

    monkeypatch.setattr("backend.cloud_adapter.httpx.post", fail)
    with caplog.at_level(logging.DEBUG):
        result = configured_adapter(monkeypatch).process("private request details")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.reason_code == "provider_error"
    assert API_KEY not in repr(result)
    assert "private request details" not in repr(result)
    assert API_KEY not in caplog.text
    assert "private request details" not in caplog.text


def test_api_key_never_appears_in_status_or_returned_values(monkeypatch):
    monkeypatch.setattr(
        "backend.cloud_adapter.httpx.post",
        lambda *args, **kwargs: FakeResponse(),
    )
    adapter = configured_adapter(monkeypatch)
    result = adapter.process("Ordinary request")

    assert API_KEY not in repr(result)
    assert API_KEY not in repr(adapter.configuration_status())


def _classification(category):
    return ClassificationResult(
        category=category,
        reason="test classification",
        model="local-test-model",
        latency_ms=1.0,
    )


class _LocalAnswer:
    def generate(self, _text):
        return LocalAnswerResult("A local answer.", "local-test-model", 1.0)


@pytest.mark.parametrize(
    ("category", "request_text", "expected_route"),
    [
        (RequestCategory.SIMPLE, "What is two plus two?", FinalRoute.LOCAL),
        (RequestCategory.COMMAND, "Turn on an unsupported device", FinalRoute.CLARIFICATION),
        (
            RequestCategory.COMPLEX,
            "Explain this briefly but include every technical detail.",
            FinalRoute.CLARIFICATION,
        ),
    ],
)
def test_non_cloud_routes_never_call_provider(
    monkeypatch, category, request_text, expected_route
):
    calls = []
    adapter = configured_adapter(
        monkeypatch,
        sender=lambda text, key: calls.append((text, key)) or "unexpected",
    )
    router = SmartRouter(
        classifier=lambda _text: _classification(category),
        cloud_adapter=adapter,
        local_answer_generator=_LocalAnswer(),
    )

    response = router.route(request_text)

    assert response.final_route is expected_route
    assert calls == []
    assert response.request_sent_to_cloud is False


def test_shield_blocked_complex_route_never_calls_provider(monkeypatch):
    calls = []
    adapter = configured_adapter(
        monkeypatch,
        sender=lambda text, key: calls.append((text, key)) or "unexpected",
    )
    router = SmartRouter(
        classifier=lambda _text: _classification(RequestCategory.COMPLEX),
        cloud_adapter=adapter,
    )

    response = router.route("Compare these options for alex@example.com")

    assert response.final_route is FinalRoute.CLOUD
    assert response.privacy_blocked is True
    assert response.request_sent_to_cloud is False
    assert calls == []
