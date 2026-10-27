"""方舟知识库开关。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.core.foundation.config.repo_settings import repo_env_raw_value


def env_bool(key: str, default: bool) -> bool:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(key: str, default: int) -> int:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


class ArknightsKbConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    arknights_kb_enabled: bool = Field(
        default=True,
        description=field_help("是否启用方舟干员结构化查询", "关闭后 LLM tools 与查询 API 均不可用"),
    )
    arknights_kb_auto_sync: bool = Field(
        default=True,
        description=field_help("缺干员数据时后台自动同步", "与决斗插件共用 resource/arknights/"),
    )
    prts_corpus_enabled: bool = Field(
        default=True,
        description=field_help("是否启用 PRTS 语料查询工具", "开启后可查询本地已安装的 PRTS 资料"),
    )
    prts_corpus_packs: str = Field(
        default="official_game,reviewed_wiki,terra_journey,entities,references",
        description=field_help(
            "指定 PRTS 语料包",
            "填写逗号分隔的 pack ID，如 official_game,references",
            "未知 pack ID 会忽略；终末地资料由单独开关控制",
        ),
    )
    prts_corpus_include_endfield: bool = Field(
        default=False,
        description=field_help("是否包含终末地语料", "开启后在同步范围中加入终末地资料包"),
    )
    prts_corpus_search_limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description=field_help("限制 PRTS 检索结果数量", "填写 1–10 的整数"),
    )
    prts_corpus_read_max_lines: int = Field(
        default=80,
        ge=1,
        le=200,
        description=field_help("限制单次 PRTS 原文读取行数", "填写 1–200 的整数"),
    )
    prts_corpus_read_max_chars: int = Field(
        default=12000,
        ge=1000,
        le=20000,
        description=field_help("限制单次 PRTS 原文读取字符数", "填写 1000–20000 的整数"),
    )
    prts_corpus_download_timeout_sec: int = Field(
        default=120,
        ge=10,
        le=600,
        description=field_help("设置 PRTS 语料下载请求超时", "填写 10–600 秒的整数"),
    )
    prts_corpus_cache_max_mb: int = Field(
        default=64,
        ge=16,
        le=256,
        description=field_help(
            "限制 PRTS 查询原始缓存数据预算",
            "填写 16–256 MiB",
            "按原始数据字节计量，不保证进程或容器 RSS；容器硬限制需单独设置，修改后重启 Bot/MCP 生效",
        ),
    )
    prts_corpus_query_max_mb: int = Field(
        default=64,
        ge=16,
        le=256,
        description=field_help(
            "限制单次 PRTS 查询累计解压数据预算",
            "填写 16–256 MiB",
            "按累计解压原始字节计量，不保证进程或容器 RSS；容器硬限制需单独设置，修改后重启 Bot/MCP 生效",
        ),
    )


def get_arknights_kb_config() -> ArknightsKbConfig:
    return ArknightsKbConfig(
        arknights_kb_enabled=env_bool("ARKNIGHTS_KB_ENABLED", True),
        arknights_kb_auto_sync=env_bool("ARKNIGHTS_KB_AUTO_SYNC", True),
        prts_corpus_enabled=env_bool("PRTS_CORPUS_ENABLED", True),
        prts_corpus_packs=str(
            repo_env_raw_value("PRTS_CORPUS_PACKS") or "official_game,reviewed_wiki,terra_journey,entities,references"
        ),
        prts_corpus_include_endfield=env_bool("PRTS_CORPUS_INCLUDE_ENDFIELD", False),
        prts_corpus_search_limit=env_int("PRTS_CORPUS_SEARCH_LIMIT", 5),
        prts_corpus_read_max_lines=env_int("PRTS_CORPUS_READ_MAX_LINES", 80),
        prts_corpus_read_max_chars=env_int("PRTS_CORPUS_READ_MAX_CHARS", 12000),
        prts_corpus_download_timeout_sec=env_int("PRTS_CORPUS_DOWNLOAD_TIMEOUT_SEC", 120),
        prts_corpus_cache_max_mb=env_int("PRTS_CORPUS_CACHE_MAX_MB", 64),
        prts_corpus_query_max_mb=env_int("PRTS_CORPUS_QUERY_MAX_MB", 64),
    )
