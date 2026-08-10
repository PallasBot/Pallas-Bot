"""后台任务辅助进程入口。"""

from __future__ import annotations

import asyncio
from importlib import metadata

import nonebot
from nonebot import logger

from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
from pallas.core.platform.work_jobs.service import run_work_service


def repeater_work_handlers():
    from packages.repeater.work_handler import repeater_work_handlers as build_handlers

    return build_handlers()


def load_external_work_handlers(*, entry_points_getter=metadata.entry_points):
    handlers = {}
    for entry_point in entry_points_getter().select(group="pallas.work_handlers"):
        try:
            provider = entry_point.load()
            provided = provider()
            if not isinstance(provided, dict):
                raise TypeError("provider must return a dict")
            provider_handlers = {}
            for raw_kind, handler in provided.items():
                kind = str(raw_kind or "").strip()
                if not kind or not callable(handler):
                    raise TypeError("handler map must contain non-empty string kinds and callables")
                provider_handlers[kind] = handler
            for kind, handler in provider_handlers.items():
                if kind in handlers:
                    logger.warning(
                        "work aux: duplicate external handler ignored kind={} entry_point={}",
                        kind,
                        entry_point.name,
                    )
                    continue
                handlers[kind] = handler
        except Exception as exc:
            logger.warning(
                "work aux: external handler provider skipped entry_point={} value={}: {}",
                entry_point.name,
                entry_point.value,
                exc,
            )
    return handlers


def load_work_handlers():
    nonebot.init()
    handlers = repeater_work_handlers()
    for kind, handler in load_external_work_handlers().items():
        if kind in handlers:
            logger.warning("work aux: external handler conflicts with built-in kind={}", kind)
            continue
        handlers[kind] = handler
    return handlers


def main() -> None:
    apply_repo_settings_to_environ()
    asyncio.run(run_work_service(load_work_handlers()))


if __name__ == "__main__":
    main()
