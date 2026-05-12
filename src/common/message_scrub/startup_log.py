from __future__ import annotations

from pathlib import Path

from nonebot import get_driver, logger

_hook_installed = False


def _lexicon_file_readable(path: str) -> bool:
    return Path(path).is_file()


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
        from .api_chain import build_review_providers
        from .config import get_message_scrub_config

        cfg = get_message_scrub_config()

        local_bits: list[str] = []
        if cfg.inbound_filter_substrings:
            local_bits.append("环境子串")
        if cfg.scrub_lexicon_path:
            if _lexicon_file_readable(cfg.scrub_lexicon_path):
                local_bits.append("词表文件")
            else:
                local_bits.append("词表路径(无效)")
                logger.warning("message_scrub 词表路径不可读: {}", cfg.scrub_lexicon_path)
        if cfg.scrub_lexicon_extra:
            local_bits.append("追加词")

        if cfg.scrub_baidu_api_key and not cfg.scrub_baidu_secret_key:
            logger.warning("message_scrub 已配置 PALLAS_SCRUB_BAIDU_API_KEY 但未配置 SECRET，百度审查未启用")
        if cfg.scrub_baidu_secret_key and not cfg.scrub_baidu_api_key:
            logger.warning("message_scrub 已配置 PALLAS_SCRUB_BAIDU_SECRET_KEY 但未配置 API_KEY，百度审查未启用")

        providers = build_review_providers()
        chain_ids = [p.id for p in providers]

        if cfg.scrub_review_providers_key_present:
            chain_mode = "显式"
            if not (cfg.scrub_review_providers or "").strip():
                chain_desc = "无远程"
            else:
                chain_desc = ",".join(chain_ids) if chain_ids else "无生效项(请检查环境变量)"
        else:
            chain_mode = "自动"
            chain_desc = ",".join(chain_ids) if chain_ids else "无远程"

        local_on = bool(local_bits)
        remote_on = bool(chain_ids)
        intercept_on = local_on or remote_on

        local_human = "+".join(local_bits) if local_bits else "无"
        fail_policy = "远程异常时放行" if cfg.inbound_filter_api_fail_open else "远程异常时按拦截处理"

        logger.info(
            "message_scrub 启动: 消息拦截={} 本地={} 远程链({})={} {} 超时={}s",
            "已启用" if intercept_on else "未启用(无本地词库且无远程)",
            local_human,
            chain_mode,
            chain_desc,
            fail_policy,
            cfg.inbound_filter_api_timeout_sec,
        )
