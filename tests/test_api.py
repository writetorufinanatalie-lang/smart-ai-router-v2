"""Integration tests for FastAPI endpoints and SQLite metrics persistence."""

import json
import re
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.classifier import ClassificationError, ClassificationResult, RequestCategory
from backend.cloud_adapter import CLOUD_FAILURE_MESSAGE, CloudAdapter
from backend.evaluation_jobs import EvaluationJobManager
from backend.local_answer import LocalAnswerResult
from backend.main import create_app
from backend.router import SmartRouter


class FakeAnswerGenerator:
    def generate(self, _text):
        return LocalAnswerResult("Local test answer", "qwen2.5:1.5b", 7.5)


def make_classification(category, latency=12.0):
    return ClassificationResult(
        category=category,
        reason="test reason",
        model="test-model",
        latency_ms=latency,
    )


def make_client(
    tmp_path,
    classifier,
    *,
    cloud_adapter=None,
    health_check=None,
    evaluation_results_path=None,
    evaluation_report_paths=None,
    evaluation_runs_directory=None,
    evaluation_job_manager=None,
    frontend_directory=None,
):
    adapter = cloud_adapter or CloudAdapter(api_key="")
    probe = health_check or (
        lambda: {
            "status": "available",
            "service_available": True,
            "model": "qwen2.5:1.5b",
            "model_available": True,
        }
    )
    router = SmartRouter(
        classifier=classifier,
        local_answer_generator=FakeAnswerGenerator(),
        cloud_adapter=adapter,
    )
    app = create_app(
        database_path=tmp_path / "metrics.db",
        router=router,
        cloud_adapter=adapter,
        ollama_health_check=probe,
        evaluation_results_path=evaluation_results_path,
        evaluation_report_paths=evaluation_report_paths,
        evaluation_runs_directory=evaluation_runs_directory,
        evaluation_job_manager=evaluation_job_manager,
        frontend_directory=frontend_directory,
    )
    return TestClient(app), app


def test_post_route_returns_answer_and_persists_separate_real_timings(tmp_path):
    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE, latency=12.0),
    )

    response = client.post("/route", json={"request_text": "What is 2 + 2?"})

    assert response.status_code == 200
    body = response.json()
    assert body["classifier_label"] == "SIMPLE"
    assert body["final_route"] == "LOCAL"
    assert body["answer"] == "Local test answer"
    assert body["classification_latency_ms"] == 12.0
    assert body["answer_generation_latency_ms"] == 7.5
    assert body["cloud_latency_ms"] is None
    assert body["request_sent_to_cloud"] is False

    stats = client.get("/stats").json()
    assert stats["total_requests"] == 1
    assert stats["requests_handled_locally"] == 1
    assert stats["average_classification_time_ms"] == 12.0
    assert stats["median_classification_time_ms"] == 12.0
    assert stats["average_answer_time_ms"] == 7.5
    assert stats["median_answer_time_ms"] == 7.5
    assert stats["average_cloud_time_ms"] is None
    assert stats["route_counts"] == {"LOCAL": 1}


def test_command_label_without_parser_match_returns_and_records_clarification_route(tmp_path):
    secret_text = "Format the computer drive and retain this private request"
    client, app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.COMMAND),
    )

    response = client.post("/route", json={"request_text": secret_text})

    assert response.status_code == 200
    body = response.json()
    assert body["classifier_label"] == "COMMAND"
    assert body["final_route"] == "CLARIFICATION"
    assert body["execution_status"] == "clarification_needed"
    assert "clarify" in body["message"]
    assert body["command_parser_matched"] is False
    assert body["command_result"] is None
    assert secret_text not in response.text
    stats = client.get("/stats").json()
    assert stats["route_counts"] == {"CLARIFICATION": 1}

    database_bytes = app.state.metrics_store.path.read_bytes()
    assert secret_text.encode() not in database_bytes


def test_route_api_exposes_distinct_device_control_not_performed_status(tmp_path):
    client, app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
    )

    response = client.post("/route", json={"request_text": "Set brightness to 40"})

    assert response.status_code == 200
    body = response.json()
    assert body["final_route"] == "LOCAL"
    assert body["execution_status"] == "device_control_not_performed"
    assert body["message"].startswith("No device was controlled")
    assert app.state.metrics_store.stats()["execution_status_counts"] == {
        "device_control_not_performed": 1
    }


