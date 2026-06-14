from __future__ import annotations

from src.plugins.who_is_spy import store
from src.plugins.who_is_spy.logic import pick_words


def test_pick_words_skips_recent_when_possible(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "RECENT_WORDS_FILE", tmp_path / "recent.json")
    store.WORD_BANK[:] = [("可乐", "雪碧"), ("饺子", "馄饨"), ("拿铁", "美式")]

    store.record_recent_word_pair(999, "可乐", "雪碧", keep=5)
    pair = pick_words(999, avoid_recent=5)
    assert pair != ("可乐", "雪碧")


def test_pick_words_fallback_when_all_recent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "RECENT_WORDS_FILE", tmp_path / "recent.json")
    store.WORD_BANK[:] = [("可乐", "雪碧"), ("饺子", "馄饨")]

    store.record_recent_word_pair(999, "可乐", "雪碧", keep=5)
    store.record_recent_word_pair(999, "饺子", "馄饨", keep=5)

    pair = pick_words(999, avoid_recent=5)
    assert pair in store.WORD_BANK
