"""message_scrub：Aho-Corasick 与入口行为。"""

import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


def test_scrub_intercept_log_preview_plain_then_raw() -> None:
    from src.common.message_scrub.log_preview import scrub_intercept_log_preview

    assert scrub_intercept_log_preview("  hello\n", "") == "hello"
    assert scrub_intercept_log_preview("", "[CQ:image,file=abc]") == "[CQ:image,file=abc]"
    long_b64 = "[CQ:image,file=base64://" + "a" * 120 + "]"
    out = scrub_intercept_log_preview("", long_b64)
    assert "base64://…" in out
    assert len(out) <= 49


def test_config_merged_reads_nonebot_when_os_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.common.message_scrub.config import MessageScrubConfig

    monkeypatch.delenv("PALLAS_INBOUND_FILTER_SUBSTRINGS", raising=False)
    fake_cfg = SimpleNamespace(
        model_fields_set={"pallas_inbound_filter_substrings"},
        pallas_inbound_filter_substrings="from_nb",
    )
    fake_driver = SimpleNamespace(config=fake_cfg)
    with patch("nonebot.get_driver", return_value=fake_driver):
        c = MessageScrubConfig.from_env()
    assert c.inbound_filter_substrings == "from_nb"


def test_config_merged_os_overrides_nonebot(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.common.message_scrub.config import MessageScrubConfig

    monkeypatch.setenv("PALLAS_INBOUND_FILTER_SUBSTRINGS", "from_os")
    fake_cfg = SimpleNamespace(
        model_fields_set={"pallas_inbound_filter_substrings"},
        pallas_inbound_filter_substrings="from_nb",
    )
    fake_driver = SimpleNamespace(config=fake_cfg)
    with patch("nonebot.get_driver", return_value=fake_driver):
        c = MessageScrubConfig.from_env()
    assert c.inbound_filter_substrings == "from_os"


def test_config_review_providers_explicit_from_nonebot_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.common.message_scrub.config import MessageScrubConfig

    monkeypatch.delenv("PALLAS_SCRUB_REVIEW_PROVIDERS", raising=False)
    fake_cfg = SimpleNamespace(
        model_fields_set={"pallas_scrub_review_providers"},
        pallas_scrub_review_providers="",
    )
    fake_driver = SimpleNamespace(config=fake_cfg)
    with patch("nonebot.get_driver", return_value=fake_driver):
        c = MessageScrubConfig.from_env()
    assert c.scrub_review_providers_key_present is True
    assert c.scrub_review_providers == ""


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


def test_get_message_scrub_config_cached_until_reload(
    scrub_env_cleanup: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.common.message_scrub.config import get_message_scrub_config

    monkeypatch.setenv("PALLAS_INBOUND_FILTER_SUBSTRINGS", "alpha")
    reload_message_scrub_caches()
    c1 = get_message_scrub_config()
    c2 = get_message_scrub_config()
    assert c1 is c2
    monkeypatch.setenv("PALLAS_INBOUND_FILTER_SUBSTRINGS", "beta")
    assert get_message_scrub_config() is c1
    reload_message_scrub_caches()
    c3 = get_message_scrub_config()
    assert c3.inbound_filter_substrings == "beta"
    assert c3 is not c1


def test_lexicon_file_oserror_logs_warning(tmp_path: Path) -> None:
    from src.common.message_scrub import local_lexicon

    p = tmp_path / "lex.txt"
    p.write_text("word", encoding="utf-8")

    real_open = Path.open

    def open_fail(self: Path, *args: object, **kwargs: object):
        if str(self) == str(p):
            raise OSError("eacces")
        return real_open(self, *args, **kwargs)

    with patch.object(Path, "open", open_fail):
        with patch.object(local_lexicon.logger, "warning") as mock_warn:
            assert local_lexicon._read_lexicon_file_lines(str(p)) == []
    mock_warn.assert_called_once()


def test_dream_cq_image_normalization_regex() -> None:
    """与 dream 捕获路径一致：只折叠 [CQ:image,...] 段，不误伤其它文本。"""
    pat = r"\[CQ:image,[^\]]*\]"
    s = "hello[CQ:image,file=https://x/y?q=1]]tail"
    assert re.sub(pat, "[CQ:image]", s) == "hello[CQ:image]]tail"
    assert re.sub(pat, "[CQ:image]", "plain .image,foo]") == "plain .image,foo]"


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
