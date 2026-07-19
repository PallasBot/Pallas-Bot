"""AI 扩展日志路径解析与 kind 映射（Bot 侧跟读本地文件）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

AiExtensionLogKind = Literal["uvicorn", "celery", "celery-media"]

AI_EXTENSION_LOG_KINDS: tuple[AiExtensionLogKind, ...] = ("uvicorn", "celery", "celery-media")

UVICORN_LOG_FILENAMES: tuple[str, ...] = ("uvicorn.log", "api.log", "app.log")
CELERY_LOG_FILENAMES: tuple[str, ...] = ("celery.log",)
CELERY_MEDIA_LOG_FILENAMES: tuple[str, ...] = ("celery-media.log",)

DOCKER_AI_LOGS_MOUNT = Path("/ai-logs")


def default_ai_repo_root(bot_repo_root: Path | None = None) -> Path:
    root = bot_repo_root or Path(__file__).resolve().parents[3]
    return (root.parent / "Pallas-Bot-AI").resolve()


def ai_extension_log_roots(bot_repo_root: Path | None = None) -> list[Path]:
    """Bot 可读日志根：本仓、同级 AI 仓、Docker 共享卷 /ai-logs。"""
    root = (bot_repo_root or Path(__file__).resolve().parents[3]).resolve()
    ai_root = default_ai_repo_root(root)
    roots = [root, ai_root]
    docker_mount = DOCKER_AI_LOGS_MOUNT
    if docker_mount.is_dir():
        roots.append(docker_mount.resolve())
    return roots


def is_allowed_log_path(path_s: str, allowed_roots: list[Path] | None = None) -> bool:
    s = (path_s or "").strip()
    if not s:
        return False
    try:
        p = Path(s).resolve()
    except (OSError, RuntimeError):
        return False
    roots = allowed_roots if allowed_roots is not None else ai_extension_log_roots()
    for root in roots:
        try:
            if p == root or p.is_relative_to(root):
                return True
        except (OSError, RuntimeError):
            continue
    return False


def log_path_candidates(ai_root: Path, filenames: tuple[str, ...]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for name in filenames:
        for base in (DOCKER_AI_LOGS_MOUNT, ai_root / "logs"):
            candidate = (base / name).resolve() if base.exists() else base / name
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def pick_existing_log_path(candidates: list[Path], allowed_roots: list[Path]) -> str:
    for candidate in candidates:
        if not is_allowed_log_path(str(candidate), allowed_roots):
            continue
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    for candidate in candidates:
        if is_allowed_log_path(str(candidate), allowed_roots):
            return str(candidate)
    if candidates:
        return str(candidates[0])
    return ""


def normalize_log_path_field(
    raw: str,
    candidates: list[Path],
    allowed_roots: list[Path],
) -> str:
    explicit = str(raw or "").strip()
    if explicit and is_allowed_log_path(explicit, allowed_roots):
        try:
            explicit_path = Path(explicit)
            if explicit_path.is_file():
                return str(explicit_path.resolve())
        except OSError:
            pass
    picked = pick_existing_log_path(candidates, allowed_roots)
    if picked:
        try:
            if Path(picked).is_file():
                return picked
        except OSError:
            pass
    if explicit and is_allowed_log_path(explicit, allowed_roots):
        return explicit
    return picked or explicit


def default_uvicorn_log_path(ai_root: Path, allowed_roots: list[Path]) -> str:
    return normalize_log_path_field("", log_path_candidates(ai_root, UVICORN_LOG_FILENAMES), allowed_roots)


def default_celery_log_path(ai_root: Path, allowed_roots: list[Path]) -> str:
    return normalize_log_path_field("", log_path_candidates(ai_root, CELERY_LOG_FILENAMES), allowed_roots)


def default_celery_media_log_path(ai_root: Path, allowed_roots: list[Path]) -> str:
    return normalize_log_path_field("", log_path_candidates(ai_root, CELERY_MEDIA_LOG_FILENAMES), allowed_roots)


def normalize_ai_extension_log_paths(
    raw: dict[str, Any] | None,
    *,
    bot_repo_root: Path | None = None,
) -> dict[str, str]:
    allowed_roots = ai_extension_log_roots(bot_repo_root)
    ai_root = default_ai_repo_root(bot_repo_root)
    d = raw or {}
    uvicorn = normalize_log_path_field(
        str(d.get("uvicorn_log_file", "")),
        log_path_candidates(ai_root, UVICORN_LOG_FILENAMES),
        allowed_roots,
    )
    celery = normalize_log_path_field(
        str(d.get("celery_log_file", "")),
        log_path_candidates(ai_root, CELERY_LOG_FILENAMES),
        allowed_roots,
    )
    celery_media = normalize_log_path_field(
        str(d.get("celery_media_log_file", "")),
        log_path_candidates(ai_root, CELERY_MEDIA_LOG_FILENAMES),
        allowed_roots,
    )
    return {
        "uvicorn_log_file": uvicorn,
        "celery_log_file": celery,
        "celery_media_log_file": celery_media,
    }


def resolve_log_path_for_kind(cfg: dict[str, Any], kind: str) -> str:
    if kind == "celery-media":
        return str(cfg.get("celery_media_log_file", ""))
    if kind == "celery":
        return str(cfg.get("celery_log_file", ""))
    return str(cfg.get("uvicorn_log_file", ""))


def ai_extension_base_url_is_local(base_url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse((base_url or "").strip()).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def ai_extension_log_missing_message(
    cfg: dict[str, Any],
    *,
    path_s: str = "",
    remote_tried: bool = False,
) -> str:
    base_url = str(cfg.get("base_url", "")).strip()
    path_hint = f"（{path_s}）" if path_s else ""
    if remote_tried:
        if base_url and not ai_extension_base_url_is_local(base_url):
            return (
                f"本机无日志{path_hint}，且无法从远端 AI 拉取。"
                "请确认 AI 服务在线、网络可达，并已升级到支持 /api/ops/logs 的版本。"
            )
        return f"本机无日志{path_hint}，且无法从 AI 服务 HTTP 拉取。请确认 AI 服务已启动并可访问。"
    if base_url and not ai_extension_base_url_is_local(base_url):
        return f"未找到 Bot 本机可读日志{path_hint}。将尝试通过 AI HTTP 接口拉取；若仍失败请检查 AI 服务连通性。"
    return (
        f"未找到本地 AI 日志文件{path_hint}。"
        "请确认 AI 服务已在本机启动，或将日志路径留空以自动探测同级 Pallas-Bot-AI/logs。"
    )
