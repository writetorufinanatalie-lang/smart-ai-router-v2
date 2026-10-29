"""Tests for evaluation-set coverage and report calculation/privacy boundaries."""

from backend.classifier import RequestCategory
from backend.privacy_shield import PrivacyShield
from backend.router import FinalRoute, RoutingResponse
from scripts.run_evaluation import build_case_result, load_cases, summarize_results


def test_evaluation_set_has_at_least_25_cases_and_required_coverage():
    cases = load_cases()

    assert len(cases) >= 25
    assert {case["expected_category"] for case in cases} == {
        "SIMPLE",
        "COMPLEX",
        "COMMAND",
    }
    assert {case["expected_final_route"] for case in cases} >= {
        "LOCAL",
        "CLOUD",
        "COMMAND",
        "COMMAND_UNSUPPORTED",
        "CLARIFICATION",
    }
    assert any("brightness to 40 percent" in case["request_text"] for case in cases)
    assert any("bedroom light" in case["request_text"] for case in cases)
    assert any(case["expected_final_route"] == "CLARIFICATION" for case in cases)

    detected_types = set()
    shield = PrivacyShield()
    for case in cases:
        detected_types.update(shield.inspect(case["request_text"]).detected_types)
    assert detected_types >= {"email", "phone_number", "card_like_number"}


def test_m3_has_command_expectation_even_when_classifier_may_mislabel_it():
    case = next(case for case in load_cases() if case["case_id"] == "command_03_brightness_40_m3")

    assert case["expected_category"] == RequestCategory.COMMAND.value
    assert case["expected_final_route"] == FinalRoute.COMMAND.value


def test_result_row_excludes_request_and_answer_text():
    private_request = "Write a report about person@example.com"
    case = {
        "case_id": "privacy_case",
        "request_text": private_request,
        "expected_category": "COMPLEX",
        "expected_final_route": "CLOUD",
    }
    response = RoutingResponse(
        classifier_label=RequestCategory.COMPLEX,
        final_route=FinalRoute.CLOUD,
        rule_parser_overrode_classifier=False,
        command_parser_matched=False,
        classification_reason="test only",
        classification_reason_source="model",
        classification_latency_ms=23.0,
        execution_status="blocked_by_privacy_shield",
        answer="private generated answer",
        cloud_latency_ms=None,
        privacy_blocked=True,
        sensitive_data_types=("email",),
    )

    row = build_case_result(case, response=response)

    assert row["case_id"] == "privacy_case"
    assert row["privacy_blocked"] is True
    assert row["sensitive_data_types"] == ["email"]
    assert private_request not in repr(row)
    assert "private generated answer" not in repr(row)


def test_summary_calculates_accuracy_precision_recall_confusion_and_latency():
    rows = [
        {
            "case_id": "one",
            "expected_category": "SIMPLE",
            "predicted_category": "SIMPLE",
            "expected_final_route": "LOCAL",
            "actual_final_route": "LOCAL",
            "classification_correct": True,
            "route_correct": True,
            "classification_latency_ms": 10.0,
            "answer_latency_ms": 2.0,
            "cloud_latency_ms": None,
            "rule_parser_overrode_classifier": False,
            "privacy_blocked": False,
            "sensitive_data_types": [],
        },
        {
            "case_id": "two",
            "expected_category": "COMPLEX",
            "predicted_category": "SIMPLE",
            "expected_final_route": "CLOUD",
            "actual_final_route": "LOCAL",
            "classification_correct": False,
            "route_correct": False,
            "classification_latency_ms": 20.0,
            "answer_latency_ms": None,
            "cloud_latency_ms": None,
            "rule_parser_overrode_classifier": False,
            "privacy_blocked": False,
            "sensitive_data_types": [],
        },
    ]

    summary = summarize_results(rows, total_cases=2)

    assert summary["classification_accuracy"] == 0.5
    assert summary["route_accuracy"] == 0.5
    assert summary["per_category_precision_recall"]["SIMPLE"] == {
        "precision": 0.5,
        "recall": 1.0,
        "support": 1,
        "predicted": 2,
        "true_positives": 1,
    }
    assert summary["confusion_matrix"]["rows"]["COMPLEX"]["SIMPLE"] == 1
    assert summary["latency_ms"]["classification"] == {
        "samples": 2,
        "mean_ms": 15.0,
        "median_ms": 15.0,
        "max_ms": 20.0,
    }
    assert summary["latency_ms"]["answer_generation"]["samples"] == 1


def test_clarification_outcomes_have_separate_count_and_never_count_as_correct_route():
    row = {
        "case_id": "clarify-one",
        "expected_category": "COMPLEX",
        "predicted_category": "COMMAND",
        "expected_final_route": "CLARIFICATION_NEEDED",
        "actual_final_route": "CLARIFICATION_NEEDED",
        "classification_correct": False,
        "route_correct": True,
        "classification_latency_ms": 10.0,
        "answer_latency_ms": None,
        "cloud_latency_ms": None,
        "rule_parser_overrode_classifier": False,
        "privacy_blocked": False,
        "sensitive_data_types": [],
    }

    summary = summarize_results([row], total_cases=1)

    assert summary["clarification_outcomes"] == 1
    assert summary["route_correct"] == 0
    assert summary["route_accuracy"] == 0.0
