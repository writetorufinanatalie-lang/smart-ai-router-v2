"""FastAPI application exposing routing, metrics, health, and evaluation APIs."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import ollama
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from backend.classifier import (
    DEFAULT_MODEL,
    LOCAL_OLLAMA_HOST,
    ClassificationError,
    RequestCategory,
)
from backend.cloud_adapter import CloudAdapter
from backend.evaluation_jobs import (
    EVALUATION_SUITES,
    EvaluationJobManager,
    EvaluationRunBusy,
    load_report,
)
from backend.metrics_store import MetricsStore
from backend.router import FinalRoute, RoutingResponse, SmartRouter


DEFAULT_METRICS_PATH = Path(__file__).resolve().parent.parent / "data" / "metrics.db"
DEFAULT_EVALUATION_RESULTS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "test_lab_results.json"
)
DEFAULT_DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
DEFAULT_FRONTEND_DIRECTORY = Path(__file__).resolve().parent.parent / "frontend"
DEFAULT_EVALUATION_RUNS_DIRECTORY = DEFAULT_DATA_DIRECTORY / "evaluation_runs"
EVALUATION_REPORTS = {
    "original_38": ("Original set (38 queries)", "test_lab_results.json"),
    "held_out_15": ("Held-out set (15 queries)", "held_out_test_lab_results.json"),
    "generalization_18": (
        "Generalization set (18 queries)",
        "generalization_test_lab_results.json",
    ),
}


class RouteRequest(BaseModel):
    request_text: str = Field(min_length=1, max_length=10_000)


class EvaluationCase(BaseModel):
    request_text: str = Field(min_length=1, max_length=10_000)
    expected_label: RequestCategory
    expected_final_route: FinalRoute | None = None


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)


class EvaluationRunRequest(BaseModel):
    suite_id: str = Field(min_length=1, max_length=64)


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
    evaluation_results_path: str | Path | None = None,
    evaluation_report_paths: dict[str, str | Path] | None = None,
    evaluation_runs_directory: str | Path | None = None,
    evaluation_job_manager: EvaluationJobManager | None = None,
    frontend_directory: str | Path | None = None,
) -> FastAPI:
    adapter = cloud_adapter or getattr(router, "_cloud_adapter", None) or CloudAdapter()
    request_router = router or SmartRouter(cloud_adapter=adapter)
    store = metrics_store or MetricsStore(database_path or DEFAULT_METRICS_PATH)
    health_check = ollama_health_check or _probe_ollama
    results_path = Path(evaluation_results_path or DEFAULT_EVALUATION_RESULTS_PATH)
    report_paths = {
        suite_id: Path(
            (evaluation_report_paths or {}).get(
                suite_id,
                DEFAULT_DATA_DIRECTORY / filename,
            )
        )
        for suite_id, (_label, filename) in EVALUATION_REPORTS.items()
    }
    runs_directory = Path(evaluation_runs_directory or DEFAULT_EVALUATION_RUNS_DIRECTORY)
    job_manager = evaluation_job_manager or EvaluationJobManager(
        output_directory=runs_directory,
        metrics_store=store,
    )
    frontend_path = Path(frontend_directory or DEFAULT_FRONTEND_DIRECTORY)

    app = FastAPI(title="Smart AI Router", version="0.1.0")
    app.state.router = request_router
    app.state.metrics_store = store
    app.state.cloud_adapter = adapter
    app.state.evaluation_results_path = results_path
    app.state.evaluation_report_paths = report_paths
    app.state.evaluation_runs_directory = runs_directory
    app.state.evaluation_job_manager = job_manager
    app.state.frontend_directory = frontend_path

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

    @app.get("/history")
    def get_history(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
        return {"items": store.history(limit=limit)}

    @app.get("/activity")
    def get_activity(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        first_day = today - timedelta(days=days - 1)
        observed = {
            item["date"]: item
            for item in store.daily_activity(start_date=first_day.isoformat())
        }
        activity = []
        for offset in range(days):
            day = (first_day + timedelta(days=offset)).isoformat()
            activity.append(
                observed.get(
                    day,
                    {"date": day, "total_requests": 0, "route_counts": {}},
                )
            )
        return {"days": activity}

    @app.get("/devices")
    def get_devices() -> dict[str, Any]:
        return {
            "status": "simulated, in-memory, resets on server restart",
            "devices": request_router.simulated_device_snapshot(),
        }

    @app.get("/evaluation-results")
    def get_evaluation_results() -> dict[str, Any]:
        if not results_path.is_file():
            return {"available": False, "run_status": "not_run", "results": []}
        return json.loads(results_path.read_text(encoding="utf-8"))

    @app.get("/evaluation-reports")
    def get_evaluation_reports() -> dict[str, Any]:
        fixed_sets = []
        for suite_id, (label, _filename) in EVALUATION_REPORTS.items():
            report = load_report(report_paths[suite_id])
            fixed_sets.append(
                {
                    "suite_id": suite_id,
                    "label": label,
                    "available": report is not None,
                    "report": report,
                }
            )

        timestamped_runs = []
        if runs_directory.is_dir():
            for path in sorted(runs_directory.glob("*.json"), reverse=True):
                report = load_report(path)
                if report is None:
                    continue
                suite_id = report.get("suite_id")
                suite = EVALUATION_SUITES.get(suite_id)
                timestamped_runs.append(
                    {
                        "file": path.name,
                        "suite_id": suite_id,
                        "label": suite["label"] if suite else "Evaluation run",
                        "report": report,
                    }
                )
        return {
            "note": "Each evaluation is a small snapshot; results are not combined.",
            "sets": fixed_sets,
            "timestamped_runs": timestamped_runs,
        }

    @app.post("/evaluation-runs", status_code=202)
    def start_evaluation_run(body: EvaluationRunRequest) -> dict[str, Any]:
        suite_id = body.suite_id
        if suite_id not in EVALUATION_SUITES:
            raise HTTPException(status_code=422, detail="Unknown evaluation suite.")
        try:
            return job_manager.start(suite_id)
        except EvaluationRunBusy as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": str(error),
                    "active_run_id": error.active_run_id,
                },
            ) from error

    @app.get("/evaluation-runs/{run_id}")
    def get_evaluation_run(run_id: str) -> dict[str, Any]:
        job = job_manager.get(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Evaluation run not found.")
        return job

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
        route_correct_count = 0
        route_expected_count = 0
        for index, case in enumerate(body.cases, start=1):
            payload, is_correct = route_and_record(
                case.request_text,
                request_kind="evaluation",
                expected_label=case.expected_label,
            )
            correct = bool(is_correct)
            correct_count += int(correct)
            expected_route = case.expected_final_route.value if case.expected_final_route else None
            route_correct = (
                payload["final_route"] == expected_route
                if expected_route is not None
                else None
            )
            if route_correct is not None:
                route_expected_count += 1
                route_correct_count += int(route_correct)
            results.append(
                {
                    "case": index,
                    "expected_label": case.expected_label.value,
                    "expected_final_route": expected_route,
                    "classifier_label": payload["classifier_label"],
                    "final_route": payload["final_route"],
                    "correct": correct,
                    "route_correct": route_correct,
                    "classification_latency_ms": payload["classification_latency_ms"],
                    "answer_generation_latency_ms": payload[
                        "answer_generation_latency_ms"
                    ],
                    "cloud_latency_ms": payload["cloud_latency_ms"],
                    "rule_parser_overrode_classifier": payload[
                        "rule_parser_overrode_classifier"
                    ],
                    "privacy_blocked": payload["privacy_blocked"],
                    "sensitive_data_types": payload["sensitive_data_types"],
                    "execution_status": payload["execution_status"],
                }
            )
        total = len(results)
        return {
            "total_cases": total,
            "correct_cases": correct_count,
            "accuracy": round(correct_count / total, 4) if total else None,
            "route_expected_cases": route_expected_count,
            "route_correct_cases": route_correct_count,
            "route_accuracy": (
                round(route_correct_count / route_expected_count, 4)
                if route_expected_count
                else None
            ),
            "results": results,
        }

    app.mount(
        "/",
        StaticFiles(directory=frontend_path, html=True),
        name="frontend",
    )
    return app


app = create_app()
