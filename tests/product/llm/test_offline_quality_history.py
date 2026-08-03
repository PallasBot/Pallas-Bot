from pallas.product.llm.offline_quality_eval import OfflineQualityCase, OfflineQualityJudge, OfflineQualityResult
from pallas.product.llm.offline_quality_history import (
    compare_quality_baselines,
    latest_quality_run_rows,
    quality_result_rows,
    summarize_quality_baseline,
)


def test_quality_result_rows_keep_matrix_identity_and_judge_audit() -> None:
    case = OfflineQualityCase(
        "calm_short_vent",
        "又临时改了，烦",
        "ACK",
        "emotion",
        persona_id="calm",
        scene="short_vent",
    )
    result = OfflineQualityResult(
        case_id=case.case_id,
        reply_target="emotion",
        reply_text="这确实烦。",
        firewall_rule_ids=("short_vent_overexplained",),
        heuristic_scores={"naturalness": 4},
        initial_reply_text="这确实烦。",
        initial_firewall_rule_ids=(),
        retry_count=0,
        final_action="allow",
        final_raw_reply_text="这确实烦。",
        final_rejected_rule_ids=(),
        judge=OfflineQualityJudge("ALLOW", {"naturalness": 5}, ("accepted",)),
    )

    rows = quality_result_rows(
        (case,),
        (result,),
        run_id="run-1",
        created_at=100,
        matrix_version="anonymous-v1",
    )

    assert rows == [
        {
            "run_id": "run-1",
            "created_at": 100,
            "matrix_version": "anonymous-v1",
            "persona_id": "calm",
            "case_id": "calm_short_vent",
            "scene": "short_vent",
            "scores": {"naturalness": 5},
            "heuristic_scores": {"naturalness": 4},
            "judge": {"verdict": "ALLOW", "reason_ids": ["accepted"]},
            "firewall_rule_ids": ["short_vent_overexplained"],
        }
    ]


def test_compare_quality_baselines_reports_only_score_and_rule_regressions() -> None:
    previous = summarize_quality_baseline([
        {
            "persona_id": "calm",
            "scene": "short_vent",
            "scores": {"naturalness": 5, "grounded": 4},
            "firewall_rule_ids": [],
        }
    ])
    current = summarize_quality_baseline([
        {
            "persona_id": "calm",
            "scene": "short_vent",
            "scores": {"naturalness": 4, "grounded": 5},
            "firewall_rule_ids": ["short_vent_overexplained"],
        }
    ])

    assert compare_quality_baselines(current, previous) == {
        "score_regressions": [
            {
                "bucket": "by_persona",
                "key": "calm",
                "score": "naturalness",
                "previous": 5.0,
                "current": 4.0,
            },
            {
                "bucket": "by_scene",
                "key": "short_vent",
                "score": "naturalness",
                "previous": 5.0,
                "current": 4.0,
            },
        ],
        "new_rule_ids": ["short_vent_overexplained"],
    }


def test_latest_quality_run_rows_selects_latest_matching_matrix_only() -> None:
    rows = [
        {"run_id": "old", "created_at": 10, "matrix_version": "anonymous-v1"},
        {"run_id": "other", "created_at": 20, "matrix_version": "default-v1"},
        {"run_id": "new", "created_at": 30, "matrix_version": "anonymous-v1"},
        {"run_id": "new", "created_at": 30, "matrix_version": "anonymous-v1", "case_id": "two"},
    ]

    assert latest_quality_run_rows(rows, matrix_version="anonymous-v1") == rows[2:]
