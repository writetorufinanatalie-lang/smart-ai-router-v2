"""SQLite persistence for routing metadata and measured stage timings."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class MetricsRecord:
    request_kind: str
    classifier_label: str | None
    final_route: str
    execution_status: str
    classification_time_ms: float | None
    answer_time_ms: float | None
    cloud_time_ms: float | None
    rule_parser_overrode_classifier: bool
    privacy_blocked: bool
    sensitive_data_types: tuple[str, ...]
    request_sent_to_cloud: bool
    external_llm_api_used: bool
    expected_label: str | None = None
    evaluation_correct: bool | None = None


class MetricsStore:
    """Persist only non-content metadata; never persist prompts, answers, or keys."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS request_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    request_kind TEXT NOT NULL,
                    classifier_label TEXT,
                    final_route TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    classification_time_ms REAL,
                    answer_time_ms REAL,
                    cloud_time_ms REAL,
                    rule_parser_overrode_classifier INTEGER NOT NULL,
                    privacy_blocked INTEGER NOT NULL,
                    sensitive_data_types TEXT NOT NULL,
                    request_sent_to_cloud INTEGER NOT NULL,
                    external_llm_api_used INTEGER NOT NULL,
                    expected_label TEXT,
                    evaluation_correct INTEGER
                )
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record(self, record: MetricsRecord) -> None:
        """Insert one metadata-only row; request and answer text are not accepted."""

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO request_metrics (
                    created_at, request_kind, classifier_label, final_route,
                    execution_status, classification_time_ms, answer_time_ms,
                    cloud_time_ms, rule_parser_overrode_classifier, privacy_blocked,
                    sensitive_data_types, request_sent_to_cloud,
                    external_llm_api_used, expected_label, evaluation_correct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    record.request_kind,
                    record.classifier_label,
                    record.final_route,
                    record.execution_status,
                    record.classification_time_ms,
                    record.answer_time_ms,
                    record.cloud_time_ms,
                    int(record.rule_parser_overrode_classifier),
                    int(record.privacy_blocked),
                    json.dumps(list(record.sensitive_data_types)),
                    int(record.request_sent_to_cloud),
                    int(record.external_llm_api_used),
                    record.expected_label,
                    None if record.evaluation_correct is None else int(record.evaluation_correct),
                ),
            )

    def record_response(
        self,
        response: object,
        *,
        request_kind: str = "route",
        expected_label: str | None = None,
        evaluation_correct: bool | None = None,
    ) -> None:
        """Persist safe fields from a routing response, excluding text fields."""

        classifier_label = getattr(response, "classifier_label", None)
        final_route = getattr(response, "final_route")
        self.record(
            MetricsRecord(
                request_kind=request_kind,
                classifier_label=(
                    classifier_label.value if classifier_label is not None else None
                ),
                final_route=final_route.value,
                execution_status=getattr(response, "execution_status"),
                classification_time_ms=getattr(response, "classification_latency_ms", None),
                answer_time_ms=getattr(response, "answer_generation_latency_ms", None),
                cloud_time_ms=getattr(response, "cloud_latency_ms", None),
                rule_parser_overrode_classifier=getattr(
                    response, "rule_parser_overrode_classifier", False
                ),
                privacy_blocked=getattr(response, "privacy_blocked", False),
                sensitive_data_types=tuple(
                    getattr(response, "sensitive_data_types", ())
                ),
                request_sent_to_cloud=getattr(response, "request_sent_to_cloud", False),
                external_llm_api_used=getattr(response, "external_llm_api_used", False),
                expected_label=expected_label,
                evaluation_correct=evaluation_correct,
            )
        )

    def record_classification_failure(
        self,
        *,
        classification_time_ms: float | None,
        request_kind: str = "route",
        expected_label: str | None = None,
    ) -> None:
        """Record a failed classification without retaining input or error text."""

        self.record(
            MetricsRecord(
                request_kind=request_kind,
                classifier_label=None,
                final_route="ERROR",
                execution_status="classification_failed",
                classification_time_ms=classification_time_ms,
                answer_time_ms=None,
                cloud_time_ms=None,
                rule_parser_overrode_classifier=False,
                privacy_blocked=False,
                sensitive_data_types=(),
                request_sent_to_cloud=False,
                external_llm_api_used=False,
                expected_label=expected_label,
                evaluation_correct=False if expected_label is not None else None,
            )
        )

    def ping(self) -> bool:
        try:
            with self._connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def stats(self) -> dict[str, object]:
        """Calculate all analytics from persisted request_metrics rows."""

        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            totals = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_requests,
                    SUM(CASE WHEN request_kind = 'route' THEN 1 ELSE 0 END) AS route_requests,
                    SUM(CASE WHEN request_kind = 'evaluation' THEN 1 ELSE 0 END) AS evaluation_cases,
                    SUM(CASE WHEN execution_status IN ('completed_locally', 'executed_locally')
                        THEN 1 ELSE 0 END) AS handled_locally,
                    SUM(CASE WHEN final_route = 'CLOUD' THEN 1 ELSE 0 END) AS cloud_routes,
                    SUM(request_sent_to_cloud) AS cloud_requests_sent,
                    SUM(external_llm_api_used) AS external_api_uses,
                    SUM(rule_parser_overrode_classifier) AS rule_parser_overrides,
                    SUM(privacy_blocked) AS privacy_shield_blocks,
                    COUNT(classification_time_ms) AS classification_samples,
                    AVG(classification_time_ms) AS average_classification_time_ms,
                    COUNT(answer_time_ms) AS answer_samples,
                    AVG(answer_time_ms) AS average_answer_time_ms,
                    COUNT(cloud_time_ms) AS cloud_timing_samples,
                    AVG(cloud_time_ms) AS average_cloud_time_ms,
                    SUM(CASE WHEN expected_label IS NOT NULL THEN 1 ELSE 0 END)
                        AS evaluated_cases,
                    SUM(CASE WHEN evaluation_correct = 1 THEN 1 ELSE 0 END)
                        AS correct_evaluations
                FROM request_metrics
                """
            ).fetchone()
            route_counts = connection.execute(
                "SELECT final_route, COUNT(*) AS count FROM request_metrics GROUP BY final_route"
            ).fetchall()
            label_counts = connection.execute(
                """SELECT classifier_label, COUNT(*) AS count FROM request_metrics
                   WHERE classifier_label IS NOT NULL GROUP BY classifier_label"""
            ).fetchall()
            status_counts = connection.execute(
                """SELECT execution_status, COUNT(*) AS count FROM request_metrics
                   GROUP BY execution_status"""
            ).fetchall()

        evaluated_cases = int(totals["evaluated_cases"] or 0)
        correct_evaluations = int(totals["correct_evaluations"] or 0)
        accuracy = (
            round(correct_evaluations / evaluated_cases, 4)
            if evaluated_cases
            else None
        )

        def average(column: str) -> float | None:
            value = totals[column]
            return round(float(value), 2) if value is not None else None

        return {
            "total_requests": int(totals["total_requests"] or 0),
            "route_requests": int(totals["route_requests"] or 0),
            "evaluation_cases": int(totals["evaluation_cases"] or 0),
            "requests_handled_locally": int(totals["handled_locally"] or 0),
            "cloud_routes": int(totals["cloud_routes"] or 0),
            "cloud_requests_sent": int(totals["cloud_requests_sent"] or 0),
            "external_api_uses": int(totals["external_api_uses"] or 0),
            "rule_parser_overrides": int(totals["rule_parser_overrides"] or 0),
            "privacy_shield_blocks": int(totals["privacy_shield_blocks"] or 0),
            "route_counts": {row["final_route"]: int(row["count"]) for row in route_counts},
            "classifier_label_counts": {
                row["classifier_label"]: int(row["count"]) for row in label_counts
            },
            "execution_status_counts": {
                row["execution_status"]: int(row["count"]) for row in status_counts
            },
            "classification_timing_samples": int(totals["classification_samples"] or 0),
            "average_classification_time_ms": average("average_classification_time_ms"),
            "answer_timing_samples": int(totals["answer_samples"] or 0),
            "average_answer_time_ms": average("average_answer_time_ms"),
            "cloud_timing_samples": int(totals["cloud_timing_samples"] or 0),
            "average_cloud_time_ms": average("average_cloud_time_ms"),
            "evaluation": {
                "cases": evaluated_cases,
                "correct": correct_evaluations,
                "accuracy": accuracy,
            },
        }
