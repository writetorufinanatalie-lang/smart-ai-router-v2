"""Tests for durable, metadata-only SQLite metrics."""

import sqlite3

from backend.metrics_store import MetricsRecord, MetricsStore


def record(**overrides):
    values = {
        "request_kind": "route",
        "classifier_label": "SIMPLE",
        "final_route": "LOCAL",
        "execution_status": "completed_locally",
        "classification_time_ms": 20.0,
        "answer_time_ms": 100.0,
        "cloud_time_ms": None,
        "rule_parser_overrode_classifier": False,
        "privacy_blocked": False,
        "sensitive_data_types": (),
        "request_sent_to_cloud": False,
        "external_llm_api_used": False,
    }
    values.update(overrides)
    return MetricsRecord(**values)


def test_empty_stats_are_computed_from_an_empty_database(tmp_path):
    store = MetricsStore(tmp_path / "metrics.db")

    stats = store.stats()

    assert stats["total_requests"] == 0
    assert stats["route_requests"] == 0
    assert stats["average_classification_time_ms"] is None
    assert stats["average_answer_time_ms"] is None
    assert stats["average_cloud_time_ms"] is None
    assert stats["evaluation"] == {"cases": 0, "correct": 0, "accuracy": None}
    assert store.ping() is True


def test_stats_aggregate_stage_timings_and_routes_from_stored_rows(tmp_path):
    store = MetricsStore(tmp_path / "metrics.db")
    store.record(record())
    store.record(
        record(
            classifier_label="COMPLEX",
            final_route="CLOUD",
            execution_status="blocked_by_privacy_shield",
            classification_time_ms=30.0,
            answer_time_ms=None,
            cloud_time_ms=125.0,
            privacy_blocked=True,
            sensitive_data_types=("email",),
        )
    )
    store.record(
        record(
            request_kind="evaluation",
            classifier_label="COMMAND",
            final_route="COMMAND",
            execution_status="executed_locally",
            classification_time_ms=40.0,
            answer_time_ms=None,
            expected_label="COMMAND",
            evaluation_correct=True,
            rule_parser_overrode_classifier=True,
        )
    )

    stats = store.stats()

    assert stats["total_requests"] == 2
    assert stats["normal_user_requests"] == 2
    assert stats["route_requests"] == 2
    assert stats["evaluation_cases"] == 1
    assert stats["requests_handled_locally"] == 1
    assert stats["cloud_routes"] == 1
    assert stats["cloud_requests_sent"] == 0
    assert stats["rule_parser_overrides"] == 0
    assert stats["privacy_shield_blocks"] == 1
    assert stats["route_counts"] == {"CLOUD": 1, "LOCAL": 1}
    assert stats["classifier_label_counts"] == {
        "COMPLEX": 1,
        "SIMPLE": 1,
    }
    assert stats["average_classification_time_ms"] == 25.0
    assert stats["median_classification_time_ms"] == 25.0
    assert stats["classification_timing_samples"] == 2
    assert stats["average_answer_time_ms"] == 100.0
    assert stats["median_answer_time_ms"] == 100.0
    assert stats["answer_timing_samples"] == 1
    assert stats["average_cloud_time_ms"] == 125.0
    assert stats["median_cloud_time_ms"] == 125.0
    assert stats["cloud_timing_samples"] == 1
    assert stats["evaluation"] == {"cases": 1, "correct": 1, "accuracy": 1.0}
    assert stats["evaluation_latency_ms"]["classification"] == {
        "samples": 1,
        "mean_ms": 40.0,
        "median_ms": 40.0,
    }


def test_database_schema_and_rows_do_not_store_prompts_answers_or_api_keys(tmp_path):
    database_path = tmp_path / "metrics.db"
    store = MetricsStore(database_path)
    prompt_secret = "private-user@example.com"
    answer_secret = "private generated answer"
    api_key_secret = "sk-test-secret-never-persist"
    store.record(record(sensitive_data_types=("email",)))

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(request_metrics)")
        }
        rows = connection.execute("SELECT * FROM request_metrics").fetchall()

    assert "request_text" not in columns
    assert "answer" not in columns
    assert "api_key" not in columns
    assert prompt_secret not in repr(rows)
    assert answer_secret not in repr(rows)
    assert api_key_secret not in repr(rows)
    assert "email" in repr(rows)


def test_record_classification_failure_keeps_error_timing_without_error_text(tmp_path):
    store = MetricsStore(tmp_path / "metrics.db")

    store.record_classification_failure(
        classification_time_ms=15.5,
        request_kind="evaluation",
        expected_label="SIMPLE",
    )
    stats = store.stats()

    assert stats["route_counts"] == {}
    assert stats["average_classification_time_ms"] is None
    assert stats["evaluation"] == {"cases": 1, "correct": 0, "accuracy": 0.0}


def test_history_and_activity_exclude_evaluation_rows_and_never_include_text(tmp_path):
    store = MetricsStore(tmp_path / "metrics.db")
    store.record(record())
    store.record(
        record(
            request_kind="evaluation",
            expected_label="SIMPLE",
            evaluation_correct=True,
            classifier_label="SIMPLE",
        )
    )

    history = store.history()
    activity = store.daily_activity(start_date="2000-01-01")

    assert len(history) == 1
    assert "request_text" not in history[0]
    assert len(activity) == 1
    assert activity[0]["total_requests"] == 1
