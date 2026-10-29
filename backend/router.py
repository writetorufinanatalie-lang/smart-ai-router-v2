"""Routing orchestration with rule-authorized simulated commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Callable

from backend.classifier import ClassificationResult, RequestCategory, classify_request
from backend.cloud_adapter import CloudAdapter
from backend.command_parser import CommandParseResult, parse_command
from backend.command_registry import SimulatedDeviceRegistry
from backend.fallback import detect_ambiguity
from backend.local_answer import LocalAnswerError, LocalAnswerGenerator


_DEVICE_CONTROL_REQUEST = re.compile(
    r"\b(?:light|lights|desk light|fan|volume|brightness)\b.*"
    r"\b(?:on|off|turn|switch|power|activate|deactivate|set|adjust|dim|"
    r"brighten|lower|raise|increase|decrease|make)\b|"
    r"\b(?:turn|switch|power|activate|deactivate|set|adjust|dim|brighten|"
    r"lower|raise|increase|decrease|make)\b.*"
    r"\b(?:light|lights|desk light|fan|volume|brightness)\b",
    re.IGNORECASE,
)
_DEVICE_CONTROL_CLAIM = re.compile(
    r"\b(?:i|we)\s+(?:have\s+)?(?:turned|switched|powered|activated|"
    r"deactivated|set|adjusted|dimmed|brightened|lowered|raised|changed)\b|"
    r"\b(?:the|your|my)\s+[a-z0-9'-]+(?:\s+[a-z0-9'-]+){0,2}\s+"
    r"(?:is|are|was|were)\s+(?:now\s+)?(?:on|off|set|adjusted)\b|"
    r"\b[a-z0-9'-]+(?:\s+[a-z0-9'-]+){0,2}\s+"
    r"(?:turned|switched|powered)\s+(?:on|off)\b|"
    r"\b(?:light|lights|desk light|fan|volume)\b.{0,48}\b"
    r"(?:is|are|was|were)\s+(?:now\s+)?(?:on|off|set|adjusted)\b|"
    r"\b(?:light|lights|desk light|fan|volume)\b.{0,32}\b"
    r"(?:turned|switched|powered)\s+(?:on|off)\b",
    re.IGNORECASE,
)
_NO_DEVICE_CONTROL_MESSAGE = (
    "No device was controlled. This request did not match a supported device command."
)


class FinalRoute(str, Enum):
    LOCAL = "LOCAL"
    CLOUD = "CLOUD"
    COMMAND = "COMMAND"
    COMMAND_UNSUPPORTED = "COMMAND_UNSUPPORTED"
    CLARIFICATION = "CLARIFICATION"


@dataclass(frozen=True)
class RoutingResponse:
    """Routing and execution metadata suitable for a later API response."""

    classifier_label: RequestCategory
    final_route: FinalRoute
    rule_parser_overrode_classifier: bool
    command_parser_matched: bool
    classification_reason: str
    classification_reason_source: str
    classification_latency_ms: float
    execution_status: str
    message: str | None = None
    answer: str | None = None
    answer_generation_latency_ms: float | None = None
    cloud_latency_ms: float | None = None
    command_result: dict[str, Any] | None = None
    classification_location: str = "local"
    external_llm_api_used: bool = False
    request_sent_to_cloud: bool = False
    privacy_blocked: bool = False
    sensitive_data_types: tuple[str, ...] = ()


class SmartRouter:
    """Classify requests, safely recognize commands, and select a final route."""

    def __init__(
        self,
        *,
        classifier: Callable[[str], ClassificationResult] = classify_request,
        command_parser: Callable[[str], CommandParseResult] = parse_command,
        command_registry: SimulatedDeviceRegistry | None = None,
        local_answer_generator: LocalAnswerGenerator | None = None,
        cloud_adapter: CloudAdapter | None = None,
    ) -> None:
        self._classifier = classifier
        self._command_parser = command_parser
        self._command_registry = command_registry or SimulatedDeviceRegistry()
        self._local_answer_generator = local_answer_generator or LocalAnswerGenerator()
        self._cloud_adapter = cloud_adapter or CloudAdapter()

    def route(self, request_text: str) -> RoutingResponse:
        classification = self._classifier(request_text)
        parsed = self._command_parser(request_text)
        parser_overrode = parsed.recognized_command and classification.category is not RequestCategory.COMMAND

        if parsed.clarification_needed:
            return RoutingResponse(
                classifier_label=classification.category,
                final_route=FinalRoute.CLARIFICATION,
                rule_parser_overrode_classifier=False,
                command_parser_matched=False,
                classification_reason=classification.reason,
                classification_reason_source=classification.reason_source,
                classification_latency_ms=classification.latency_ms,
                execution_status="clarification_needed",
                message=(
                    "I couldn't safely interpret that as one supported device command. "
                    "Please clarify the single action you want."
                ),
            )

        if parsed.recognized_command:
            if parsed.command is None:
                return self._unsupported(classification, parsed, parser_overrode)
            execution = self._command_registry.execute(parsed.command)
            return RoutingResponse(
                classifier_label=classification.category,
                final_route=FinalRoute.COMMAND,
                rule_parser_overrode_classifier=parser_overrode,
                command_parser_matched=True,
                classification_reason=classification.reason,
                classification_reason_source=classification.reason_source,
                classification_latency_ms=classification.latency_ms,
                execution_status="executed_locally",
                message=execution.message,
                command_result={
                    "device": execution.device,
                    "action": execution.action,
                    "state": execution.state,
                },
            )

        if classification.category is RequestCategory.COMMAND:
            return RoutingResponse(
                classifier_label=classification.category,
                final_route=FinalRoute.CLARIFICATION,
                rule_parser_overrode_classifier=False,
                command_parser_matched=False,
                classification_reason=classification.reason,
                classification_reason_source=classification.reason_source,
                classification_latency_ms=classification.latency_ms,
                execution_status="clarification_needed",
                message=(
                    "I couldn't match that to a supported device command. "
                    "Could you clarify what you want to do?"
                ),
            )

        ambiguity = detect_ambiguity(request_text)
        if ambiguity is not None:
            return RoutingResponse(
                classifier_label=classification.category,
                final_route=FinalRoute.CLARIFICATION,
                rule_parser_overrode_classifier=False,
                command_parser_matched=False,
                classification_reason=classification.reason,
                classification_reason_source=classification.reason_source,
                classification_latency_ms=classification.latency_ms,
                execution_status="clarification_needed",
                message=ambiguity.message,
            )

        if classification.category is RequestCategory.SIMPLE:
            if _DEVICE_CONTROL_REQUEST.search(request_text):
                return RoutingResponse(
                    classifier_label=classification.category,
                    final_route=FinalRoute.LOCAL,
                    rule_parser_overrode_classifier=False,
                    command_parser_matched=False,
                    classification_reason=classification.reason,
                    classification_reason_source=classification.reason_source,
                    classification_latency_ms=classification.latency_ms,
                    execution_status="completed_locally",
                    message=_NO_DEVICE_CONTROL_MESSAGE,
                )
            try:
                local_answer = self._local_answer_generator.generate(request_text)
            except LocalAnswerError as error:
                return RoutingResponse(
                    classifier_label=classification.category,
                    final_route=FinalRoute.LOCAL,
                    rule_parser_overrode_classifier=False,
                    command_parser_matched=False,
                    classification_reason=classification.reason,
                    classification_reason_source=classification.reason_source,
                    classification_latency_ms=classification.latency_ms,
                    execution_status="local_generation_failed",
                    message=f"Local answer generation failed: {error}",
                    answer_generation_latency_ms=error.latency_ms,
                )
            return RoutingResponse(
                classifier_label=classification.category,
                final_route=FinalRoute.LOCAL,
                rule_parser_overrode_classifier=False,
                command_parser_matched=False,
                classification_reason=classification.reason,
                classification_reason_source=classification.reason_source,
                classification_latency_ms=classification.latency_ms,
                execution_status="completed_locally",
                answer=(
                    _NO_DEVICE_CONTROL_MESSAGE
                    if _DEVICE_CONTROL_CLAIM.search(local_answer.answer)
                    else local_answer.answer
                ),
                answer_generation_latency_ms=local_answer.latency_ms,
            )

        cloud_result = self._cloud_adapter.process(request_text)
        return RoutingResponse(
            classifier_label=classification.category,
            final_route=FinalRoute.CLOUD,
            rule_parser_overrode_classifier=False,
            command_parser_matched=False,
            classification_reason=classification.reason,
            classification_reason_source=classification.reason_source,
            classification_latency_ms=classification.latency_ms,
            execution_status=cloud_result.status,
            message=cloud_result.message,
            answer=cloud_result.answer,
            cloud_latency_ms=cloud_result.cloud_latency_ms,
            external_llm_api_used=cloud_result.request_sent_to_cloud,
            request_sent_to_cloud=cloud_result.request_sent_to_cloud,
            privacy_blocked=cloud_result.privacy_blocked,
            sensitive_data_types=cloud_result.sensitive_data_types,
        )

    @staticmethod
    def _unsupported(
        classification: ClassificationResult,
        parsed: CommandParseResult,
        parser_overrode: bool,
    ) -> RoutingResponse:
        device_unsupported = parsed.unsupported_device
        return RoutingResponse(
            classifier_label=classification.category,
            final_route=FinalRoute.COMMAND_UNSUPPORTED,
            rule_parser_overrode_classifier=parser_overrode,
            command_parser_matched=parsed.recognized_command,
            classification_reason=classification.reason,
            classification_reason_source=classification.reason_source,
            classification_latency_ms=classification.latency_ms,
            execution_status=(
                "device_not_supported" if device_unsupported else "command_not_supported"
            ),
            message="device not supported" if device_unsupported else "command not supported",
        )
