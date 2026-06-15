from __future__ import annotations

import os
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from src.console.webui.field_help import field_help
from src.foundation.config.dotenv import (
    merged_repo_dotenv_upper,
    repo_layered_dotenv_files_exist,
)

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


def _scrub_env_str(
    name_upper: str,
    *,
    merged_dotenv: dict[str, str],
    default: str = "",
) -> str:
    # 环境变量 > 仓库 .env 合并层；若仓库已有 dotenv 文件则不回退 driver.config。
    if name_upper in os.environ:
        return (os.environ.get(name_upper, default) or "").strip()
    if name_upper in merged_dotenv:
        return (merged_dotenv[name_upper] or "").strip()
    if not repo_layered_dotenv_files_exist():
        nb = _nonebot_driver_config_str(name_upper)
        if nb is not None:
            return nb.strip()
    return default


def _scrub_review_providers_key_explicit(merged_dotenv: dict[str, str]) -> bool:
    if "PALLAS_SCRUB_REVIEW_PROVIDERS" in os.environ:
        return True
    if "PALLAS_SCRUB_REVIEW_PROVIDERS" in merged_dotenv:
        return True
    try:
        from nonebot import get_driver

        cfg = get_driver().config
    except ValueError:
        return False
    if not repo_layered_dotenv_files_exist():
        return "pallas_scrub_review_providers" in (getattr(cfg, "model_fields_set", None) or set())
    return False


def message_scrub_has_active_config(cfg: MessageScrubConfig | None = None) -> bool:
    """未显式设置 ``PALLAS_MESSAGE_SCRUB_ENABLED`` 时，根据是否已有审查配置推断。"""
    c = cfg or get_message_scrub_config()
    if (c.inbound_filter_substrings or "").strip():
        return True
    if (c.scrub_lexicon_path or "").strip():
        return True
    if (c.scrub_lexicon_extra or "").strip():
        return True
    if c.scrub_review_providers_key_present and (c.scrub_review_providers or "").strip():
        return True
    if not c.scrub_review_providers_key_present:
        if (c.scrub_api_url or c.inbound_filter_api_url or "").strip():
            return True
        if (c.scrub_baidu_api_key or "").strip() and (c.scrub_baidu_secret_key or "").strip():
            return True
    return False


def is_message_scrub_enabled() -> bool:
    """运行时是否执行入站审查；显式 ``PALLAS_MESSAGE_SCRUB_ENABLED=false`` 可覆盖旧配置。"""
    merged = merged_repo_dotenv_upper()
    raw = _scrub_env_str("PALLAS_MESSAGE_SCRUB_ENABLED", merged_dotenv=merged, default="")
    if raw:
        return raw.lower() not in ("0", "false", "no", "off")
    return message_scrub_has_active_config()


class MessageScrubConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    inbound_filter_substrings: str = Field(
        default="",
        description=field_help(
            "在本地按关键词拦截入站消息",
            "多个词用英文逗号分隔；消息里只要出现其中任一词（不区分大小写）就不再处理",
            "留空表示不按关键词拦截",
        ),
    )
    scrub_lexicon_path: str = Field(
        default="",
        description=field_help(
            "从文件加载敏感词表",
            "填写服务器上词表文件的完整路径；文件需为 UTF-8 文本，一行一个词，以 # 开头的行会被忽略",
            "留空表示不使用外部词表文件",
        ),
    )
    scrub_lexicon_extra: str = Field(
        default="",
        description=field_help(
            "在本地词表外再追加一批词",
            "多个词用英文逗号分隔，会与词表文件中的词一起参与匹配",
            "留空表示不追加",
        ),
    )
    scrub_review_providers_key_present: bool = Field(
        default=False,
        description=field_help(
            "标记是否已在环境里写过「审查服务列表」这一项",
            "一般由程序自动维护，请勿在控制台手动修改",
        ),
    )
    scrub_review_providers: str = Field(
        default="",
        description=field_help(
            "按顺序调用哪些在线审查服务",
            "多个服务名用英文逗号分隔：baidu（百度）、json_http / generic / http（自建接口）",
            "留空表示不启用在线审查，仅使用本地词表与关键词",
        ),
    )
    scrub_api_url: str = Field(
        default="",
        description=field_help(
            "使用你自己搭建的审查接口",
            "填写完整网址（含 http 或 https）；若同时填了备用审查网址，以本项为准",
            "留空表示不使用自建接口",
        ),
    )
    inbound_filter_api_url: str = Field(
        default="",
        description=field_help(
            "审查接口网址（备用项）",
            "与「自建审查接口」作用相同，仅在前一项留空时才会使用",
            "留空表示不用此项",
        ),
    )
    inbound_filter_api_key: str = Field(
        default="",
        description=field_help(
            "访问自建审查接口时携带的密钥",
            "按你的网关要求填写；不需要密钥时留空",
        ),
    )
    inbound_filter_api_timeout_sec: float = Field(
        default=2.0,
        ge=0.1,
        le=120.0,
        description=field_help(
            "等待在线审查接口返回的最长时间",
            "填写秒数，例如 2 表示最多等 2 秒",
            "时间过短容易误判为失败；过长会拖慢收消息",
        ),
    )
    inbound_filter_api_fail_open: bool = Field(
        default=True,
        description=field_help(
            "在线审查出错或超时时是否仍放行消息",
            "开启：接口不可用时不拦消息；关闭：出错时按拦截处理",
            "若你更在意可用性可保持开启；更在意安全可关闭",
        ),
    )
    scrub_baidu_api_key: str = Field(
        default="",
        description=field_help(
            "百度内容审核的 API Key",
            "在百度智能云控制台创建应用后获取",
            "仅在使用 baidu 审查时需要填写",
        ),
    )
    scrub_baidu_secret_key: str = Field(
        default="",
        description=field_help(
            "百度内容审核的 Secret Key",
            "与 API Key 成对使用",
            "请勿泄露或提交到公开仓库",
        ),
    )
    scrub_baidu_censor_url: str = Field(
        default="",
        description=field_help(
            "百度文本审核的接口地址",
            "一般留空即可，程序会使用百度官方默认地址",
            "只有百度文档要求自定义端点时才需要改",
        ),
    )
    scrub_baidu_strategy_id: str = Field(
        default="",
        description=field_help(
            "百度审核策略编号",
            "若你在百度控制台配置了专用策略，可填写对应 ID",
            "留空使用账号默认策略",
        ),
    )
    scrub_baidu_block_suspected: bool = Field(
        default=True,
        description=field_help(
            "百度返回「疑似违规」时是否也拦截",
            "开启：疑似也当违规处理；关闭：仅明确违规才拦截",
        ),
    )

    @classmethod
    def from_env(cls) -> Self:
        merged_dotenv = merged_repo_dotenv_upper()
        has_rp = _scrub_review_providers_key_explicit(merged_dotenv)
        rp_val = _scrub_env_str("PALLAS_SCRUB_REVIEW_PROVIDERS", merged_dotenv=merged_dotenv, default="")
        try:
            timeout_sec = float(
                _scrub_env_str(
                    "PALLAS_INBOUND_FILTER_API_TIMEOUT_SEC",
                    merged_dotenv=merged_dotenv,
                    default="2",
                )
            )
        except ValueError:
            timeout_sec = 2.0
        timeout_sec = max(0.1, min(120.0, timeout_sec))
        return cls(
            inbound_filter_substrings=_scrub_env_str("PALLAS_INBOUND_FILTER_SUBSTRINGS", merged_dotenv=merged_dotenv),
            scrub_lexicon_path=_scrub_env_str("PALLAS_SCRUB_LEXICON_PATH", merged_dotenv=merged_dotenv),
            scrub_lexicon_extra=_scrub_env_str("PALLAS_SCRUB_LEXICON_EXTRA", merged_dotenv=merged_dotenv),
            scrub_review_providers_key_present=has_rp,
            scrub_review_providers=rp_val,
            scrub_api_url=_scrub_env_str("PALLAS_SCRUB_API_URL", merged_dotenv=merged_dotenv),
            inbound_filter_api_url=_scrub_env_str("PALLAS_INBOUND_FILTER_API_URL", merged_dotenv=merged_dotenv),
            inbound_filter_api_key=_scrub_env_str("PALLAS_INBOUND_FILTER_API_KEY", merged_dotenv=merged_dotenv),
            inbound_filter_api_timeout_sec=timeout_sec,
            inbound_filter_api_fail_open=_fail_open_from_str(
                _scrub_env_str(
                    "PALLAS_INBOUND_FILTER_API_FAIL_OPEN",
                    merged_dotenv=merged_dotenv,
                    default="1",
                )
            ),
            scrub_baidu_api_key=_scrub_env_str("PALLAS_SCRUB_BAIDU_API_KEY", merged_dotenv=merged_dotenv),
            scrub_baidu_secret_key=_scrub_env_str("PALLAS_SCRUB_BAIDU_SECRET_KEY", merged_dotenv=merged_dotenv),
            scrub_baidu_censor_url=_scrub_env_str("PALLAS_SCRUB_BAIDU_CENSOR_URL", merged_dotenv=merged_dotenv),
            scrub_baidu_strategy_id=_scrub_env_str("PALLAS_SCRUB_BAIDU_STRATEGY_ID", merged_dotenv=merged_dotenv),
            scrub_baidu_block_suspected=_block_suspected_from_str(
                _scrub_env_str(
                    "PALLAS_SCRUB_BAIDU_BLOCK_SUSPECTED",
                    merged_dotenv=merged_dotenv,
                    default="1",
                )
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
    """读取当前环境；缓存至 ``clear_message_scrub_config_cache``。"""
    global _cached_message_scrub_config
    with _config_lock:
        if _cached_message_scrub_config is None:
            _cached_message_scrub_config = MessageScrubConfig.from_env()
        return _cached_message_scrub_config
