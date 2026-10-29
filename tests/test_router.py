"""Tests for routing, command overrides, and safe failure behavior."""

import pytest

from backend.classifier import ClassificationResult, RequestCategory
from backend.cloud_adapter import CLOUD_FAILURE_MESSAGE, CloudAdapter
from backend.command_parser import ParsedCommand, CommandAction
from backend.command_registry import SimulatedDeviceRegistry, UnsupportedCommandError
from backend.local_answer import LocalAnswerError, LocalAnswerResult
from backend.router import FinalRoute, SmartRouter


def classification(category):
    return ClassificationResult(
        category=category,
        reason="test classifier reason",
        model="test-model",
        latency_ms=12.5,
    )


class ExecutionSpy:
    def __init__(self):
        self.calls = []

    def execute(self, command):
        self.calls.append(command)
        return SimulatedDeviceRegistry().execute(command)


class FakeAnswerGenerator:
    def __init__(self, answer="2 + 2 = 4.", error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def generate(self, text):
        self.calls.append(text)
        if self.error:
            raise self.error
        return LocalAnswerResult(self.answer, "qwen2.5:1.5b", 42.0)


def test_m3_rule_parser_overrides_simple_label_and_executes_supported_command():
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
    )

    response = router.route("Set the desk light brightness to 40 percent")

    assert response.classifier_label is RequestCategory.SIMPLE
    assert response.final_route is FinalRoute.COMMAND
    assert response.rule_parser_overrode_classifier is True
    assert response.command_parser_matched is True
    assert response.execution_status == "executed_locally"
    assert response.message == "desk light brightness set to 40%"
    assert response.command_result["state"]["brightness"] == 40
    assert response.classification_location == "local"
    assert response.external_llm_api_used is False


def test_whitelisted_command_can_override_complex_classifier_label():
    router = SmartRouter(classifier=lambda _text: classification(RequestCategory.COMPLEX))

    response = router.route("Turn on the desk light.")

    assert response.classifier_label is RequestCategory.COMPLEX
    assert response.final_route is FinalRoute.COMMAND
    assert response.rule_parser_overrode_classifier is True
    assert response.execution_status == "executed_locally"


def test_command_label_with_no_whitelist_match_asks_for_clarification_without_execution():
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.COMMAND),
        command_registry=registry,
    )

    response = router.route("Turn on an unsupported action.")

    assert response.classifier_label is RequestCategory.COMMAND
    assert response.final_route is FinalRoute.CLARIFICATION
    assert response.rule_parser_overrode_classifier is False
    assert response.command_parser_matched is False
    assert response.execution_status == "clarification_needed"
    assert "clarify" in response.message
    assert registry.calls == []


def test_unrecognized_model_command_does_not_run_arbitrary_actions():
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.COMMAND),
        command_registry=registry,
    )

    response = router.route("Format the computer drive.")

    assert response.final_route is FinalRoute.CLARIFICATION
    assert response.execution_status == "clarification_needed"
    assert response.message != "command not supported"
    assert registry.calls == []


def test_unknown_bedroom_light_returns_device_not_supported_without_execution():
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.COMMAND),
        command_registry=registry,
    )

    response = router.route("turn on my bedroom light")

    assert response.final_route is FinalRoute.COMMAND_UNSUPPORTED
    assert response.execution_status == "device_not_supported"
    assert response.message == "device not supported"
    assert response.command_parser_matched is True
    assert registry.calls == []


def test_unknown_device_can_override_non_command_label_but_still_does_not_execute():
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        command_registry=registry,
    )

    response = router.route("turn on my bedroom light")

    assert response.classifier_label is RequestCategory.SIMPLE
    assert response.final_route is FinalRoute.COMMAND_UNSUPPORTED
    assert response.rule_parser_overrode_classifier is True
    assert response.message == "device not supported"
    assert registry.calls == []


def test_out_of_range_command_is_rejected_and_not_executed_even_if_label_is_simple():
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        command_registry=registry,
    )

    response = router.route("Set the desk light brightness to 101 percent.")

    assert response.final_route is FinalRoute.COMMAND_UNSUPPORTED
    assert response.rule_parser_overrode_classifier is True
    assert response.execution_status == "command_not_supported"
    assert registry.calls == []


def test_model_command_with_supported_rule_is_executed_without_override():
    router = SmartRouter(classifier=lambda _text: classification(RequestCategory.COMMAND))

    response = router.route("Turn on the fan.")

    assert response.classifier_label is RequestCategory.COMMAND
    assert response.final_route is FinalRoute.COMMAND
    assert response.rule_parser_overrode_classifier is False
    assert response.command_parser_matched is True
    assert response.message == "fan turned on"


def test_volume_command_uses_whitelisted_simulated_execution():
    router = SmartRouter(classifier=lambda _text: classification(RequestCategory.SIMPLE))

    response = router.route("Set the volume to 30 percent.")

    assert response.final_route is FinalRoute.COMMAND
    assert response.rule_parser_overrode_classifier is True
    assert response.command_result["state"]["level"] == 30


def test_simple_route_reports_pending_local_answer_without_inventing_one():
    generator = FakeAnswerGenerator()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        local_answer_generator=generator,
    )

    response = router.route("What is 2 + 2?")

    assert response.classifier_label is RequestCategory.SIMPLE
    assert response.final_route is FinalRoute.LOCAL
    assert response.execution_status == "completed_locally"
    assert response.answer == "2 + 2 = 4."
    assert response.answer_generation_latency_ms == 42.0
    assert response.classification_latency_ms == 12.5
    assert generator.calls == ["What is 2 + 2?"]
    assert response.request_sent_to_cloud is False


