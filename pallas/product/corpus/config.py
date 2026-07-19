"""语料多源配置。"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

RemoteCorpusFindMode = Literal["off", "sync", "prefetch"]

_PREFIX = "PALLAS_CORPUS_"
_VALID_SOURCES = ("local", "fed", "community")
TriState = Literal["auto", "true", "false"]


def parse_tristate(raw: str, *, default: bool = False) -> bool | None:
    s = (raw or "").strip().lower()
    if s in ("auto", ""):
        return None
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def setting_str(name: str, default: str = "") -> str:
    raw = repo_env_raw_value(name)
    if raw is None:
        return default
    return (raw or "").strip() or default


class CorpusConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    merge_order: list[str] = Field(default_factory=lambda: list(_VALID_SOURCES))
    merge_strategy: str = Field(default="local_first")
    fed_enabled: bool | None = Field(default=None)
    community_enabled: bool | None = Field(default=None)
    auto_enroll: bool | None = Field(default=None)
    fed_contribute: bool = Field(default=False)
    community_contribute: bool | None = Field(default=None)
    on_remote_failure: str = Field(default="local_only")
    community_api_base: str = Field(default="")
    community_token: str = Field(default="")


def resolve_merge_order(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in (raw or "").split(",") if p.strip()]
    if not parts:
        return list(_VALID_SOURCES)
    out: list[str] = []
    for part in parts:
        if part in _VALID_SOURCES and part not in out:
            out.append(part)
    return out or list(_VALID_SOURCES)


def fed_configured() -> bool:
    for key in ("PG_CORPUS_FED_HOST", "PG_CORPUS_FED_DATABASE", "PG_CORPUS_FED_DB"):
        if setting_str(key):
            return True
    return False


def community_manual_configured() -> bool:
    return bool(setting_str(f"{_PREFIX}TOKEN") or setting_str(f"{_PREFIX}COMMUNITY_TOKEN")) and bool(
        setting_str(f"{_PREFIX}COMMUNITY_API_BASE")
    )


def persisted_community_configured() -> bool:
    from pallas.product.corpus.store import corpus_community_enrollment_valid

    return corpus_community_enrollment_valid()


def community_configured() -> bool:
    return community_manual_configured() or persisted_community_configured()


def auto_enroll_enabled() -> bool:
    """是否自动向社区登记语料凭证。

    ``true`` / ``false`` 强制开闭；``auto`` 表示跟随「使用社区共享接话库」：
    已显式开启共享语料时自动登记，避免 WebUI 默认 ``auto`` 被当成关闭导致
    多源状态一直显示未启用。
    """
    flag = parse_tristate(setting_str(f"{_PREFIX}AUTO_ENROLL", "false"), default=False)
    if flag is True:
        return True
    if flag is False:
        return False
    return is_community_corpus_wanted()


def is_community_corpus_wanted(cfg: CorpusConfig | None = None) -> bool:
    cfg = cfg or get_corpus_config()
    if cfg.community_enabled is False:
        return False
    if cfg.community_enabled is True:
        return True
    return community_manual_configured()


def resolve_enabled(flag: bool | None, *, configured: bool) -> bool:
    if flag is True:
        return True
    if flag is False:
        return False
    return configured


def resolved_community_api_base_urls() -> list[str]:
    manual = setting_str(f"{_PREFIX}COMMUNITY_API_BASE")
    if manual:
        return [manual.rstrip("/")]
    try:
        from pallas.product.community_stats.config import get_community_stats_config
        from pallas.product.community_stats.endpoints import corpus_api_base_urls_for_config, is_auto_endpoint_mode

        cs_cfg = get_community_stats_config()
        if is_auto_endpoint_mode(cs_cfg):
            urls = corpus_api_base_urls_for_config(cs_cfg)
            if urls:
                return urls
    except Exception:
        pass
    from pallas.product.corpus.store import load_corpus_community_state

    stored = str(load_corpus_community_state().get("api_base") or "").strip().rstrip("/")
    return [stored] if stored else []


def resolved_community_api_base() -> str:
    urls = resolved_community_api_base_urls()
    return urls[0] if urls else ""


def resolved_community_token() -> str:
    manual = setting_str(f"{_PREFIX}TOKEN") or setting_str(f"{_PREFIX}COMMUNITY_TOKEN")
    if manual:
        return manual
    from pallas.product.corpus.store import load_corpus_community_state

    return str(load_corpus_community_state().get("corpus_token") or "").strip()


def community_contribute_enabled(cfg: CorpusConfig | None = None) -> bool:
    """是否向社区池 mirror 学习结果"""
    flag = parse_tristate(setting_str(f"{_PREFIX}COMMUNITY_CONTRIBUTE", "auto"), default=True)
    if flag is True:
        return True
    if flag is False:
        return False
    from pallas.product.corpus.store import load_corpus_community_state

    state = load_corpus_community_state()
    if "contribute" in state and state.get("contribute") is not None:
        return bool(state.get("contribute"))
    return True


@lru_cache(maxsize=1)
def get_corpus_config() -> CorpusConfig:
    fed_flag = parse_tristate(setting_str(f"{_PREFIX}FED_ENABLED", "auto"))
    community_flag = parse_tristate(setting_str(f"{_PREFIX}COMMUNITY_ENABLED", "false"))
    auto_flag = parse_tristate(setting_str(f"{_PREFIX}AUTO_ENROLL", "false"), default=False)
    contrib_flag = parse_tristate(setting_str(f"{_PREFIX}COMMUNITY_CONTRIBUTE", "auto"), default=True)
    return CorpusConfig(
        merge_order=resolve_merge_order(setting_str(f"{_PREFIX}MERGE_ORDER", "local,fed,community")),
        merge_strategy=setting_str(f"{_PREFIX}MERGE_STRATEGY", "local_first") or "local_first",
        fed_enabled=fed_flag,
        community_enabled=community_flag,
        auto_enroll=auto_flag,
        fed_contribute=parse_tristate(setting_str(f"{_PREFIX}FED_CONTRIBUTE", "false"), default=False) is True,
        community_contribute=contrib_flag,
        on_remote_failure=setting_str(f"{_PREFIX}ON_REMOTE_FAILURE", "local_only") or "local_only",
        community_api_base=resolved_community_api_base(),
        community_token=resolved_community_token(),
    )


def clear_corpus_config_cache() -> None:
    get_corpus_config.cache_clear()


def corpus_composite_enabled(cfg: CorpusConfig | None = None) -> bool:
    cfg = cfg or get_corpus_config()
    fed_on = resolve_enabled(cfg.fed_enabled, configured=fed_configured())
    community_on = is_community_corpus_wanted(cfg) and (community_configured() or auto_enroll_enabled())
    return fed_on or community_on


def remote_corpus_find_mode(cfg: CorpusConfig | None = None) -> RemoteCorpusFindMode:
    """local 未命中时的远程语料策略（PALLAS_CORPUS_REMOTE_FIND_ENABLED）。

    - off：不拉远程
    - sync：热路径同步 HTTP 查社区并当场接话
    - prefetch：热路径仅本地；miss 时后台拉取并写入本地，下次再回
    """
    _ = cfg
    raw = setting_str(f"{_PREFIX}REMOTE_FIND_ENABLED", "auto").strip().lower()
    if raw == "sync":
        return "sync"
    if raw in ("true", "prefetch", "1", "yes", "on"):
        return "prefetch"
    return "off"


def remote_corpus_find_enabled(cfg: CorpusConfig | None = None) -> bool:
    """是否在 local 未命中时访问远程语料。"""
    return remote_corpus_find_mode(cfg) == "sync"