def test_cloud_time_is_stored_separately_only_when_sender_was_called(tmp_path):
    def failing_sender(_text, _key):
        raise OSError("test provider failure")

    adapter = CloudAdapter(api_key="test-key", sender=failing_sender)
    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.COMPLEX, latency=22.0),
        cloud_adapter=adapter,
    )

    response = client.post("/route", json={"request_text": "Write a long story"})

    assert response.status_code == 200
    body = response.json()
    assert body["classification_latency_ms"] == 22.0
    assert body["answer_generation_latency_ms"] is None
    assert body["cloud_latency_ms"] is not None
    assert body["request_sent_to_cloud"] is True
    stats = client.get("/stats").json()
    assert stats["classification_timing_samples"] == 1
    assert stats["answer_timing_samples"] == 0
    assert stats["cloud_timing_samples"] == 1
    assert stats["average_cloud_time_ms"] == body["cloud_latency_ms"]
    assert stats["median_cloud_time_ms"] == body["cloud_latency_ms"]


def test_stats_count_privacy_block_and_do_not_persist_sensitive_values_or_key(tmp_path):
    secret_email = "person.private@example.com"
    secret_api_key = "sk-test-key-must-not-be-stored"
    adapter = CloudAdapter(api_key=secret_api_key)
    client, app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.COMPLEX, latency=20.0),
        cloud_adapter=adapter,
    )

    response = client.post(
        "/route",
        json={"request_text": f"Summarize this note for {secret_email}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["privacy_blocked"] is True
    assert body["sensitive_data_types"] == ["email"]
    assert body["request_sent_to_cloud"] is False
    assert body["message"] == CLOUD_FAILURE_MESSAGE

    stats = client.get("/stats").json()
    assert stats["privacy_shield_blocks"] == 1
    assert stats["cloud_routes"] == 1
    assert stats["cloud_requests_sent"] == 0

    database_bytes = app.state.metrics_store.path.read_bytes()
    assert secret_email.encode() not in database_bytes
    assert secret_api_key.encode() not in database_bytes


def test_post_evaluate_records_cases_and_computes_accuracy_from_actual_labels(tmp_path):
    def classifier(text):
        category = RequestCategory.SIMPLE if text.startswith("simple") else RequestCategory.COMPLEX
        return make_classification(category, latency=5.0 if category is RequestCategory.SIMPLE else 9.0)

    client, _app = make_client(tmp_path, classifier)

    response = client.post(
        "/evaluate",
        json={
            "cases": [
                {"request_text": "simple: 2 + 2", "expected_label": "SIMPLE"},
                {"request_text": "complex: write a story", "expected_label": "SIMPLE"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_cases"] == 2
    assert body["correct_cases"] == 1
    assert body["accuracy"] == 0.5
    assert body["results"][0]["classifier_label"] == "SIMPLE"
    assert body["results"][0]["correct"] is True
    assert body["results"][0]["rule_parser_overrode_classifier"] is False
    assert body["results"][0]["privacy_blocked"] is False
    assert body["results"][0]["sensitive_data_types"] == []
    assert body["results"][1]["classifier_label"] == "COMPLEX"
    assert body["results"][1]["correct"] is False
    assert "request_text" not in body["results"][0]

    stats = client.get("/stats").json()
    assert stats["evaluation_cases"] == 2
    assert stats["evaluation"] == {"cases": 2, "correct": 1, "accuracy": 0.5}
    assert stats["total_requests"] == 0
    assert stats["normal_user_requests"] == 0
    assert stats["evaluation_cases"] == 2


def test_post_evaluate_reports_route_accuracy_separately_when_expected_route_is_supplied(tmp_path):
    classifier = lambda text: make_classification(
        RequestCategory.SIMPLE if text.startswith("simple") else RequestCategory.COMPLEX
    )
    client, _app = make_client(tmp_path, classifier)

    response = client.post(
        "/evaluate",
        json={
            "cases": [
                {
                    "request_text": "simple: arithmetic",
                    "expected_label": "SIMPLE",
                    "expected_final_route": "LOCAL",
                },
                {
                    "request_text": "complex: outline a book",
                    "expected_label": "COMPLEX",
                    "expected_final_route": "LOCAL",
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["correct_cases"] == 2
    assert body["route_expected_cases"] == 2
    assert body["route_correct_cases"] == 1
    assert body["route_accuracy"] == 0.5
    assert body["results"][0]["route_correct"] is True
    assert body["results"][1]["route_correct"] is False


def test_health_reports_backend_ollama_and_cloud_configuration_without_secrets(tmp_path):
    secret_api_key = "sk-health-check-secret"
    adapter = CloudAdapter(api_key=secret_api_key)
    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
        cloud_adapter=adapter,
        health_check=lambda: {
            "status": "available",
            "service_available": True,
            "model": "qwen2.5:1.5b",
            "model_available": True,
        },
    )

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["backend"] == {"status": "ok", "metrics_store_available": True}
    assert body["ollama"]["service_available"] is True
    assert body["ollama"]["model_available"] is True
    assert body["cloud"] == {
        "status": "not_configured",
        "configured": False,
        "api_key_configured": True,
        "provider_configured": False,
    }
    assert secret_api_key not in response.text


def test_route_classification_failure_is_persisted_without_error_or_input_text(tmp_path):
    secret_text = "do not persist this private prompt"

    def failing_classifier(_text):
        raise ClassificationError("private failure detail", latency_ms=18.0)

    client, _app = make_client(tmp_path, failing_classifier)

    response = client.post("/route", json={"request_text": secret_text})

    assert response.status_code == 200
    assert response.json()["final_route"] == "ERROR"
    assert response.json()["classification_latency_ms"] == 18.0
    assert secret_text not in response.text
    stats = client.get("/stats").json()
    assert stats["route_counts"] == {"ERROR": 1}
    assert stats["average_classification_time_ms"] == 18.0


def test_evaluation_results_endpoint_serves_saved_test_lab_json(tmp_path):
    results_path = tmp_path / "test_lab_results.json"
    results_path.write_text(
        '{"run_status":"completed","results":[{"case_id":"simple_01"}]}',
        encoding="utf-8",
    )
    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
        evaluation_results_path=results_path,
    )

    response = client.get("/evaluation-results")

    assert response.status_code == 200
    assert response.json() == {
        "run_status": "completed",
        "results": [{"case_id": "simple_01"}],
    }


def test_evaluation_results_endpoint_reports_when_no_real_run_exists(tmp_path):
    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
        evaluation_results_path=tmp_path / "missing_results.json",
    )

    response = client.get("/evaluation-results")

    assert response.status_code == 200
    assert response.json() == {"available": False, "run_status": "not_run", "results": []}


def test_history_activity_and_device_status_are_real_and_separate(tmp_path):
    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
    )
    client.post("/route", json={"request_text": "What is 2 + 2?"})
    client.post(
        "/evaluate",
        json={"cases": [{"request_text": "simple: 1 + 1", "expected_label": "SIMPLE"}]},
    )

    history = client.get("/history").json()
    activity = client.get("/activity?days=3").json()
    devices = client.get("/devices").json()
    stats = client.get("/stats").json()

    assert len(history["items"]) == 1
    assert "request_text" not in history["items"][0]
    assert len(activity["days"]) == 3
    assert sum(day["total_requests"] for day in activity["days"]) == 1
    assert devices["status"] == "simulated, in-memory, resets on server restart"
    assert devices["devices"]["desk_light"] == {"on": False, "brightness": 50}
    assert stats["normal_user_requests"] == 1
    assert stats["evaluation_cases"] == 1
    assert stats["route_counts"] == {"LOCAL": 1}


def test_evaluation_reports_endpoint_returns_three_separate_named_sets(tmp_path):
    report_paths = {}
    for suite_id in ("original_38", "held_out_15", "generalization_18"):
        path = tmp_path / f"{suite_id}.json"
        path.write_text(
            json.dumps({"run_status": "completed", "summary": {"cases_completed": 1}}),
            encoding="utf-8",
        )
        report_paths[suite_id] = path
    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
        evaluation_report_paths=report_paths,
    )

    response = client.get("/evaluation-reports")

    assert response.status_code == 200
    body = response.json()
    assert [item["suite_id"] for item in body["sets"]] == [
        "original_38",
        "held_out_15",
        "generalization_18",
    ]
    assert all(item["available"] for item in body["sets"])
    assert "not combined" in body["note"]


def test_evaluation_job_runs_in_background_reports_progress_and_allows_one_run(tmp_path):
    entered_runner = threading.Event()
    finish_runner = threading.Event()
    private_query = "do not expose this evaluation input"
    safe_result = {
        "case_id": "case_1",
        "expected_category": "SIMPLE",
        "predicted_category": "SIMPLE",
        "expected_final_route": "LOCAL",
        "actual_final_route": "LOCAL",
        "classification_correct": True,
        "route_correct": True,
        "classification_latency_ms": 5.0,
        "answer_latency_ms": 2.0,
        "cloud_latency_ms": None,
        "rule_parser_overrode_classifier": False,
        "privacy_blocked": False,
        "sensitive_data_types": [],
        "execution_status": "completed_locally",
    }
    fake_summary = {
        "cases_completed": 1,
        "cases_in_set": 2,
        "classification_accuracy": 1.0,
        "route_accuracy": 1.0,
    }

    def runner(*, cases_path, output_path, suite_id, progress_callback):
        progress_callback(
            {
                "completed_cases": 1,
                "current_case_id": "case_1",
                "latest_result": safe_result,
                "summary": fake_summary,
            }
        )
        entered_runner.set()
        finish_runner.wait(timeout=3)
        report = {
            "suite_id": suite_id,
            "run_status": "completed",
            "finished_at": "2026-01-01T00:00:00+00:00",
            "summary": fake_summary,
            "results": [safe_result],
        }
        Path(output_path).write_text(json.dumps(report), encoding="utf-8")
        return report

    report_root = tmp_path / "data"
    report_root.mkdir()
    baseline_contents = {}
    for name in (
        "test_lab_results.json",
        "held_out_test_lab_results.json",
        "generalization_test_lab_results.json",
    ):
        baseline_path = report_root / name
        baseline_contents[name] = "baseline:" + name
        baseline_path.write_text(baseline_contents[name], encoding="utf-8")

    manager = EvaluationJobManager(
        output_directory=report_root / "evaluation_runs",
        runner=runner,
        cases_loader=lambda _path: [
            {"case_id": "case_1", "request_text": private_query},
            {"case_id": "case_2", "request_text": "another private query"},
        ],
    )
    client, app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
        evaluation_job_manager=manager,
    )

    started = client.post("/evaluation-runs", json={"suite_id": "original_38"})
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    assert entered_runner.wait(timeout=1)

    progress = client.get(f"/evaluation-runs/{run_id}")
    assert progress.status_code == 200
    assert progress.json()["completed_cases"] == 1
    assert progress.json()["total_cases"] == 2
    assert progress.json()["results"] == [safe_result]
    assert private_query not in progress.text

    rejected = client.post("/evaluation-runs", json={"suite_id": "held_out_15"})
    assert rejected.status_code == 409
    assert app.state.metrics_store.stats()["normal_user_requests"] == 0

    finish_runner.set()
    for _ in range(100):
        complete = client.get(f"/evaluation-runs/{run_id}").json()
        if complete["status"] == "completed":
            break
        time.sleep(0.01)
    assert complete["status"] == "completed"
    assert re.fullmatch(r"original_38_\d{8}T\d{6}_\d{6}Z\.json", complete["result_file"])
    output_path = report_root / "evaluation_runs" / complete["result_file"]
    assert output_path.is_file()
    assert private_query not in output_path.read_text(encoding="utf-8")
    for name, content in baseline_contents.items():
        assert (report_root / name).read_text(encoding="utf-8") == content


def test_frontend_static_mount_cannot_serve_project_siblings(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<h1>Router UI</h1>", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "test_lab_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "metrics.db").write_bytes(b"sqlite secret")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text("secret source", encoding="utf-8")

    client, _app = make_client(
        tmp_path,
        lambda _text: make_classification(RequestCategory.SIMPLE),
        frontend_directory=frontend,
    )

    assert client.get("/").status_code == 200
    assert client.get("/").text == "<h1>Router UI</h1>"
    for path in (
        "/.env",
        "/data/test_lab_results.json",
        "/data/metrics.db",
        "/backend/main.py",
        "/%2e%2e/.env",
    ):
        assert client.get(path).status_code == 404
