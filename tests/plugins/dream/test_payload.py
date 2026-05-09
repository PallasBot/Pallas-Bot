from src.plugins.dream.payload import DriftPayload


def test_drift_payload_defaults() -> None:
    p = DriftPayload(nickname="甲")
    assert p.nickname == "甲"
    assert p.text is None
    assert p.image_bytes is None


def test_drift_payload_full() -> None:
    p = DriftPayload(nickname="乙", text="hi", image_bytes=b"\xff")
    assert p.text == "hi"
    assert p.image_bytes == b"\xff"
