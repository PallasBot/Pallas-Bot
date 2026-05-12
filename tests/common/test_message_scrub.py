"""message_scrub：Aho-Corasick 与入口行为。"""

import os
from pathlib import Path

import pytest

from src.common.message_scrub import (
    is_message_scrub_blocked_async,
    is_message_scrub_blocked_sync,
    reload_message_scrub_caches,
)
from src.common.message_scrub.aho_corasick import AhoCorasick


def test_ac_overlapping_patterns() -> None:
    ac = AhoCorasick(["he", "she", "his", "hers"])
    assert ac.contains("ushers")
    assert ac.contains("she")
    assert not ac.contains("abc")


def test_ac_unicode() -> None:
    ac = AhoCorasick(["敏感词", "测试"])
    assert ac.contains("这是一段敏感词内容")
    assert not ac.contains("正常")


@pytest.fixture
def scrub_env_cleanup(monkeypatch: pytest.MonkeyPatch):
    keys = [
        "PALLAS_INBOUND_FILTER_SUBSTRINGS",
        "PALLAS_SCRUB_LEXICON_PATH",
        "PALLAS_SCRUB_LEXICON_EXTRA",
        "PALLAS_INBOUND_FILTER_API_URL",
        "PALLAS_SCRUB_API_URL",
        "PALLAS_SCRUB_REVIEW_PROVIDERS",
        "PALLAS_SCRUB_BAIDU_API_KEY",
        "PALLAS_SCRUB_BAIDU_SECRET_KEY",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    reload_message_scrub_caches()
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    reload_message_scrub_caches()


def test_sync_hits_env_substrings(scrub_env_cleanup: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLAS_INBOUND_FILTER_SUBSTRINGS", "badword,spam")
    reload_message_scrub_caches()
    assert is_message_scrub_blocked_sync(plain_text="has BADWORD here", raw_message="")
    assert not is_message_scrub_blocked_sync(plain_text="clean", raw_message="")


def test_sync_hits_lexicon_file(scrub_env_cleanup: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "lex.txt"
    p.write_text("# c\nblockedline\n", encoding="utf-8")
    monkeypatch.setenv("PALLAS_SCRUB_LEXICON_PATH", str(p))
    reload_message_scrub_caches()
    assert is_message_scrub_blocked_sync(plain_text="prefix blockedline suffix", raw_message="")


@pytest.mark.asyncio
async def test_async_local_short_circuit_no_http(scrub_env_cleanup: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALLAS_INBOUND_FILTER_SUBSTRINGS", "x")
    reload_message_scrub_caches()
    assert await is_message_scrub_blocked_async(plain_text="x", raw_message="")


def test_build_review_providers_default_baidu_before_json(
    scrub_env_cleanup: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.common.message_scrub.api_chain import build_review_providers

    monkeypatch.setenv("PALLAS_SCRUB_BAIDU_API_KEY", "ak")
    monkeypatch.setenv("PALLAS_SCRUB_BAIDU_SECRET_KEY", "sk")
    monkeypatch.setenv("PALLAS_SCRUB_API_URL", "https://example.invalid/scrub")
    monkeypatch.delenv("PALLAS_SCRUB_REVIEW_PROVIDERS", raising=False)
    ids = [p.id for p in build_review_providers()]
    assert ids == ["baidu", "json_http"]


def test_build_review_providers_explicit_order(
    scrub_env_cleanup: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.common.message_scrub.api_chain import build_review_providers

    monkeypatch.setenv("PALLAS_SCRUB_BAIDU_API_KEY", "ak")
    monkeypatch.setenv("PALLAS_SCRUB_BAIDU_SECRET_KEY", "sk")
    monkeypatch.setenv("PALLAS_SCRUB_API_URL", "https://example.invalid/scrub")
    monkeypatch.setenv("PALLAS_SCRUB_REVIEW_PROVIDERS", "json_http,baidu")
    ids = [p.id for p in build_review_providers()]
    assert ids == ["json_http", "baidu"]
