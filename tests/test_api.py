"""Integration tests for FastAPI endpoints and SQLite metrics persistence."""

from fastapi.testclient import TestClient

from backend.classifier import ClassificationError, ClassificationResult, RequestCategory
from backend.cloud_adapter import CLOUD_FAILURE_MESSAGE, CloudAdapter
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


def make_client(tmp_path, classifier, *, cloud_adapter=None, health_check=None):
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
    assert stats["average_answer_time_ms"] == 7.5
    assert stats["average_cloud_time_ms"] is None
    assert stats["route_counts"] == {"LOCAL": 1}


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
    assert body["results"][1]["classifier_label"] == "COMPLEX"
    assert body["results"][1]["correct"] is False
    assert "request_text" not in body["results"][0]

    stats = client.get("/stats").json()
    assert stats["evaluation_cases"] == 2
    assert stats["evaluation"] == {"cases": 2, "correct": 1, "accuracy": 0.5}
    assert stats["total_requests"] == 2


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
