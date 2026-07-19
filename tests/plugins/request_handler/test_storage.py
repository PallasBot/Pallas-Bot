import json
from pathlib import Path

from packages.request_handler.storage import merge_write_bot_entry, merge_write_bot_nested_entries


def test_merge_write_bot_nested_entries_preserves_other_bot_updates(tmp_path: Path) -> None:
    path = tmp_path / "pending_group_requests.json"
    path.write_text(
        ('{\n  "1001": {"g1": {"flag": "old"}},\n  "2002": {"g2": {"flag": "keep"}}\n}\n'),
        encoding="utf-8",
    )

    stale_snapshot = {
        "1001": {"g1": {"flag": "old"}},
        "2002": {"g2": {"flag": "stale"}},
    }
    stale_snapshot["1001"].pop("g1")

    merge_write_bot_nested_entries(path, stale_snapshot, "1001")

    assert json.loads(path.read_text(encoding="utf-8")) == {"2002": {"g2": {"flag": "keep"}}}


def test_merge_write_bot_entry_preserves_other_bot_updates(tmp_path: Path) -> None:
    path = tmp_path / "last_notified_request.json"
    path.write_text(
        (
            "{\n"
            '  "1001": {"kind": "group", "target_id": "1", "ts": 1},\n'
            '  "2002": {"kind": "friend", "target_id": "2", "ts": 99}\n'
            "}\n"
        ),
        encoding="utf-8",
    )

    stale_snapshot = {
        "1001": {"kind": "group", "target_id": "3", "ts": 2},
        "2002": {"kind": "friend", "target_id": "2", "ts": 1},
    }
    stale_snapshot.pop("1001")

    merge_write_bot_entry(path, stale_snapshot, "1001")

    assert json.loads(path.read_text(encoding="utf-8")) == {"2002": {"kind": "friend", "target_id": "2", "ts": 99}}
