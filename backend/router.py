"""Routing orchestration with rule-authorized simulated commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from backend.classifier import ClassificationResult, RequestCategory, classify_request
from backend.cloud_adapter import CloudAdapter
from backend.command_parser import CommandParseResult, parse_command
from backend.command_registry import SimulatedDeviceRegistry
from backend.fallback import detect_ambiguity
from backend.local_answer import LocalAnswerError, LocalAnswerGenerator


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
            return self._unsupported(classification, parsed, False)

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
                answer=local_answer.answer,
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
