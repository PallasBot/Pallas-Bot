"""语料接话性能：WebUI / 环境变量可读，供热路径与 find 缓存使用。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.core.foundation.config.repo_settings import repo_env_raw_value


def _int_read(env_key: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = repo_env_raw_value(env_key)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return max(min_v, min(max_v, value))


class CorpusReplyPerfConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply_messages_cap: int = Field(
        default=16,
        ge=1,
        le=256,
        description=field_help(
            "接话时每条语料答案最多加载多少条历史回复",
            "填 16～48：越大越完整、尖峰读库越重；热梗群可略调高",
            "仅影响接话查询，学习与全量清理仍读完整语料",
        ),
    )
    reply_answers_cap: int = Field(
        default=128,
        ge=32,
        le=4096,
        description=field_help(
            "接话时每个关键词最多加载多少条 Answer 候选",
            "热梗语料 Answer 极多时必须限制，否则查询参数超限或占满内存",
            "按 count 从高到低取前 N 条；全量 find / 学习路径不受影响",
        ),
    )
    find_cache_ttl_sec: int = Field(
        default=45,
        ge=5,
        le=600,
        description=field_help(
            "本机语料查询结果在内存中保留的秒数",
            "重复句越多越省数据库；过大可能短暂用到稍旧的接话候选",
            "保存后清空当前缓存并立即按新值生效",
        ),
    )
    find_cache_max: int = Field(
        default=50000,
        ge=1000,
        le=200000,
        description=field_help(
            "语料查询内存缓存最多保留多少条关键词",
            "超高活跃群可调高；过大占用更多内存",
        ),
    )
    reply_snapshot_ttl_sec: int = Field(
        default=5,
        ge=1,
        le=60,
        description=field_help(
            "本地 PG 接话结果在进程内短暂保留多少秒",
            "用于抵抗高频 learn 对同一关键词的反复重查；越大越省库，但新学到的回复会晚几秒生效",
        ),
    )
    reply_snapshot_max: int = Field(
        default=20000,
        ge=1000,
        le=100000,
        description=field_help(
            "PG 接话短时快照最多保留多少个关键词",
            "仅覆盖接话热路径；热点群多时可调高，代价是更多内存",
        ),
    )


@lru_cache(maxsize=1)
def get_corpus_reply_perf_config() -> CorpusReplyPerfConfig:
    return CorpusReplyPerfConfig(
        reply_messages_cap=_int_read("PALLAS_CORPUS_REPLY_MESSAGES_CAP", 16, min_v=1, max_v=256),
        reply_answers_cap=_int_read("PALLAS_CORPUS_REPLY_ANSWERS_CAP", 128, min_v=32, max_v=4096),
        find_cache_ttl_sec=_int_read("PALLAS_CORPUS_FIND_CACHE_SEC", 45, min_v=5, max_v=600),
        find_cache_max=_int_read("PALLAS_CORPUS_FIND_CACHE_MAX", 50000, min_v=1000, max_v=200000),
        reply_snapshot_ttl_sec=_int_read("PALLAS_CORPUS_REPLY_SNAPSHOT_SEC", 5, min_v=1, max_v=60),
        reply_snapshot_max=_int_read("PALLAS_CORPUS_REPLY_SNAPSHOT_MAX", 20000, min_v=1000, max_v=100000),
    )


def clear_corpus_reply_perf_config_cache() -> None:
    get_corpus_reply_perf_config.cache_clear()


def reply_messages_cap() -> int:
    return get_corpus_reply_perf_config().reply_messages_cap


def reply_answers_cap() -> int:
    return get_corpus_reply_perf_config().reply_answers_cap


def find_cache_ttl_sec() -> float:
    return float(get_corpus_reply_perf_config().find_cache_ttl_sec)


def find_cache_max_entries() -> int:
    return get_corpus_reply_perf_config().find_cache_max


def reply_snapshot_ttl_sec() -> float:
    return float(get_corpus_reply_perf_config().reply_snapshot_ttl_sec)


def reply_snapshot_max_entries() -> int:
    return get_corpus_reply_perf_config().reply_snapshot_max


def reply_query_caps(keywords: str) -> tuple[int, int]:
    """按关键词长度收紧热词查询窗口，优先保接话时延。"""
    msg_cap = reply_messages_cap()
    ans_cap = reply_answers_cap()
    key_len = len((keywords or "").strip())
    if key_len <= 2:
        return min(msg_cap, 6), min(ans_cap, 48)
    if key_len <= 3:
        return min(msg_cap, 8), min(ans_cap, 64)
    return msg_cap, ans_cap
