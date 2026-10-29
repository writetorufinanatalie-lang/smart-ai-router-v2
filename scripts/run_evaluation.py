"""Run the fixed evaluation set against the real local SmartRouter."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable
from uuid import uuid4

from backend.classifier import DEFAULT_MODEL, ClassificationError, RequestCategory
from backend.main import DEFAULT_METRICS_PATH
from backend.metrics_store import MetricsStore
from backend.router import RoutingResponse, SmartRouter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = PROJECT_ROOT / "tests" / "evaluation_cases.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "test_lab_results.json"
CATEGORIES = [category.value for category in RequestCategory]
CONFUSION_LABELS = [*CATEGORIES, "ERROR"]
EXPECTED_ROUTES = {
    "LOCAL",
    "CLOUD",
    "COMMAND",
    "COMMAND_UNSUPPORTED",
    "CLARIFICATION",
}


def load_cases(path: str | Path = DEFAULT_CASES_PATH) -> list[dict[str, str]]:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("The evaluation file must contain a non-empty list of cases.")

    seen_ids: set[str] = set()
    for case in cases:
        required = {
            "case_id",
            "request_text",
            "expected_category",
            "expected_final_route",
        }
        if not isinstance(case, dict) or not required.issubset(case):
            raise ValueError("Each evaluation case needs an id, request, category, and route.")
        if not case["case_id"] or case["case_id"] in seen_ids:
            raise ValueError("Evaluation case ids must be non-empty and unique.")
        seen_ids.add(case["case_id"])
        if case["expected_category"] not in CATEGORIES:
            raise ValueError(f"Unsupported expected category in case {case['case_id']}.")
        if case["expected_final_route"] not in EXPECTED_ROUTES:
            raise ValueError(f"Unsupported expected route in case {case['case_id']}.")
        if not isinstance(case["request_text"], str) or not case["request_text"].strip():
            raise ValueError(f"Case {case['case_id']} has an empty request.")
    return cases


def build_case_result(
    case: dict[str, str],
    *,
    response: RoutingResponse | None = None,
    error: ClassificationError | None = None,
) -> dict[str, Any]:
    """Return only safe report fields; never copy request, answer, or reason text."""

    if response is None:
        return {
            "case_id": case["case_id"],
            "expected_category": case["expected_category"],
            "predicted_category": None,
            "expected_final_route": case["expected_final_route"],
            "actual_final_route": "ERROR",
            "classification_correct": False,
            "route_correct": False,
            "classification_latency_ms": error.latency_ms if error else None,
            "answer_latency_ms": None,
            "cloud_latency_ms": None,
            "rule_parser_overrode_classifier": False,
            "privacy_blocked": False,
            "sensitive_data_types": [],
            "execution_status": "classification_failed",
        }

    predicted_category = response.classifier_label.value
    actual_route = response.final_route.value
    return {
        "case_id": case["case_id"],
        "expected_category": case["expected_category"],
        "predicted_category": predicted_category,
        "expected_final_route": case["expected_final_route"],
        "actual_final_route": actual_route,
        "classification_correct": predicted_category == case["expected_category"],
        "route_correct": actual_route == case["expected_final_route"],
        "classification_latency_ms": response.classification_latency_ms,
        "answer_latency_ms": response.answer_generation_latency_ms,
        "cloud_latency_ms": response.cloud_latency_ms,
        "rule_parser_overrode_classifier": response.rule_parser_overrode_classifier,
        "privacy_blocked": response.privacy_blocked,
        "sensitive_data_types": list(response.sensitive_data_types),
        "execution_status": response.execution_status,
    }


def _latency_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [row[field] for row in rows if row[field] is not None]
    if not values:
        return {"samples": 0, "mean_ms": None, "median_ms": None, "max_ms": None}
    return {
        "samples": len(values),
        "mean_ms": round(mean(values), 2),
        "median_ms": round(median(values), 2),
        "max_ms": round(max(values), 2),
    }


def summarize_results(rows: list[dict[str, Any]], total_cases: int) -> dict[str, Any]:
    correct = sum(row["classification_correct"] for row in rows)
    route_correct = sum(row["route_correct"] for row in rows)
    processed = len(rows)
    category_metrics = {}
    for category in CATEGORIES:
        true_positive = sum(
            row["expected_category"] == category
            and row["predicted_category"] == category
            for row in rows
        )
        support = sum(row["expected_category"] == category for row in rows)
        predicted = sum(row["predicted_category"] == category for row in rows)
        category_metrics[category] = {
            "precision": round(true_positive / predicted, 4) if predicted else None,
            "recall": round(true_positive / support, 4) if support else None,
            "support": support,
            "predicted": predicted,
            "true_positives": true_positive,
        }

    matrix = {category: {label: 0 for label in CONFUSION_LABELS} for category in CATEGORIES}
    for row in rows:
        predicted = row["predicted_category"] or "ERROR"
        matrix[row["expected_category"]][predicted] += 1

    return {
        "cases_completed": processed,
        "cases_in_set": total_cases,
        "classification_accuracy": round(correct / processed, 4) if processed else None,
        "classification_correct": correct,
        "route_accuracy": round(route_correct / processed, 4) if processed else None,
        "route_correct": route_correct,
        "clarification_outcomes": sum(
            row["actual_final_route"] == "CLARIFICATION" for row in rows
        ),
        "per_category_precision_recall": category_metrics,
        "confusion_matrix": {"labels": CONFUSION_LABELS, "rows": matrix},
        "latency_ms": {
            "classification": _latency_summary(rows, "classification_latency_ms"),
            "answer_generation": _latency_summary(rows, "answer_latency_ms"),
            "cloud": _latency_summary(rows, "cloud_latency_ms"),
        },
        "rule_parser_overrides": [
            {
                "case_id": row["case_id"],
                "classifier_label": row["predicted_category"],
                "final_route": row["actual_final_route"],
            }
            for row in rows
            if row["rule_parser_overrode_classifier"]
        ],
        "privacy_shield_blocks": [
            {
                "case_id": row["case_id"],
                "sensitive_data_types": row["sensitive_data_types"],
            }
            for row in rows
            if row["privacy_blocked"]
        ],
        "classification_errors": sum(row["predicted_category"] is None for row in rows),
        "external_cloud_requests": sum(
            row["cloud_latency_ms"] is not None for row in rows
        ),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def run_evaluation(
    *,
    cases_path: str | Path = DEFAULT_CASES_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    suite_id: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    metrics_store: MetricsStore | None = None,
) -> dict[str, Any]:
    """Run each case through the real local router and save actual run metadata."""

    cases = load_cases(cases_path)
    router = SmartRouter()
    metrics = metrics_store or MetricsStore(DEFAULT_METRICS_PATH)
    report_path = Path(output_path)
    run_id = uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    def report(status: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": run_id,
            "suite_id": suite_id,
            "run_status": status,
            "data_source": "real_local_classifier_and_router_runs",
            "model": DEFAULT_MODEL,
            "classification_location": "local",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat()
            if status != "in_progress"
            else None,
            "summary": summarize_results(rows, len(cases)),
            "results": rows,
        }

    _write_report(report_path, report("in_progress"))
    for index, case in enumerate(cases, start=1):
        try:
            response = router.route(case["request_text"])
        except ClassificationError as error:
            row = build_case_result(case, error=error)
            metrics.record_classification_failure(
                classification_time_ms=error.latency_ms,
                request_kind="evaluation",
                expected_label=case["expected_category"],
            )
        else:
            row = build_case_result(case, response=response)
            metrics.record_response(
                response,
                request_kind="evaluation",
                expected_label=case["expected_category"],
                evaluation_correct=row["classification_correct"],
            )
        rows.append(row)
        _write_report(report_path, report("in_progress"))
        if progress_callback is not None:
            progress_callback(
                {
                    "completed_cases": len(rows),
                    "current_case_id": case["case_id"],
                    "latest_result": row,
                    "summary": summarize_results(rows, len(cases)),
                }
            )
        print(
            f"[{index}/{len(cases)}] {case['case_id']}: "
            f"{row['predicted_category'] or 'ERROR'} -> {row['actual_final_route']}",
            file=sys.stderr,
        )

    errors = sum(row["predicted_category"] is None for row in rows)
    final_report = report(
        "completed_with_classification_errors" if errors else "completed"
    )
    _write_report(report_path, final_report)
    print(json.dumps(final_report["summary"], indent=2))
    return final_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the fixed evaluation set against local Qwen and the real router."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    arguments = parser.parse_args()
    run_evaluation(cases_path=arguments.cases, output_path=arguments.output)


if __name__ == "__main__":
    main()
