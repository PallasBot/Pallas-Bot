from __future__ import annotations

from pallas.core.platform.shard.repeater_ingress_metrics import (
    clear_repeater_ingress_metrics_for_tests,
    merge_repeater_ingress_metrics,
    record_repeater_ingress_claim,
    record_repeater_ingress_early_discard,
    record_repeater_ingress_event,
    record_repeater_reply_selection,
    repeater_ingress_metrics_snapshot,
)


def test_repeater_ingress_metrics_snapshot_and_merge():
    clear_repeater_ingress_metrics_for_tests()
    record_repeater_ingress_event()
    record_repeater_ingress_event()
    record_repeater_ingress_early_discard("plugin_disabled")
    record_repeater_ingress_early_discard("plugin_command")
    record_repeater_ingress_early_discard("cross_bot_claim")
    record_repeater_ingress_early_discard("message_scrub")
    record_repeater_ingress_claim(won=True)
    record_repeater_ingress_claim(won=False)
    record_repeater_reply_selection(
        mode="god",
        source="same_group_recent_live",
        recent_hit=True,
        repeat_hit=False,
        pick_path="god_recent_live",
    )
    record_repeater_reply_selection(
        mode="ghost",
        source="cross_group",
        recent_hit=False,
        repeat_hit=True,
        pick_path="ghost_pool",
    )

    snap = repeater_ingress_metrics_snapshot()
    assert snap["events"] == 2
    assert snap["early_plugin_disabled"] == 1
    assert snap["early_plugin_command"] == 1
    assert snap["early_cross_bot_claim"] == 1
    assert snap["early_message_scrub"] == 1
    assert snap["claim_won"] == 1
    assert snap["claim_lost"] == 1
    assert snap["claim_hit_rate"] == 0.5
    assert snap["reply_total"] == 2
    assert snap["reply_mode_god"] == 1
    assert snap["reply_mode_ghost"] == 1
    assert snap["reply_source_same_group_recent_live"] == 1
    assert snap["reply_source_cross_group"] == 1
    assert snap["reply_recent_hit"] == 1
    assert snap["reply_repeat_hit"] == 1
    assert snap["reply_pick_god_recent_live"] == 1
    assert snap["reply_pick_ghost_pool"] == 1

    cluster = merge_repeater_ingress_metrics([snap, {"day_key": snap["day_key"], "claim_won": 1, "claim_lost": 0}])
    assert cluster["claim_won"] == 2
    assert cluster["claim_lost"] == 1
    assert round(cluster["claim_hit_rate"], 4) == round(2 / 3, 4)
