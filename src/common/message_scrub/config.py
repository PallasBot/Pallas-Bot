from __future__ import annotations

import os
from typing import Self

from pydantic import BaseModel, ConfigDict, Field


def _strip_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _fail_open_from_str(raw: str) -> bool:
    v = raw.strip().lower()
    return v in ("1", "true", "yes", "on", "")


def _block_suspected_from_str(raw: str) -> bool:
    v = raw.strip().lower()
    return v in ("1", "true", "yes", "on", "")


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
        has_rp = "PALLAS_SCRUB_REVIEW_PROVIDERS" in os.environ
        rp_val = os.environ.get("PALLAS_SCRUB_REVIEW_PROVIDERS", "")
        try:
            timeout_sec = float(_strip_env("PALLAS_INBOUND_FILTER_API_TIMEOUT_SEC", "2"))
        except ValueError:
            timeout_sec = 2.0
        timeout_sec = max(0.1, min(120.0, timeout_sec))
        return cls(
            inbound_filter_substrings=_strip_env("PALLAS_INBOUND_FILTER_SUBSTRINGS"),
            scrub_lexicon_path=_strip_env("PALLAS_SCRUB_LEXICON_PATH"),
            scrub_lexicon_extra=_strip_env("PALLAS_SCRUB_LEXICON_EXTRA"),
            scrub_review_providers_key_present=has_rp,
            scrub_review_providers=rp_val.strip(),
            scrub_api_url=_strip_env("PALLAS_SCRUB_API_URL"),
            inbound_filter_api_url=_strip_env("PALLAS_INBOUND_FILTER_API_URL"),
            inbound_filter_api_key=_strip_env("PALLAS_INBOUND_FILTER_API_KEY"),
            inbound_filter_api_timeout_sec=timeout_sec,
            inbound_filter_api_fail_open=_fail_open_from_str(
                os.environ.get("PALLAS_INBOUND_FILTER_API_FAIL_OPEN", "1")
            ),
            scrub_baidu_api_key=_strip_env("PALLAS_SCRUB_BAIDU_API_KEY"),
            scrub_baidu_secret_key=_strip_env("PALLAS_SCRUB_BAIDU_SECRET_KEY"),
            scrub_baidu_censor_url=_strip_env("PALLAS_SCRUB_BAIDU_CENSOR_URL"),
            scrub_baidu_strategy_id=_strip_env("PALLAS_SCRUB_BAIDU_STRATEGY_ID"),
            scrub_baidu_block_suspected=_block_suspected_from_str(
                os.environ.get("PALLAS_SCRUB_BAIDU_BLOCK_SUSPECTED", "1")
            ),
        )

    def json_http_url(self) -> str:
        return self.scrub_api_url or self.inbound_filter_api_url


def get_message_scrub_config() -> MessageScrubConfig:
    """每次读取当前环境"""
    return MessageScrubConfig.from_env()
