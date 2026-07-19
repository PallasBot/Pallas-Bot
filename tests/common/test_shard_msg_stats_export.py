from __future__ import annotations

from packages.pb_webui.extended_api import (
    _message_stats_mem_from_shard_blob,
    _msg_stats_shard_export,
    _msg_stats_shard_import,
)


def test_msg_stats_shard_export_import_roundtrip():
    mem = {
        "sent": 10,
        "received": 20,
        "day_sent": 3,
        "day_received": 5,
        "day_key": "2026-05-23",
        "day_api_total": 7,
        "day_api_counts": {"send_group_msg": 4, "delete_msg": 3},
        "api_call_buckets": [{"at": 100, "apis": {"send_group_msg": 2}}],
        "msg_traffic_buckets": [{"at": 100, "recv": 1, "sent": 0}],
    }
    blob = _msg_stats_shard_export(mem)
    restored = _msg_stats_shard_import(blob, today="2026-05-23")
    assert restored["day_api_total"] == 7
    assert restored["day_api_counts"]["send_group_msg"] == 4
    assert len(restored["api_call_buckets"]) == 1
    assert len(restored["msg_traffic_buckets"]) == 1


def test_message_stats_mem_from_shard_blob_keeps_api_series():
    rec = {
        "msg": {
            "sent": 1,
            "received": 2,
            "day_sent": 1,
            "day_received": 2,
            "day_key": "2026-05-23",
            "day_api_total": 2,
            "day_api_counts": {"get_group_member_info": 2},
            "api_call_buckets": [{"at": 200, "apis": {"get_group_member_info": 2}}],
            "msg_traffic_buckets": [],
        }
    }
    mem = _message_stats_mem_from_shard_blob(rec)
    assert mem["day_api_total"] == 2
    assert mem["api_call_buckets"][0]["apis"]["get_group_member_info"] == 2
