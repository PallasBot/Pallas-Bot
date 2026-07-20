from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from ipaddress import ip_address
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pallas.core.foundation.config.repo_settings import (
    _atomic_write_text,
    repo_webui_settings_path,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence

GIT_MIRROR_SCOPES = ("bot", "webui", "community")

_DEFAULT_SCOPES = dict.fromkeys(GIT_MIRROR_SCOPES, "")
_DEFAULT_GIT_MIRROR_CONFIG: dict[str, object] = {
    "preferred_id": "github",
    "custom_proxy_prefix": "",
    "scopes": dict(_DEFAULT_SCOPES),
}


@dataclass(frozen=True, slots=True)
class MirrorSpec:
    id: str
    label: str
    type: str  # default | proxy
    clone_prefix: str
    raw_prefix: str
    api_prefix: str


def _proxy_mirror(mirror_id: str, label: str, proxy_base: str) -> MirrorSpec:
    base = proxy_base.rstrip("/")
    return MirrorSpec(
        id=mirror_id,
        label=label,
        type="proxy",
        clone_prefix=f"{base}/https://github.com",
        raw_prefix=f"{base}/https://raw.githubusercontent.com",
        api_prefix=f"{base}/https://api.github.com",
    )


BUILTIN_MIRRORS: tuple[MirrorSpec, ...] = (
    MirrorSpec(
        id="github",
        label="GitHub 官方",
        type="default",
        clone_prefix="https://github.com",
        raw_prefix="https://raw.githubusercontent.com",
        api_prefix="https://api.github.com",
    ),
    _proxy_mirror("ghproxy-vip", "ghproxy.vip", "https://ghproxy.vip"),
    _proxy_mirror("ghproxy-net", "ghproxy.net", "https://ghproxy.net"),
    _proxy_mirror("gh-proxy-com", "gh-proxy.com", "https://gh-proxy.com"),
    _proxy_mirror("github-akams", "github.akams.cn", "https://github.akams.cn"),
    _proxy_mirror("moeyy-gh", "moeyy.cn/gh-proxy", "https://moeyy.cn/gh-proxy"),
)


def validate_custom_proxy_prefix(prefix: str) -> str:
    raw = (prefix or "").strip().rstrip("/") + "/"
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("自定义前缀须为 https:// 公网地址")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise ValueError("自定义前缀禁止本地/内网主机")
    try:
        ip = ip_address(host)
        if not ip.is_global:
            raise ValueError("自定义前缀禁止私网 IP")
    except ValueError as e:
        if "私网" in str(e) or "禁止" in str(e):
            raise
        # hostname is a domain name — allow
    return raw.rstrip("/")


def rewrite_github_url(url: str, mirror: MirrorSpec) -> str:
    u = (url or "").strip()
    if not u or mirror.id == "github" or mirror.type == "default":
        return u
    for host, attr in (
        ("https://raw.githubusercontent.com", "raw_prefix"),
        ("https://api.github.com", "api_prefix"),
        ("https://github.com", "clone_prefix"),
    ):
        if u.startswith(host + "/") or u == host:
            rest = u[len(host) :]
            prefix = getattr(mirror, attr).rstrip("/")
            return prefix + rest
    return u


def _normalize_scopes(raw: object) -> dict[str, str]:
    out = dict(_DEFAULT_SCOPES)
    if not isinstance(raw, dict):
        return out
    for scope in GIT_MIRROR_SCOPES:
        val = raw.get(scope)
        if val is None:
            continue
        out[scope] = str(val).strip()
    return out


def load_git_mirror_config() -> dict[str, object]:
    path = repo_webui_settings_path()
    if not path.is_file():
        return {
            "preferred_id": _DEFAULT_GIT_MIRROR_CONFIG["preferred_id"],
            "custom_proxy_prefix": _DEFAULT_GIT_MIRROR_CONFIG["custom_proxy_prefix"],
            "scopes": dict(_DEFAULT_SCOPES),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "preferred_id": _DEFAULT_GIT_MIRROR_CONFIG["preferred_id"],
            "custom_proxy_prefix": _DEFAULT_GIT_MIRROR_CONFIG["custom_proxy_prefix"],
            "scopes": dict(_DEFAULT_SCOPES),
        }
    if not isinstance(data, dict):
        return {
            "preferred_id": _DEFAULT_GIT_MIRROR_CONFIG["preferred_id"],
            "custom_proxy_prefix": _DEFAULT_GIT_MIRROR_CONFIG["custom_proxy_prefix"],
            "scopes": dict(_DEFAULT_SCOPES),
        }
    section = data.get("git_mirror")
    if not isinstance(section, dict):
        return {
            "preferred_id": _DEFAULT_GIT_MIRROR_CONFIG["preferred_id"],
            "custom_proxy_prefix": _DEFAULT_GIT_MIRROR_CONFIG["custom_proxy_prefix"],
            "scopes": dict(_DEFAULT_SCOPES),
        }
    return {
        "preferred_id": str(section.get("preferred_id") or _DEFAULT_GIT_MIRROR_CONFIG["preferred_id"]),
        "custom_proxy_prefix": str(section.get("custom_proxy_prefix") or ""),
        "scopes": _normalize_scopes(section.get("scopes")),
    }


def save_git_mirror_config(
    preferred_id: str,
    custom_proxy_prefix: str = "",
    scopes: dict[str, str] | None = None,
) -> None:
    path = repo_webui_settings_path()
    doc: dict = {"env": {}}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                doc = data
        except (json.JSONDecodeError, OSError):
            pass
    if not isinstance(doc.get("env"), dict):
        doc["env"] = {}
    existing = doc.get("git_mirror") if isinstance(doc.get("git_mirror"), dict) else {}
    merged_scopes = _normalize_scopes(existing.get("scopes") if isinstance(existing, dict) else None)
    if scopes is not None:
        merged_scopes = _normalize_scopes({**merged_scopes, **scopes})
    doc["git_mirror"] = {
        "preferred_id": preferred_id,
        "custom_proxy_prefix": custom_proxy_prefix,
        "scopes": merged_scopes,
    }
    _atomic_write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def mirror_by_id(mirror_id: str) -> MirrorSpec | None:
    for mirror in BUILTIN_MIRRORS:
        if mirror.id == mirror_id:
            return mirror
    return None


def mirror_from_custom_prefix(prefix: str) -> MirrorSpec:
    validated = validate_custom_proxy_prefix(prefix)
    return MirrorSpec(
        id="custom",
        label="自定义代理",
        type="proxy",
        clone_prefix=f"{validated}/https://github.com",
        raw_prefix=f"{validated}/https://raw.githubusercontent.com",
        api_prefix=f"{validated}/https://api.github.com",
    )


def resolve_mirror_by_preferred_id(preferred_id: str, custom_proxy_prefix: str = "") -> MirrorSpec:
    pid = (preferred_id or "").strip()
    if pid == "custom":
        prefix = (custom_proxy_prefix or "").strip()
        if prefix:
            try:
                return mirror_from_custom_prefix(prefix)
            except ValueError:
                pass
        return mirror_by_id("github") or BUILTIN_MIRRORS[0]
    mirror = mirror_by_id(pid)
    if mirror is not None:
        return mirror
    return mirror_by_id("github") or BUILTIN_MIRRORS[0]


def resolve_preferred_mirror() -> MirrorSpec:
    cfg = load_git_mirror_config()
    return resolve_mirror_by_preferred_id(
        str(cfg["preferred_id"]),
        custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
    )


def resolve_mirror_for_scope(scope: str) -> MirrorSpec:
    cfg = load_git_mirror_config()
    scopes = _normalize_scopes(cfg.get("scopes"))
    scope_id = (scopes.get(scope) or "").strip()
    if not scope_id:
        scope_id = str(cfg["preferred_id"])
    return resolve_mirror_by_preferred_id(
        scope_id,
        custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
    )


def git_instead_of_args(mirror: MirrorSpec) -> list[str]:
    if mirror.id == "github" or mirror.type == "default":
        return []
    prefix = mirror.clone_prefix.rstrip("/") + "/"
    return ["-c", f"url.{prefix}.insteadOf=https://github.com/"]


def iter_mirrors_for_failover(scope: str | None = None) -> Iterator[MirrorSpec]:
    seen: set[str] = set()
    ordered: list[MirrorSpec] = []

    def add(mirror: MirrorSpec) -> None:
        if mirror.id in seen:
            return
        seen.add(mirror.id)
        ordered.append(mirror)

    if scope and scope in GIT_MIRROR_SCOPES:
        add(resolve_mirror_for_scope(scope))
    else:
        add(resolve_preferred_mirror())

    for mirror in BUILTIN_MIRRORS:
        if mirror.type == "proxy" and mirror.id not in seen:
            add(mirror)

    github = mirror_by_id("github")
    if github is not None and github.id not in seen:
        add(github)

    yield from ordered


async def request_with_mirrors[T](
    url: str,
    mirrors: Sequence[MirrorSpec] | Iterable[MirrorSpec],
    getter: Callable[[str], Awaitable[T]],
) -> T:
    last_exc: Exception | None = None
    for mirror in mirrors:
        rewritten = rewrite_github_url(url, mirror)
        try:
            return await getter(rewritten)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError("无可用镜像源")


_GITHUB_HTTPS = "https://github.com/"
_PROBE_RAW_URL = "https://raw.githubusercontent.com/PallasBot/Pallas-Bot/main/README.md"
_GIT_CMD_TIMEOUT_S = 60.0
_BOT_CANONICAL = "https://github.com/PallasBot/Pallas-Bot"


def detect_mirror_id(remote_url: str) -> str:
    u = (remote_url or "").strip()
    if not u:
        return "unknown"
    if u.startswith("git@"):
        return "ssh"
    proxy_mirrors = [m for m in BUILTIN_MIRRORS if m.type == "proxy"]
    for mirror in sorted(proxy_mirrors, key=lambda m: len(m.clone_prefix), reverse=True):
        if u.startswith(mirror.clone_prefix):
            return mirror.id
    if u.startswith(("https://github.com/", "http://github.com/")):
        return "github"
    if "/https://github.com/" in u:
        return "custom"
    canonical = canonical_github_https_url(u)
    if canonical and canonical.startswith(_GITHUB_HTTPS):
        return "github"
    return "unknown"


def canonical_github_https_url(remote_url: str) -> str | None:
    u = (remote_url or "").strip()
    if not u:
        return None
    if u.startswith("git@"):
        host_part, _, path = u.partition(":")
        if host_part.lower() != "git@github.com" or not path:
            return None
        return f"{_GITHUB_HTTPS}{path.lstrip('/')}".rstrip("/")
    if not u.startswith(("https://", "http://")):
        return None
    if u.startswith(("https://github.com/", "http://github.com/")):
        return f"{_GITHUB_HTTPS}{u.split('github.com/', 1)[1]}".rstrip("/")
    proxy_mirrors = [m for m in BUILTIN_MIRRORS if m.type == "proxy"]
    for mirror in sorted(proxy_mirrors, key=lambda m: len(m.clone_prefix), reverse=True):
        prefix = mirror.clone_prefix.rstrip("/") + "/"
        if u.startswith(prefix):
            rest = u[len(prefix) :].lstrip("/")
            if rest.startswith("https://github.com/"):
                return rest.rstrip("/")
            return f"{_GITHUB_HTTPS}{rest}".rstrip("/")
    marker = "/https://github.com/"
    idx = u.find(marker)
    if idx >= 0:
        return u[idx + 1 :].rstrip("/")
    return None


def mirror_option_dict(mirror: MirrorSpec) -> dict[str, str]:
    return {"id": mirror.id, "label": mirror.label, "type": mirror.type}


def available_mirrors_for_config() -> list[dict[str, str]]:
    cfg = load_git_mirror_config()
    options = [mirror_option_dict(mirror) for mirror in BUILTIN_MIRRORS]
    custom_prefix = str(cfg.get("custom_proxy_prefix") or "").strip()
    if custom_prefix:
        try:
            options.append(mirror_option_dict(mirror_from_custom_prefix(custom_prefix)))
        except ValueError:
            pass
    return options


def run_git_command_sync(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
    if shutil.which("git") is None:
        return 127, "", "未找到 git 命令"
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_CMD_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "git 命令超时"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    return int(proc.returncode or 0), out, err


def list_community_plugin_git_info() -> list[dict[str, object]]:
    from pallas.console.webui.community_plugin_install import community_plugins_root

    root = community_plugins_root()
    if not root.is_dir() or shutil.which("git") is None:
        return []

    rows: list[dict[str, object]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        plugin_id = entry.name
        rel_path = f"local/plugins/{plugin_id}"
        is_git_repo = False
        remote_url = ""
        code, out, _ = run_git_command_sync("rev-parse", "--is-inside-work-tree", cwd=str(entry))
        if code == 0 and out.lower() == "true":
            is_git_repo = True
            code2, origin, _ = run_git_command_sync("remote", "get-url", "origin", cwd=str(entry))
            if code2 == 0:
                remote_url = origin
        rows.append({
            "id": plugin_id,
            "kind": "plugin",
            "path": rel_path,
            "remote_url": remote_url,
            "is_git_repo": is_git_repo,
            "mirror": detect_mirror_id(remote_url) if remote_url else "unknown",
            "can_apply_remote": is_git_repo,
        })
    return rows


def bot_git_info() -> dict[str, object]:
    from pallas.core.foundation.bot_version import pallas_bot_repo_root

    root = pallas_bot_repo_root()
    scope_mirror = resolve_mirror_for_scope("bot")
    row: dict[str, object] = {
        "id": "bot",
        "kind": "bot",
        "label": "Bot 本体",
        "path": str(root),
        "remote_url": "",
        "is_git_repo": False,
        "mirror": scope_mirror.id,
        "can_apply_remote": False,
        "scope_id": scope_mirror.id,
        "note": "Docker / 非 git 部署请用镜像更新；含 packages/ 官方插件",
    }
    if shutil.which("git") is None:
        return row
    code, out, _ = run_git_command_sync("rev-parse", "--is-inside-work-tree", cwd=str(root))
    if code != 0 or out.lower() != "true":
        return row
    row["is_git_repo"] = True
    row["can_apply_remote"] = True
    row["note"] = "git 工作副本；packages/ 官方插件随本仓库更新，无独立 remote"
    code2, origin, _ = run_git_command_sync("remote", "get-url", "origin", cwd=str(root))
    if code2 == 0 and origin:
        row["remote_url"] = origin
        row["mirror"] = detect_mirror_id(origin)
    return row


def official_plugins_target_info() -> dict[str, object]:
    scope_mirror = resolve_mirror_for_scope("bot")
    return {
        "id": "official_plugins",
        "kind": "official",
        "label": "官方插件",
        "path": "packages/（pb_* 等内核插件）",
        "remote_url": "",
        "is_git_repo": False,
        "mirror": scope_mirror.id,
        "can_apply_remote": False,
        "scope_id": scope_mirror.id,
        "note": "随 Bot 仓库 / Docker 镜像更新，使用上方「Bot 更新」scope，无独立 git remote",
    }


def webui_target_info() -> dict[str, object]:
    scope_mirror = resolve_mirror_for_scope("webui")
    return {
        "id": "webui",
        "kind": "webui",
        "label": "WebUI dist",
        "path": "GitHub Releases",
        "remote_url": "",
        "is_git_repo": False,
        "mirror": scope_mirror.id,
        "can_apply_remote": False,
        "scope_id": scope_mirror.id,
        "note": "仅影响 Release / dist 下载，无 git remote 可改写",
    }


def build_git_mirror_info() -> dict[str, object]:
    cfg = load_git_mirror_config()
    scopes = _normalize_scopes(cfg.get("scopes"))
    return {
        "preferred_id": cfg["preferred_id"],
        "custom_proxy_prefix": cfg["custom_proxy_prefix"],
        "scopes": scopes,
        "available_mirrors": available_mirrors_for_config(),
        "targets": [bot_git_info(), official_plugins_target_info(), webui_target_info()],
        "plugins": list_community_plugin_git_info(),
    }


def _set_origin_url(repo_cwd: str, new_url: str) -> tuple[bool, str]:
    code, out, err = run_git_command_sync("remote", "set-url", "origin", new_url, cwd=repo_cwd)
    if code != 0:
        return False, err or out or "git remote set-url 失败"
    return True, "已更新 origin"


def apply_mirror_to_plugin(plugin_id: str, mirror: MirrorSpec | None = None) -> dict[str, object]:
    from pallas.console.webui.community_plugin_install import (
        CommunityPluginInstallError,
        community_plugins_root,
        validate_plugin_id,
    )

    mirror = mirror or resolve_mirror_for_scope("community")
    try:
        pid = validate_plugin_id(plugin_id)
    except CommunityPluginInstallError as e:
        return {"id": (plugin_id or "").strip(), "success": False, "message": e.detail}

    plugin_path = community_plugins_root() / pid
    if not plugin_path.is_dir():
        return {"id": pid, "success": False, "message": f"local/plugins/{pid} 不存在"}

    code, out, err = run_git_command_sync("rev-parse", "--is-inside-work-tree", cwd=str(plugin_path))
    if code != 0 or out.lower() != "true":
        return {"id": pid, "success": False, "message": "不是 git 仓库"}

    code, remote_url, err = run_git_command_sync("remote", "get-url", "origin", cwd=str(plugin_path))
    if code != 0 or not remote_url:
        detail = err or out or "无法读取 origin remote"
        return {"id": pid, "success": False, "message": detail}

    canonical = canonical_github_https_url(remote_url)
    if canonical is None:
        return {"id": pid, "success": False, "message": "仅支持 GitHub 仓库的镜像切换"}

    new_url = rewrite_github_url(canonical, mirror)
    if new_url == remote_url:
        return {
            "id": pid,
            "success": True,
            "message": "remote 已是目标镜像",
            "remote_url": remote_url,
        }

    ok, detail = _set_origin_url(str(plugin_path), new_url)
    if not ok:
        return {"id": pid, "success": False, "message": detail}

    return {"id": pid, "success": True, "message": "已更新 origin", "remote_url": new_url}


def apply_mirror_to_bot(mirror: MirrorSpec | None = None) -> dict[str, object]:
    from pallas.core.foundation.bot_version import pallas_bot_repo_root

    mirror = mirror or resolve_mirror_for_scope("bot")
    root = pallas_bot_repo_root()
    code, out, err = run_git_command_sync("rev-parse", "--is-inside-work-tree", cwd=str(root))
    if code != 0 or out.lower() != "true":
        return {
            "id": "bot",
            "success": False,
            "message": "当前目录不是 git 工作副本（例如 Docker 镜像部署）",
        }

    code, remote_url, err = run_git_command_sync("remote", "get-url", "origin", cwd=str(root))
    if code != 0 or not remote_url:
        return {"id": "bot", "success": False, "message": err or out or "无法读取 origin remote"}

    canonical = canonical_github_https_url(remote_url) or _BOT_CANONICAL
    new_url = rewrite_github_url(canonical, mirror)
    if new_url == remote_url:
        return {
            "id": "bot",
            "success": True,
            "message": "remote 已是目标镜像",
            "remote_url": remote_url,
        }

    ok, detail = _set_origin_url(str(root), new_url)
    if not ok:
        return {"id": "bot", "success": False, "message": detail}
    return {"id": "bot", "success": True, "message": "已更新 origin", "remote_url": new_url}


def apply_mirror_to_community_plugins(mirror: MirrorSpec | None = None) -> dict[str, object]:
    mirror = mirror or resolve_mirror_for_scope("community")
    plugins = list_community_plugin_git_info()
    results: list[dict[str, object]] = []
    for row in plugins:
        if not row.get("is_git_repo"):
            results.append({"id": row["id"], "success": False, "message": "不是 git 仓库"})
            continue
        results.append(apply_mirror_to_plugin(str(row["id"]), mirror=mirror))
    success_count = sum(1 for item in results if item.get("success"))
    return {
        "results": results,
        "summary": {
            "total": len(results),
            "success_count": success_count,
            "fail_count": len(results) - success_count,
        },
    }


def apply_mirror_to_all_targets(mirror: MirrorSpec | None = None) -> dict[str, object]:
    """应用 Bot remote + 社区插件 remotes；WebUI 仅靠 scope 偏好，无 remote。"""
    preferred = mirror or resolve_preferred_mirror()
    results: list[dict[str, object]] = [apply_mirror_to_bot(preferred)]
    community = apply_mirror_to_community_plugins(preferred)
    results.extend(community.get("results") or [])
    success_count = sum(1 for item in results if item.get("success"))
    return {
        "results": results,
        "summary": {
            "total": len(results),
            "success_count": success_count,
            "fail_count": len(results) - success_count,
        },
    }


async def probe_preferred_mirror(mirror_id: str | None = None) -> dict[str, object]:
    import httpx

    cfg = load_git_mirror_config()
    if mirror_id:
        mirror = resolve_mirror_by_preferred_id(
            mirror_id,
            custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
        )
    else:
        mirror = resolve_preferred_mirror()
    url = rewrite_github_url(_PROBE_RAW_URL, mirror)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            resp = await client.head(url)
            if resp.status_code >= 400:
                resp = await client.get(url)
            resp.raise_for_status()
        return {"ok": True, "mirror_id": mirror.id}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "mirror_id": mirror.id, "error": str(e)}
