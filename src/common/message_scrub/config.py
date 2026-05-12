from __future__ import annotations

import os
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

_config_lock = Lock()
_cached_message_scrub_config: MessageScrubConfig | None = None


def _fail_open_from_str(raw: str) -> bool:
    v = raw.strip().lower()
    return v in ("1", "true", "yes", "on", "")


def _block_suspected_from_str(raw: str) -> bool:
    v = raw.strip().lower()
    return v in ("1", "true", "yes", "on", "")


def _nonebot_driver_config_str(name_upper: str) -> str | None:
    try:
        from nonebot import get_driver

        cfg = get_driver().config
    except ValueError:
        return None
    attr = name_upper.lower()
    fields_set = getattr(cfg, "model_fields_set", None) or set()
    if attr not in fields_set:
        return None
    val = getattr(cfg, attr, None)
    if val is None:
        return ""
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, int | float):
        return str(val)
    return str(val).strip()


def _merged_env_str(name_upper: str, default: str = "") -> str:
    if name_upper in os.environ:
        return os.environ.get(name_upper, default).strip()
    nb = _nonebot_driver_config_str(name_upper)
    if nb is not None:
        return nb.strip()
    return default


def _scrub_review_providers_key_explicit() -> bool:
    if "PALLAS_SCRUB_REVIEW_PROVIDERS" in os.environ:
        return True
    try:
        from nonebot import get_driver

        cfg = get_driver().config
    except ValueError:
        return False
    return "pallas_scrub_review_providers" in (getattr(cfg, "model_fields_set", None) or set())


class MessageScrubConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    inbound_filter_substrings: str = Field(
        default="",
        description="逗号分隔本地子串；命中则拦截。不区分大小写。",
    )
    scrub_lexicon_path: str = Field(
        default="",
        description="可选 UTF-8 词表文件路径，一行一词，# 开头为注释。",
    )
    scrub_lexicon_extra: str = Field(
        default="",
        description="逗号分隔追加词，并入本地词库。",
    )
    scrub_review_providers_key_present: bool = Field(
        default=False,
        description="是否显式设置 PALLAS_SCRUB_REVIEW_PROVIDERS（含空字符串）。",
    )
    scrub_review_providers: str = Field(
        default="",
        description="审查链：逗号分隔的 baidu / json_http / generic / http。",
    )
    scrub_api_url: str = Field(default="", description="自建审查网关 URL（优先于 inbound_filter_api_url）。")
    inbound_filter_api_url: str = Field(default="", description="自建审查网关 URL（备用键名）。")
    inbound_filter_api_key: str = Field(default="", description="自建网关 Bearer Token。")
    inbound_filter_api_timeout_sec: float = Field(
        default=2.0,
        ge=0.1,
        le=120.0,
        description="远程审查 HTTP 超时（秒）。",
    )
    inbound_filter_api_fail_open: bool = Field(
        default=True,
        description="远程失败时是否放行（True=放行，False=按拦截处理）。",
    )
    scrub_baidu_api_key: str = Field(default="", description="百度 API Key（client_id）。")
    scrub_baidu_secret_key: str = Field(default="", description="百度 Secret Key（client_secret）。")
    scrub_baidu_censor_url: str = Field(default="", description="百度文本审核接口 URL，空则用官方默认。")
    scrub_baidu_strategy_id: str = Field(default="", description="百度策略 ID，可选。")
    scrub_baidu_block_suspected: bool = Field(
        default=True,
        description="百度 conclusion 为「疑似」时是否拦截。",
    )

    @classmethod
    def from_env(cls) -> Self:
        has_rp = _scrub_review_providers_key_explicit()
        rp_val = _merged_env_str("PALLAS_SCRUB_REVIEW_PROVIDERS", "")
        try:
            timeout_sec = float(_merged_env_str("PALLAS_INBOUND_FILTER_API_TIMEOUT_SEC", "2"))
        except ValueError:
            timeout_sec = 2.0
        timeout_sec = max(0.1, min(120.0, timeout_sec))
        return cls(
            inbound_filter_substrings=_merged_env_str("PALLAS_INBOUND_FILTER_SUBSTRINGS"),
            scrub_lexicon_path=_merged_env_str("PALLAS_SCRUB_LEXICON_PATH"),
            scrub_lexicon_extra=_merged_env_str("PALLAS_SCRUB_LEXICON_EXTRA"),
            scrub_review_providers_key_present=has_rp,
            scrub_review_providers=rp_val,
            scrub_api_url=_merged_env_str("PALLAS_SCRUB_API_URL"),
            inbound_filter_api_url=_merged_env_str("PALLAS_INBOUND_FILTER_API_URL"),
            inbound_filter_api_key=_merged_env_str("PALLAS_INBOUND_FILTER_API_KEY"),
            inbound_filter_api_timeout_sec=timeout_sec,
            inbound_filter_api_fail_open=_fail_open_from_str(
                _merged_env_str("PALLAS_INBOUND_FILTER_API_FAIL_OPEN", "1")
            ),
            scrub_baidu_api_key=_merged_env_str("PALLAS_SCRUB_BAIDU_API_KEY"),
            scrub_baidu_secret_key=_merged_env_str("PALLAS_SCRUB_BAIDU_SECRET_KEY"),
            scrub_baidu_censor_url=_merged_env_str("PALLAS_SCRUB_BAIDU_CENSOR_URL"),
            scrub_baidu_strategy_id=_merged_env_str("PALLAS_SCRUB_BAIDU_STRATEGY_ID"),
            scrub_baidu_block_suspected=_block_suspected_from_str(
                _merged_env_str("PALLAS_SCRUB_BAIDU_BLOCK_SUSPECTED", "1")
            ),
        )

    def json_http_url(self) -> str:
        return self.scrub_api_url or self.inbound_filter_api_url


def clear_message_scrub_config_cache() -> None:
    """供 ``reload_message_scrub_caches`` 等调用；环境或驱动配置变更后需失效缓存。"""
    global _cached_message_scrub_config
    with _config_lock:
        _cached_message_scrub_config = None


def get_message_scrub_config() -> MessageScrubConfig:
    """读取当前环境（含 NoneBot 已从 .env 注入的自定义键）；缓存至 ``clear_message_scrub_config_cache``。"""
    global _cached_message_scrub_config
    with _config_lock:
        if _cached_message_scrub_config is None:
            _cached_message_scrub_config = MessageScrubConfig.from_env()
        return _cached_message_scrub_config
