"""Tests for honest cloud-adapter behavior without a configured provider."""

from backend.cloud_adapter import CLOUD_FAILURE_MESSAGE, CloudAdapter


def test_missing_api_key_does_not_call_sender_and_returns_exact_message(monkeypatch):
    monkeypatch.delenv("CLOUD_API_KEY", raising=False)
    calls = []
    adapter = CloudAdapter(sender=lambda text, key: calls.append((text, key)))

    result = adapter.process("Write a story about a dragon.")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.message == "Cloud route selected, but the request could not be processed"
    assert result.answer is None
    assert result.status == "cloud_not_configured"
    assert result.processed is False
    assert result.request_sent_to_cloud is False
    assert calls == []


def test_api_key_without_provider_sender_still_does_not_claim_success():
    adapter = CloudAdapter(api_key="test-key")

    result = adapter.process("Write a story about a dragon.")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.answer is None
    assert result.processed is False
    assert result.request_sent_to_cloud is False


def test_provider_exception_returns_failure_without_fabricating_answer():
    def failing_sender(_text, _key):
        raise OSError("provider unavailable")

    adapter = CloudAdapter(api_key="test-key", sender=failing_sender)

    result = adapter.process("Write a story about a dragon.")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.answer is None
    assert result.status == "cloud_request_failed"
    assert result.processed is False
    assert result.request_sent_to_cloud is True
    assert result.cloud_latency_ms is not None
    assert result.cloud_latency_ms >= 0


def test_empty_provider_response_is_not_reported_as_an_answer():
    adapter = CloudAdapter(api_key="test-key", sender=lambda _text, _key: "  ")

    result = adapter.process("Write a story about a dragon.")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.answer is None
    assert result.processed is False


def test_privacy_shield_blocks_email_before_sender_call():
    calls = []
    adapter = CloudAdapter(
        api_key="test-key",
        sender=lambda text, key: calls.append((text, key)) or "unexpected answer",
    )

    result = adapter.process("Summarize this email: alex@example.com")

    assert result.message == CLOUD_FAILURE_MESSAGE
    assert result.answer is None
    assert result.privacy_blocked is True
    assert result.sensitive_data_types == ("email",)
    assert result.request_sent_to_cloud is False
    assert calls == []


def test_privacy_shield_blocks_phone_and_card_numbers_before_sender_call():
    for sensitive_text, expected_type in [
        ("Call 415-555-2671", "phone_number"),
        ("Card 4111 1111 1111 1111", "card_like_number"),
    ]:
        calls = []
        adapter = CloudAdapter(
            api_key="test-key",
            sender=lambda text, key: calls.append((text, key)) or "unexpected answer",
        )

        result = adapter.process(sensitive_text)

        assert result.message == CLOUD_FAILURE_MESSAGE
        assert result.privacy_blocked is True
        assert expected_type in result.sensitive_data_types
        assert result.request_sent_to_cloud is False
        assert calls == []
