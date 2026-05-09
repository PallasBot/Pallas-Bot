"""dream.history_bottle 纯函数单测（不连库）。"""

from __future__ import annotations

import pytest

from src.plugins.dream.history_bottle import (
    DREAM_KEY_PREFIX,
    DREAM_RECORD_SEP,
    dream_display_name_from_keywords,
    dream_keywords_for_insert,
    first_http_image_url_from_cq_raw,
)


def test_dream_keywords_for_insert_basic() -> None:
    kw = dream_keywords_for_insert("凯尔希")
    assert kw.startswith(DREAM_KEY_PREFIX)
    assert DREAM_RECORD_SEP in kw
    assert "凯尔希" in kw


def test_dream_keywords_for_insert_strips_record_sep() -> None:
    raw_nick = f"left{DREAM_RECORD_SEP}right"
    kw = dream_keywords_for_insert(raw_nick)
    assert dream_display_name_from_keywords(kw) == "left right"


def test_dream_keywords_for_insert_empty_defaults() -> None:
    kw = dream_keywords_for_insert("")
    assert kw.startswith(DREAM_KEY_PREFIX)
    assert "某位博士" in kw


def test_dream_display_name_from_is_dream() -> None:
    kw = dream_keywords_for_insert("阿米娅")
    assert dream_display_name_from_keywords(kw) == "阿米娅"


def test_dream_display_name_non_is_dream_prefix_fallback() -> None:
    assert dream_display_name_from_keywords(f"[牛牛做梦记录]{DREAM_RECORD_SEP}老陈") == "某位博士"


def test_dream_display_name_unknown_prefix() -> None:
    assert dream_display_name_from_keywords("hello") == "某位博士"


def test_dream_display_name_non_str() -> None:
    assert dream_display_name_from_keywords(None) == "某位博士"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected_sub"),
    [
        (
            "[CQ:image,url=https%3A%2F%2Fexample.com%2Fx.png]",
            "https://example.com/x.png",
        ),
        (
            "[CQ:image,file=https%3A%2F%2Fcdn.example%2F1.png]",
            "https://cdn.example/1.png",
        ),
    ],
)
def test_first_http_image_url_from_cq_raw(raw: str, expected_sub: str) -> None:
    u = first_http_image_url_from_cq_raw(raw)
    assert u is not None
    assert u.startswith("http")
    assert expected_sub in u or u == expected_sub


def test_first_http_image_url_no_http_returns_none() -> None:
    raw = "[CQ:image,file=base64://xxx]"
    assert first_http_image_url_from_cq_raw(raw) is None


def test_first_http_image_url_plain_text() -> None:
    assert first_http_image_url_from_cq_raw("你好") is None
