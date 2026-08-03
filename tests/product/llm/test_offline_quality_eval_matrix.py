from pallas.product.llm.offline_quality_eval import (
    ANONYMOUS_QUALITY_MATRIX,
    OfflineQualityCase,
    summarize_quality_matrix,
)


def test_anonymous_quality_matrix_covers_personas_and_scenarios() -> None:
    assert len(ANONYMOUS_QUALITY_MATRIX) >= 60
    assert {case.persona_id for case in ANONYMOUS_QUALITY_MATRIX} == {"calm", "warm", "direct"}
    assert all(case.expected_action for case in ANONYMOUS_QUALITY_MATRIX)
    assert all(case.forbidden_traits for case in ANONYMOUS_QUALITY_MATRIX)


def test_quality_judge_dimensions_cover_memory_tool_and_silence() -> None:
    case = OfflineQualityCase("case", "测试", "ACK", "fact")
    summary = summarize_quality_matrix([
        (
            case,
            {
                "memory_factuality": 5,
                "tool_faithfulness": 4,
                "silence_correctness": 5,
            },
        )
    ])

    assert summary["by_persona"]["unassigned"]["scores"]["memory_factuality"] == 5
    assert summary["by_persona"]["unassigned"]["scores"]["tool_faithfulness"] == 4


def test_quality_matrix_summary_groups_by_persona_and_scene() -> None:
    case = OfflineQualityCase("case", "测试", "ACK", "fact", persona_id="calm", scene="short_vent")
    summary = summarize_quality_matrix([(case, {"naturalness": 5, "persona_drift": 1}, ("short_vent_overexplained",))])

    assert summary["by_persona"]["calm"]["count"] == 1
    assert summary["by_scene"]["short_vent"]["scores"]["naturalness"] == 5
    assert summary["by_rule_id"]["short_vent_overexplained"]["count"] == 1
