from __future__ import annotations

from pallas.product.llm.sticker_fit import (
    StickerFitStore,
    record_sticker_feedback,
    upsert_sticker_candidate,
)


def test_sticker_fit_upsert_and_pick(tmp_path) -> None:
    store = StickerFitStore(tmp_path / "stickers.json")
    upsert_sticker_candidate(
        store,
        sticker_id="md5-a",
        tags=["无奈", "翻白眼"],
        persona_fit=True,
    )
    upsert_sticker_candidate(
        store,
        sticker_id="md5-b",
        tags=["开心"],
        persona_fit=False,
    )
    picked = store.pick_by_tag("无奈")
    assert picked is not None
    assert picked["sticker_id"] == "md5-a"
    assert store.pick_by_tag("开心") is None


def test_sticker_feedback_can_demote(tmp_path) -> None:
    store = StickerFitStore(tmp_path / "stickers.json")
    upsert_sticker_candidate(store, sticker_id="md5-c", tags=["无语"], persona_fit=True)
    for _ in range(3):
        record_sticker_feedback(store, sticker_id="md5-c", score=1)
    item = store.get("md5-c")
    assert item is not None
    assert item["persona_fit"] is False
