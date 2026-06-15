from __future__ import annotations

from dataclasses import dataclass

from nonebot import get_driver

from src.console.web import public_base_url as nonebot_public_base_url
from src.platform.shard import context as shard_ctx

from .config import Config, get_maa_config


def normalize_http_path(path: str) -> str:
    p = (path or "").strip()
    if not p.startswith("/"):
        p = f"/{p}"
    return p


def normalize_public_base_url(raw: str) -> str | None:
    s = (raw or "").strip().rstrip("/")
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        s = f"http://{s}"
    return s


def normalize_full_endpoint(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        s = f"http://{s}"
    return s


@dataclass(frozen=True, slots=True)
class MaaHttpEndpoints:
    get_task_url: str
    report_status_url: str
    inferred_base: bool


def maa_public_http_base(cfg: Config) -> tuple[str, bool]:
    """对外基址；分片未配置时回退 hub 端口。"""
    configured = normalize_public_base_url(cfg.maa_public_base_url)
    if configured:
        return configured, False
    from src.platform.shard.registry.config import get_shard_registry_settings

    if shard_ctx.sharding_active():
        s = get_shard_registry_settings()
        host = (s.ws_host or "127.0.0.1").strip() or "127.0.0.1"
        return nonebot_public_base_url(host=host, port=s.hub_port), True
    dconf = get_driver().config
    return (
        nonebot_public_base_url(host=getattr(dconf, "host", None), port=getattr(dconf, "port", None)),
        True,
    )


def resolve_maa_http_endpoints(cfg: Config | None = None) -> MaaHttpEndpoints:
    cfg = cfg if cfg is not None else get_maa_config()
    get_path = normalize_http_path(cfg.maa_get_task_path)
    report_path = normalize_http_path(cfg.maa_report_status_path)

    get_override = normalize_full_endpoint(cfg.maa_get_task_endpoint)
    report_override = normalize_full_endpoint(cfg.maa_report_status_endpoint)
    if get_override and report_override:
        return MaaHttpEndpoints(get_override, report_override, inferred_base=False)

    base, inferred = maa_public_http_base(cfg)

    if get_override:
        get_url = get_override
    else:
        get_url = f"{base}{get_path}"
    if report_override:
        report_url = report_override
    else:
        report_url = f"{base}{report_path}"
    return MaaHttpEndpoints(get_url, report_url, inferred)


def resolve_maa_process_http_endpoints(cfg: Config | None = None) -> MaaHttpEndpoints:
    """本进程 NoneBot 监听地址 + 路径。"""
    cfg = cfg if cfg is not None else get_maa_config()
    get_path = normalize_http_path(cfg.maa_get_task_path)
    report_path = normalize_http_path(cfg.maa_report_status_path)

    get_override = normalize_full_endpoint(cfg.maa_get_task_endpoint)
    report_override = normalize_full_endpoint(cfg.maa_report_status_endpoint)
    if get_override and report_override:
        return MaaHttpEndpoints(get_override, report_override, inferred_base=False)

    dconf = get_driver().config
    base = nonebot_public_base_url(host=getattr(dconf, "host", None), port=getattr(dconf, "port", None))
    get_url = get_override or f"{base}{get_path}"
    report_url = report_override or f"{base}{report_path}"
    return MaaHttpEndpoints(get_url, report_url, inferred_base=True)


def resolve_maa_probe_http_endpoints(cfg: Config | None = None) -> MaaHttpEndpoints:
    """连通性探测：与 MAA 客户端轮询地址一致。"""
    return resolve_maa_http_endpoints(cfg)


def format_maa_http_setup_help() -> str:
    ep = resolve_maa_http_endpoints()
    lines = [
        "在 MAA「设置 → 远程控制」填写（POST JSON）：",
        f"获取任务端点：{ep.get_task_url}",
        f"汇报任务端点：{ep.report_status_url}",
        "用户标识符：你的 QQ 号（与绑定命令一致）。",
    ]
    if ep.inferred_base:
        shard_hint = (
            "分片时请配置 maa_public_base_url 为 hub 对外地址（未填则按 hub 端口推断）。"
            if shard_ctx.sharding_active()
            else ""
        )
        lines.append(
            "当前地址由 NoneBot 的 host/port 推断，仅适合本机调试；"
            "对外部署一般只需配置 maa_public_base_url（与默认路径自动拼接）。"
            f"{shard_hint}"
            "仅在特殊反代场景再单独填写 maa_get_task_endpoint、maa_report_status_endpoint。"
        )
    return "\n\n".join(lines)
