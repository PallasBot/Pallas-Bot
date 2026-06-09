from __future__ import annotations

from pathlib import Path

from nonebot import get_driver, logger

_hook_installed = False

LOCAL_SOURCE_LABELS = {
    "env_substrings": "环境变量子串",
    "lexicon_file": "词表文件",
    "lexicon_path_invalid": "词表路径无效",
    "extra_substrings": "额外子串",
}

PROVIDER_LABELS = {
    "baidu": "百度",
    "json_http": "自建 HTTP",
}


def _lexicon_file_readable(path: str) -> bool:
    return Path(path).is_file()


def format_local_sources(bits: list[str]) -> str:
    if not bits:
        return "无"
    return "、".join(LOCAL_SOURCE_LABELS.get(bit, bit) for bit in bits)


def format_provider_chain(ids: list[str]) -> str:
    if not ids:
        return "无"
    return " → ".join(PROVIDER_LABELS.get(pid, pid) for pid in ids)


def format_remote_chain_summary(
    *,
    key_present: bool,
    providers_raw: str,
    chain_ids: list[str],
) -> tuple[str, str]:
    if key_present:
        mode = "显式配置"
        if not providers_raw.strip():
            chain = "无（已显式关闭远程审查）"
        elif chain_ids:
            chain = format_provider_chain(chain_ids)
        else:
            chain = "无可用提供者（请检查百度密钥或自建 URL）"
    else:
        mode = "自动推断"
        chain = format_provider_chain(chain_ids) if chain_ids else "无"
    return mode, chain


def format_api_fail_behavior(fail_open: bool) -> str:
    return "放行" if fail_open else "拦截"


def install_message_scrub_startup_log() -> None:
    global _hook_installed
    if _hook_installed:
        return
    try:
        driver = get_driver()
    except ValueError:
        return
    _hook_installed = True

    @driver.on_startup
    async def _message_scrub_log_config_on_startup() -> None:
        from src.platform.bot_runtime.roles import is_sharded_worker

        if is_sharded_worker():
            return

        from .api_chain import build_review_providers
        from .config import get_message_scrub_config

        cfg = get_message_scrub_config()

        local_bits: list[str] = []
        if cfg.inbound_filter_substrings:
            local_bits.append("env_substrings")
        if cfg.scrub_lexicon_path:
            if _lexicon_file_readable(cfg.scrub_lexicon_path):
                local_bits.append("lexicon_file")
            else:
                local_bits.append("lexicon_path_invalid")
                logger.warning("message_scrub: 词表路径不可读：{}", cfg.scrub_lexicon_path)
        if cfg.scrub_lexicon_extra:
            local_bits.append("extra_substrings")

        if cfg.scrub_baidu_api_key and not cfg.scrub_baidu_secret_key:
            logger.warning("message_scrub: 百度审查未启用（已配置 API_KEY，缺少 SECRET_KEY）")
        if cfg.scrub_baidu_secret_key and not cfg.scrub_baidu_api_key:
            logger.warning("message_scrub: 百度审查未启用（已配置 SECRET_KEY，缺少 API_KEY）")

        providers = build_review_providers()
        chain_ids = [p.id for p in providers]
        remote_mode, remote_chain = format_remote_chain_summary(
            key_present=cfg.scrub_review_providers_key_present,
            providers_raw=cfg.scrub_review_providers or "",
            chain_ids=chain_ids,
        )

        intercept_on = bool(local_bits) or bool(chain_ids)
        filter_status = "已启用" if intercept_on else "未启用（无本地规则且无远程审查）"
        local_desc = format_local_sources(local_bits)
        fail_behavior = format_api_fail_behavior(cfg.inbound_filter_api_fail_open)

        logger.info(
            "message_scrub 启动配置 · 入站过滤：{} · 本地来源：{} · 远程审查：{}（{}） · 远程超时：{} 秒 · 失败时{}",
            filter_status,
            local_desc,
            remote_mode,
            remote_chain,
            cfg.inbound_filter_api_timeout_sec,
            fail_behavior,
        )