def test_simple_lights_on_request_is_executed_only_by_the_whitelist_parser():
    generator = FakeAnswerGenerator("The lights are on now.")
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        local_answer_generator=generator,
        command_registry=registry,
    )

    response = router.route("lights on please")

    assert response.final_route is FinalRoute.COMMAND
    assert response.execution_status == "executed_locally"
    assert response.command_result["device"] == "desk_light"
    assert response.answer is None
    assert generator.calls == []
    assert len(registry.calls) == 1


def test_unrecognized_simple_device_request_has_distinct_not_performed_status():
    generator = FakeAnswerGenerator("The brightness is now set to 40%.")
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        local_answer_generator=generator,
        command_registry=registry,
    )

    response = router.route("Set brightness to 40")

    assert response.final_route is FinalRoute.LOCAL
    assert response.execution_status == "device_control_not_performed"
    assert response.message.startswith("No device was controlled")
    assert generator.calls == []
    assert registry.calls == []


@pytest.mark.parametrize(
    "text",
    [
        "How do I turn on the fan?",
        "Don't turn off the light.",
        "If it's dark, turn on the light.",
        "Turn on the desk light and switch off the fan.",
    ],
)
def test_unsafe_command_forms_ask_for_clarification_and_never_execute(text):
    registry = ExecutionSpy()
    generator = FakeAnswerGenerator()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        command_registry=registry,
        local_answer_generator=generator,
    )

    response = router.route(text)

    assert response.final_route is FinalRoute.CLARIFICATION
    assert response.execution_status == "clarification_needed"
    assert registry.calls == []
    assert generator.calls == []


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("How does a ceiling fan work?", "A ceiling fan moves air."),
        ("What is a light year?", "A light-year measures distance."),
    ],
)
def test_normal_questions_are_not_caught_by_device_control_guard(text, answer):
    generator = FakeAnswerGenerator(answer)
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        local_answer_generator=generator,
    )

    response = router.route(text)

    assert response.final_route is FinalRoute.LOCAL
    assert response.answer == answer
    assert generator.calls == [text]


def test_local_answer_claiming_device_control_is_replaced_with_safe_message():
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        local_answer_generator=FakeAnswerGenerator("I turned on the desk light."),
    )

    response = router.route("What is the desk light used for?")

    assert response.answer == (
        "No device was controlled. This request did not match a supported device command."
    )


def test_local_answer_claim_about_another_device_is_also_replaced():
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        local_answer_generator=FakeAnswerGenerator("The television is on now."),
    )

    response = router.route("What does television status mean?")

    assert response.answer == (
        "No device was controlled. This request did not match a supported device command."
    )


def test_simple_route_reports_clear_error_when_local_answer_generation_fails():
    generator = FakeAnswerGenerator(
        error=LocalAnswerError("The local model could not generate an answer.", latency_ms=18.0)
    )
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.SIMPLE),
        local_answer_generator=generator,
    )

    response = router.route("What is 2 + 2?")

    assert response.execution_status == "local_generation_failed"
    assert "Local answer generation failed" in response.message
    assert response.answer is None
    assert response.answer_generation_latency_ms == 18.0


def test_complex_route_is_reported_without_faking_a_cloud_response():
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.COMPLEX),
        cloud_adapter=CloudAdapter(api_key=""),
    )

    response = router.route("Write a 500-word story about a dragon.")

    assert response.classifier_label is RequestCategory.COMPLEX
    assert response.final_route is FinalRoute.CLOUD
    assert response.execution_status == "cloud_not_configured"
    assert response.message == CLOUD_FAILURE_MESSAGE
    assert response.answer is None
    assert response.request_sent_to_cloud is False
    assert response.external_llm_api_used is False


def test_cloud_route_privacy_shield_blocks_personal_data_before_sender_call():
    calls = []
    adapter = CloudAdapter(
        api_key="test-key",
        sender=lambda text, key: calls.append((text, key)) or "unexpected answer",
    )
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.COMPLEX),
        cloud_adapter=adapter,
    )

    response = router.route("Summarize this note for sam@example.com")

    assert response.final_route is FinalRoute.CLOUD
    assert response.execution_status == "blocked_by_privacy_shield"
    assert response.message == CLOUD_FAILURE_MESSAGE
    assert response.privacy_blocked is True
    assert response.sensitive_data_types == ("email",)
    assert response.request_sent_to_cloud is False
    assert response.answer is None
    assert calls == []


def test_conflicting_brevity_and_detail_request_asks_for_clarification():
    router = SmartRouter(classifier=lambda _text: classification(RequestCategory.COMPLEX))

    response = router.route("Explain AI briefly but include every technical detail.")

    assert response.final_route is FinalRoute.CLARIFICATION
    assert response.execution_status == "clarification_needed"
    assert "Which should I prioritize?" in response.message
    assert response.answer is None
    assert response.request_sent_to_cloud is False


def test_registry_independently_rejects_non_whitelisted_device_action():
    registry = SimulatedDeviceRegistry()

    try:
        registry.execute(ParsedCommand("computer", CommandAction.TURN_ON))
    except UnsupportedCommandError as error:
        assert str(error) == "command not supported"
    else:
        raise AssertionError("Unsupported device command was not rejected")
