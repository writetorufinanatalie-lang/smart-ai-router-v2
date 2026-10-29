"""Tests for routing, command overrides, and safe failure behavior."""

from backend.classifier import ClassificationResult, RequestCategory
from backend.command_parser import ParsedCommand, CommandAction
from backend.command_registry import SimulatedDeviceRegistry, UnsupportedCommandError
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


def test_command_label_alone_never_executes_unrecognized_text():
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.COMMAND),
        command_registry=registry,
    )

    response = router.route("Turn on the bedroom light.")

    assert response.classifier_label is RequestCategory.COMMAND
    assert response.final_route is FinalRoute.COMMAND_UNSUPPORTED
    assert response.rule_parser_overrode_classifier is False
    assert response.command_parser_matched is False
    assert response.execution_status == "command_not_supported"
    assert response.message == "command not supported"
    assert registry.calls == []


def test_unrecognized_model_command_does_not_run_arbitrary_actions():
    registry = ExecutionSpy()
    router = SmartRouter(
        classifier=lambda _text: classification(RequestCategory.COMMAND),
        command_registry=registry,
    )

    response = router.route("Format the computer drive.")

    assert response.final_route is FinalRoute.COMMAND_UNSUPPORTED
    assert response.message == "command not supported"
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
    router = SmartRouter(classifier=lambda _text: classification(RequestCategory.SIMPLE))

    response = router.route("What is 2 + 2?")

    assert response.classifier_label is RequestCategory.SIMPLE
    assert response.final_route is FinalRoute.LOCAL
    assert response.execution_status == "awaiting_local_answer"
    assert response.message is None
    assert response.request_sent_to_cloud is False


def test_complex_route_is_reported_without_faking_a_cloud_response():
    router = SmartRouter(classifier=lambda _text: classification(RequestCategory.COMPLEX))

    response = router.route("Write a 500-word story about a dragon.")

    assert response.classifier_label is RequestCategory.COMPLEX
    assert response.final_route is FinalRoute.CLOUD
    assert response.execution_status == "cloud_not_configured"
    assert "no cloud response was generated" in response.message
    assert response.request_sent_to_cloud is False
    assert response.external_llm_api_used is False


def test_registry_independently_rejects_non_whitelisted_device_action():
    registry = SimulatedDeviceRegistry()

    try:
        registry.execute(ParsedCommand("computer", CommandAction.TURN_ON))
    except UnsupportedCommandError as error:
        assert str(error) == "command not supported"
    else:
        raise AssertionError("Unsupported device command was not rejected")
