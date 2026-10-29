"""Routing orchestration with rule-authorized simulated commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from backend.classifier import ClassificationResult, RequestCategory, classify_request
from backend.command_parser import CommandParseResult, parse_command
from backend.command_registry import SimulatedDeviceRegistry


class FinalRoute(str, Enum):
    LOCAL = "LOCAL"
    CLOUD = "CLOUD"
    COMMAND = "COMMAND"
    COMMAND_UNSUPPORTED = "COMMAND_UNSUPPORTED"


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
    command_result: dict[str, Any] | None = None
    classification_location: str = "local"
    external_llm_api_used: bool = False
    request_sent_to_cloud: bool = False


class SmartRouter:
    """Classify requests, safely recognize commands, and select a final route."""

    def __init__(
        self,
        *,
        classifier: Callable[[str], ClassificationResult] = classify_request,
        command_parser: Callable[[str], CommandParseResult] = parse_command,
        command_registry: SimulatedDeviceRegistry | None = None,
    ) -> None:
        self._classifier = classifier
        self._command_parser = command_parser
        self._command_registry = command_registry or SimulatedDeviceRegistry()

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

        if classification.category is RequestCategory.SIMPLE:
            return RoutingResponse(
                classifier_label=classification.category,
                final_route=FinalRoute.LOCAL,
                rule_parser_overrode_classifier=False,
                command_parser_matched=False,
                classification_reason=classification.reason,
                classification_reason_source=classification.reason_source,
                classification_latency_ms=classification.latency_ms,
                execution_status="awaiting_local_answer",
            )

        return RoutingResponse(
            classifier_label=classification.category,
            final_route=FinalRoute.CLOUD,
            rule_parser_overrode_classifier=False,
            command_parser_matched=False,
            classification_reason=classification.reason,
            classification_reason_source=classification.reason_source,
            classification_latency_ms=classification.latency_ms,
            execution_status="cloud_not_configured",
            message="Routed to cloud; no cloud response was generated because cloud integration is not configured yet.",
        )

    @staticmethod
    def _unsupported(
        classification: ClassificationResult,
        parsed: CommandParseResult,
        parser_overrode: bool,
    ) -> RoutingResponse:
        return RoutingResponse(
            classifier_label=classification.category,
            final_route=FinalRoute.COMMAND_UNSUPPORTED,
            rule_parser_overrode_classifier=parser_overrode,
            command_parser_matched=parsed.recognized_command,
            classification_reason=classification.reason,
            classification_reason_source=classification.reason_source,
            classification_latency_ms=classification.latency_ms,
            execution_status="command_not_supported",
            message="command not supported",
        )
