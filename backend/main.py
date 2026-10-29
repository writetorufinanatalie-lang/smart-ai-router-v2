"""FastAPI application exposing routing, metrics, health, and evaluation APIs."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import ollama
from fastapi import FastAPI
from pydantic import BaseModel, Field

from backend.classifier import (
    DEFAULT_MODEL,
    LOCAL_OLLAMA_HOST,
    ClassificationError,
    RequestCategory,
)
from backend.cloud_adapter import CloudAdapter
from backend.metrics_store import MetricsStore
from backend.router import RoutingResponse, SmartRouter


DEFAULT_METRICS_PATH = Path(__file__).resolve().parent.parent / "data" / "metrics.db"


class RouteRequest(BaseModel):
    request_text: str = Field(min_length=1, max_length=10_000)


class EvaluationCase(BaseModel):
    request_text: str = Field(min_length=1, max_length=10_000)
    expected_label: RequestCategory


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)


def _probe_ollama() -> dict[str, Any]:
    """Check the real local Ollama service and whether the chosen model exists."""

    try:
        ollama_client = ollama.Client(host=LOCAL_OLLAMA_HOST, timeout=2.0)
        response = ollama_client.list()
        models = getattr(response, "models", [])
        names = []
        for model in models:
            if isinstance(model, dict):
                name = model.get("model") or model.get("name")
            else:
                name = getattr(model, "model", None) or getattr(model, "name", None)
            if isinstance(name, str):
                names.append(name)
        model_available = DEFAULT_MODEL in names
        return {
            "status": "available" if model_available else "model_missing",
            "service_available": True,
            "model": DEFAULT_MODEL,
            "model_available": model_available,
        }
    except Exception:
        return {
            "status": "unavailable",
            "service_available": False,
            "model": DEFAULT_MODEL,
            "model_available": False,
        }


def _response_payload(response: RoutingResponse) -> dict[str, Any]:
    payload = asdict(response)
    payload["classifier_label"] = response.classifier_label.value
    payload["final_route"] = response.final_route.value
    payload["sensitive_data_types"] = list(response.sensitive_data_types)
    return payload


def _classification_failure_payload(error: ClassificationError) -> dict[str, Any]:
    return {
        "classifier_label": None,
        "final_route": "ERROR",
        "rule_parser_overrode_classifier": False,
        "command_parser_matched": False,
        "classification_reason": "",
        "classification_reason_source": "none",
        "classification_latency_ms": error.latency_ms,
        "answer_generation_latency_ms": None,
        "cloud_latency_ms": None,
        "execution_status": "classification_failed",
        "message": "Local classification failed; no route was selected.",
        "answer": None,
        "command_result": None,
        "classification_location": "local",
        "external_llm_api_used": False,
        "request_sent_to_cloud": False,
        "privacy_blocked": False,
        "sensitive_data_types": [],
    }


def create_app(
    *,
    database_path: str | Path | None = None,
    metrics_store: MetricsStore | None = None,
    router: SmartRouter | None = None,
    cloud_adapter: CloudAdapter | None = None,
    ollama_health_check: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    adapter = cloud_adapter or getattr(router, "_cloud_adapter", None) or CloudAdapter()
    request_router = router or SmartRouter(cloud_adapter=adapter)
    store = metrics_store or MetricsStore(database_path or DEFAULT_METRICS_PATH)
    health_check = ollama_health_check or _probe_ollama

    app = FastAPI(title="Smart AI Router", version="0.1.0")
    app.state.router = request_router
    app.state.metrics_store = store
    app.state.cloud_adapter = adapter

    def route_and_record(
        request_text: str,
        *,
        request_kind: str = "route",
        expected_label: RequestCategory | None = None,
    ) -> tuple[dict[str, Any], bool | None]:
        expected_value = expected_label.value if expected_label is not None else None
        try:
            response = request_router.route(request_text)
        except ClassificationError as error:
            store.record_classification_failure(
                classification_time_ms=error.latency_ms,
                request_kind=request_kind,
                expected_label=expected_value,
            )
            return _classification_failure_payload(error), False if expected_label else None

        is_correct = (
            response.classifier_label is expected_label
            if expected_label is not None
            else None
        )
        store.record_response(
            response,
            request_kind=request_kind,
            expected_label=expected_value,
            evaluation_correct=is_correct,
        )
        return _response_payload(response), is_correct

    @app.post("/route")
    def route_request(body: RouteRequest) -> dict[str, Any]:
        payload, _ = route_and_record(body.request_text)
        return payload

    @app.get("/stats")
    def get_stats() -> dict[str, object]:
        return store.stats()

    @app.get("/health")
    def get_health() -> dict[str, Any]:
        storage_available = store.ping()
        ollama_status = health_check()
        backend_status = "ok" if storage_available else "unavailable"
        healthy = storage_available and ollama_status.get("model_available", False)
        return {
            "status": "ok" if healthy else "degraded",
            "backend": {"status": backend_status, "metrics_store_available": storage_available},
            "ollama": ollama_status,
            "cloud": adapter.configuration_status(),
        }

    @app.post("/evaluate")
    def evaluate(body: EvaluationRequest) -> dict[str, Any]:
        results = []
        correct_count = 0
        for index, case in enumerate(body.cases, start=1):
            payload, is_correct = route_and_record(
                case.request_text,
                request_kind="evaluation",
                expected_label=case.expected_label,
            )
            correct = bool(is_correct)
            correct_count += int(correct)
            results.append(
                {
                    "case": index,
                    "expected_label": case.expected_label.value,
                    "classifier_label": payload["classifier_label"],
                    "final_route": payload["final_route"],
                    "correct": correct,
                    "classification_latency_ms": payload["classification_latency_ms"],
                    "answer_generation_latency_ms": payload[
                        "answer_generation_latency_ms"
                    ],
                    "cloud_latency_ms": payload["cloud_latency_ms"],
                    "execution_status": payload["execution_status"],
                }
            )
        total = len(results)
        return {
            "total_cases": total,
            "correct_cases": correct_count,
            "accuracy": round(correct_count / total, 4) if total else None,
            "results": results,
        }

    return app


app = create_app()
