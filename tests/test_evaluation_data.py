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


def test_held_out_set_is_separate_and_has_fifteen_unseen_queries():
    from pathlib import Path

    import json

    project_root = Path(__file__).resolve().parents[1]
    main_cases = load_cases()
    held_out_cases = json.loads(
        (project_root / "tests" / "held_out_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(held_out_cases) == 15
    assert not ({case["case_id"] for case in main_cases} & {
        case["case_id"] for case in held_out_cases
    })
    assert {case["expected_category"] for case in held_out_cases} == {
        "SIMPLE",
        "COMPLEX",
        "COMMAND",
    }
    assert any("dimmer" in case["request_text"] for case in held_out_cases)
    assert any("Lights on please" in case["request_text"] for case in held_out_cases)
    assert any("Switch the fan off" in case["request_text"] for case in held_out_cases)


def test_new_generalization_set_is_separate_with_command_lookalikes():
    from pathlib import Path

    import json

    project_root = Path(__file__).resolve().parents[1]
    earlier_held_out = json.loads(
        (project_root / "tests" / "held_out_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )
    new_cases = json.loads(
        (project_root / "tests" / "generalization_evaluation_cases.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(new_cases) == 18
    assert not ({case["case_id"] for case in earlier_held_out} & {
        case["case_id"] for case in new_cases
    })
    assert sum(case["expected_category"] == "COMMAND" for case in new_cases) == 15
    assert sum(case["expected_category"] != "COMMAND" for case in new_cases) == 3


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


def test_ambiguous_clarification_counts_as_correct_when_expected():
    row = {
        "case_id": "clarify-one",
        "expected_category": "COMPLEX",
        "predicted_category": "COMMAND",
        "expected_final_route": "CLARIFICATION",
        "actual_final_route": "CLARIFICATION",
        "classification_correct": True,
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
    assert summary["route_correct"] == 1
    assert summary["route_accuracy"] == 1.0


def test_classifier_command_clarification_is_incorrect_when_cloud_was_expected():
    row = {
        "case_id": "misclassified-complex",
        "expected_category": "COMPLEX",
        "predicted_category": "COMMAND",
        "expected_final_route": "CLOUD",
        "actual_final_route": "CLARIFICATION",
        "classification_correct": False,
        "route_correct": False,
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
