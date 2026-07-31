"""本机 Embedding 辅进程：消费 Redis 队列，只在本进程加载 fastembed。"""

from __future__ import annotations

import os
import signal

from nonebot import logger

from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
from pallas.product.llm.config import clear_llm_config_cache, get_llm_config
from pallas.product.llm.knowledge.embed_redis import complete_embed_job, pop_embed_job, redis_embed_available
from pallas.product.llm.knowledge.embedding_provider import (
    LocalFastEmbedProvider,
    clear_embedding_provider_cache,
    resolve_embedding_provider_name,
    resolve_local_embedding_model,
)


def _run_loop() -> int:
    apply_repo_settings_to_environ()
    os.environ["PALLAS_BOT_ROLE"] = "embed"
    clear_llm_config_cache()
    clear_embedding_provider_cache()
    if not redis_embed_available():
        logger.error("embed worker: REDIS_URL / coord Redis 不可用，退出")
        return 1
    cfg = get_llm_config()
    if resolve_embedding_provider_name(cfg) != "local":
        logger.error("embed worker: 当前不是 local Embedding，退出")
        return 1
    provider = LocalFastEmbedProvider(cfg=cfg)
    model = resolve_local_embedding_model(cfg)
    logger.info("embed worker started model={}", model)
    # 预热模型，避免首条任务尖刺
    try:
        provider.embed_sync(["ping"], timeout_sec=60.0)
    except Exception as exc:
        logger.warning("embed worker warm-up failed: {}", exc)

    stopping = False

    def _stop(*_args) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stopping:
        job = pop_embed_job(timeout_sec=2.0)
        if job is None:
            continue
        texts = [str(t or "").strip() for t in (job.get("texts") or [])]
        texts = [t for t in texts if t]
        if not texts:
            continue
        job_model = str(job.get("model") or "").strip() or model
        if job_model != model:
            logger.warning("embed worker model mismatch job={} live={}", job_model, model)
        try:
            vectors = provider.embed_sync(texts, timeout_sec=60.0)
        except Exception as exc:
            logger.warning("embed worker embed failed: {}", exc)
            continue
        complete_embed_job({**job, "model": model}, vectors)
    logger.info("embed worker stopped")
    return 0


def main() -> None:
    raise SystemExit(_run_loop())


if __name__ == "__main__":
    main()
