from __future__ import annotations

from src.platform.shard.coord.dream_drift import drift_payload_from_dict, drift_payload_to_dict
from src.plugins.dream.payload import DriftPayload


def test_drift_payload_roundtrip_text() -> None:
    src = DriftPayload(nickname="老陈", text="梦见罗德岛")
    data = drift_payload_to_dict(src)
    out = drift_payload_from_dict(data)
    assert out.nickname == "老陈"
    assert out.text == "梦见罗德岛"
    assert out.image_bytes is None


def test_drift_payload_roundtrip_image() -> None:
    raw = b"\x89PNG" + b"dream"
    src = DriftPayload(nickname="博士", image_bytes=raw)
    out = drift_payload_from_dict(drift_payload_to_dict(src))
    assert out.image_bytes == raw


def test_drift_payload_roundtrip_mixed() -> None:
    raw = b"\xff\xd8\xff"
    src = DriftPayload(nickname="  ", text="  hi  ", image_bytes=raw)
    out = drift_payload_from_dict(drift_payload_to_dict(src))
    assert out.nickname == "某位博士"
    assert out.text == "  hi  "
    assert out.image_bytes == raw
