from __future__ import annotations

from pallas.console.webui.enum_labels import GLOBAL_CHOICE_LABELS, field_choice_labels


def test_global_choice_labels_for_tristate():
    labels = field_choice_labels("community_contribute", ["auto", "true", "false"])
    assert labels == {"auto": "自动", "true": "开启", "false": "关闭"}


def test_merge_order_choice_labels():
    labels = field_choice_labels("merge_order", ["local,community", "local"])
    assert labels == {"local,community": "先本机，再共享池", "local": "只用本机"}


def test_interval_sec_uses_global():
    labels = field_choice_labels("community_stats_interval_sec", ["300", "600"])
    assert labels == {"300": "5 分钟", "600": "10 分钟"}


def test_global_labels_cover_expected_keys():
    assert "prefetch" in GLOBAL_CHOICE_LABELS
    assert "session" in GLOBAL_CHOICE_LABELS

def test_conversation_feature_level_choice_labels():
    labels = field_choice_labels(
        "conversation_feature_level",
        ["", "legacy_repeater", "repeater_plus_decision", "full_conversation_kernel"],
    )
    assert labels is not None
    assert labels[""] == "自动推断（推荐）"
    assert labels["full_conversation_kernel"] == "决策 + 生成 + 反馈全链路"
