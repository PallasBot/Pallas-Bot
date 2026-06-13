"""WebUI「语料联邦」配置段读写。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.console.webui.field_help import field_help
from src.foundation.config.repo_settings import repo_env_raw_value

_TRI = Literal["auto", "true", "false"]
_REMOTE_FIND = Literal["auto", "false", "prefetch", "sync"]


def _tristate_read(env_key: str, *, default: str = "auto") -> str:
    raw = repo_env_raw_value(env_key)
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in ("auto", ""):
        return "auto"
    if s in ("1", "true", "yes", "on"):
        return "true"
    if s in ("0", "false", "no", "off"):
        return "false"
    return default


def _remote_find_read(env_key: str, *, default: str = "auto") -> str:
    raw = repo_env_raw_value(env_key)
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in ("auto", ""):
        return "auto"
    if s in ("0", "false", "no", "off"):
        return "false"
    if s in ("1", "true", "yes", "on", "prefetch"):
        return "prefetch"
    if s == "sync":
        return "sync"
    return default


def _str_read(env_key: str, default: str = "") -> str:
    raw = repo_env_raw_value(env_key)
    if raw is None:
        return default
    return str(raw).strip() or default


class CorpusFederationWebuiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    merge_order: str = Field(
        default="local",
        description=field_help(
            "接话时按什么顺序查找语料",
            "选「先本机再共享池」时，本机没有合适回复才会查社区；选「只用本机」则完全不查共享池",
            "关闭共享语料后建议改为「只用本机」",
        ),
    )
    merge_strategy: Literal["local_first", "merge_counts"] = Field(
        default="local_first",
        description=field_help(
            "本机与共享池都有同一句回复时怎么处理",
            "本地优先：以本机记录为准；合并计数：把两边的使用次数加在一起再排序",
        ),
    )
    community_enabled: _TRI = Field(
        default="false",
        description=field_help(
            "是否使用社区共享语料池",
            "开启后可从社区读取大家贡献的接话素材；默认关闭，需手动开启",
            "与上方「接话查找顺序」配合使用",
        ),
    )
    auto_enroll: _TRI = Field(
        default="false",
        description=field_help(
            "是否自动向社区登记本机语料访问凭证",
            "开启共享语料后，程序会向社区中心登记并保存口令，一般无需手填",
            "已有手动口令时可保持关闭",
        ),
    )
    community_contribute: _TRI = Field(
        default="auto",
        description=field_help(
            "是否把本机新学到的回复上传到共享池",
            "自动：在已接入共享语料时默认允许上传；也可强制开启或关闭",
            "仅上传关键词与短句，不含群号与 QQ",
        ),
    )
    remote_find_enabled: _REMOTE_FIND = Field(
        default="auto",
        description=field_help(
            "本机语料没命中时，是否向共享池查询",
            "后台预取（推荐）：查到后写入本机，下次接话即可用；当场查询：当次消息立刻联网查",
            "与「是否使用共享语料」独立；只影响读取，不影响学习上传",
        ),
    )
    fed_enabled: _TRI = Field(
        default="auto",
        description=field_help(
            "是否启用跨站联邦语料（进阶）",
            "多数自托管部署用不到，保持关闭或自动即可",
        ),
    )
    fed_contribute: bool = Field(
        default=False,
        description=field_help(
            "是否向联邦语料库回写学习结果",
            "仅在你已部署联邦服务并了解风险时开启",
        ),
    )
    on_remote_failure: Literal["local_only"] = Field(
        default="local_only",
        description=field_help(
            "访问共享语料失败时的兜底方式",
            "目前固定为仅使用本机语料，保证牛牛仍能正常接话",
        ),
    )
    community_api_base: str = Field(
        default="",
        description=field_help(
            "共享语料服务的根地址",
            "填写形如 https://示例域名 的地址，末尾不要加斜杠",
            "留空时程序会按自动登记结果或统计上报地址推导",
        ),
    )
    community_token: str = Field(
        default="",
        description=field_help(
            "访问共享语料用的口令",
            "一般以 pc_ 开头；留空则使用自动登记保存在本机的口令",
        ),
    )
    community_stats_enabled: bool = Field(
        default=True,
        description=field_help(
            "是否向社区中心上报本机在线情况",
            "开启后「统计与语料」页才能看到全网大致数据；关闭不影响牛牛聊天",
            "默认开启；单进程总机上报，分片 worker 不上报",
        ),
    )
    community_stats_endpoint: str = Field(
        default="https://stats.pallasbot.top/v1/heartbeat",
        description=field_help(
            "在线统计要提交到的网址",
            "官方地址一般无需修改；主站不可用时程序会自动尝试备站",
        ),
    )
    community_stats_token: str = Field(
        default="",
        description=field_help(
            "提交统计时附带的访问口令",
            "公开统计服务通常可留空；运营方发了专用口令再填写",
        ),
    )
    community_stats_interval_sec: int = Field(
        default=300,
        ge=60,
        le=3600,
        description=field_help(
            "每隔多少秒上报一次在线情况",
            "例如 300 表示 5 分钟一次；间隔越短请求越频繁，越长则页面数据更新越慢",
        ),
    )
    community_stats_roster_public: bool = Field(
        default=False,
        description=field_help(
            "是否在社区主站公开本部署牛牛名册",
            "开启后随统计上报 QQ、昵称、在线状态与近 7 日消息量；主站气泡墙可点击查看 QQ 资料",
            "不上报群号与消息正文；默认关闭，可随时关掉",
        ),
    )


def get_corpus_federation_webui_config() -> CorpusFederationWebuiConfig:
    interval_raw = repo_env_raw_value("PALLAS_COMMUNITY_STATS_INTERVAL_SEC")
    try:
        interval = int(str(interval_raw).strip()) if interval_raw is not None else 300
    except ValueError:
        interval = 300
    interval = max(60, min(3600, interval))
    enabled_raw = repo_env_raw_value("PALLAS_COMMUNITY_STATS_ENABLED")
    stats_enabled = True
    if enabled_raw is not None:
        stats_enabled = str(enabled_raw).strip().lower() not in ("0", "false", "no", "off")
    strategy = _str_read("PALLAS_CORPUS_MERGE_STRATEGY", "local_first")
    if strategy not in ("local_first", "merge_counts"):
        strategy = "local_first"
    return CorpusFederationWebuiConfig(
        merge_order=_str_read("PALLAS_CORPUS_MERGE_ORDER", "local"),
        merge_strategy=strategy,  # type: ignore[arg-type]
        community_enabled=_tristate_read("PALLAS_CORPUS_COMMUNITY_ENABLED", default="false"),
        auto_enroll=_tristate_read("PALLAS_CORPUS_AUTO_ENROLL", default="false"),
        community_contribute=_tristate_read("PALLAS_CORPUS_COMMUNITY_CONTRIBUTE"),
        remote_find_enabled=_remote_find_read("PALLAS_CORPUS_REMOTE_FIND_ENABLED"),
        fed_enabled=_tristate_read("PALLAS_CORPUS_FED_ENABLED"),
        fed_contribute=_tristate_read("PALLAS_CORPUS_FED_CONTRIBUTE", default="false") == "true",
        on_remote_failure="local_only",
        community_api_base=_str_read("PALLAS_CORPUS_COMMUNITY_API_BASE"),
        community_token=_str_read("PALLAS_CORPUS_TOKEN") or _str_read("PALLAS_CORPUS_COMMUNITY_TOKEN"),
        community_stats_enabled=stats_enabled,
        community_stats_endpoint=_str_read(
            "PALLAS_COMMUNITY_STATS_ENDPOINT",
            "https://stats.pallasbot.top/v1/heartbeat",
        ),
        community_stats_token=_str_read("PALLAS_COMMUNITY_STATS_TOKEN"),
        community_stats_interval_sec=interval,
        community_stats_roster_public=_str_read("PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC", "").lower()
        in ("1", "true", "yes", "on"),
    )
