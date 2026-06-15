import asyncio
import json
import os
import re
import secrets
import shutil
import socket
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from src.foundation.paths import resource_dir

from .backends import ProtocolRuntimeBackend, make_protocol_runtime_backend
from .config import (
    Config,
    instances_root_for,
    onebot_connection_hints,
    resolve_onebot_ws_settings,
)
from .config_manager import AccountConfigManager
from .contract import (
    ACCOUNT_PROTOCOL_BACKEND_KEY,
    DEFAULT_PROTOCOL_BACKEND,
    MANAGED_RUNTIME_TAG_KEY,
    SNOWLUMA_PROTOCOL_BACKEND,
)
from .docker_cli import (
    docker_repository_from_ref,
)
from .docker_cli import (
    docker_stderr_suggests_container_name_conflict as _docker_stderr_suggests_container_name_conflict,
)
from .docker_cli import (
    docker_stderr_suggests_host_port_bind_conflict as _docker_stderr_suggests_host_port_bind_conflict,
)
from .launch_manager import LaunchManager
from .runtime.installer import NapCatRuntimeStore, default_release_asset_for_platform, default_release_repo_for_platform
from .runtime.snowluma_installer import SnowLumaRuntimeStore, default_snowluma_asset_name_for_tag
from .snowluma_config import resolve_snowluma_webui_temp_password

_LINUX_RT_MODES = frozenset({"docker", "appimage", "shell"})


def _coerce_linux_runtime_mode(raw: object, default: str) -> str:
    m = str(raw or "").strip().lower()
    return m if m in _LINUX_RT_MODES else default


def _realpath_sync(path: str) -> str:
    return os.path.realpath(path)


@dataclass
class NapCatRuntime:
    process: asyncio.subprocess.Process | None = None
    started_at: datetime | None = None
    logs: deque[str] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    drain_task: asyncio.Task | None = None
    expect_bootmain_detach: bool = False
    tracked_child_root_pid: int | None = None
    docker_container_name: str | None = None


class PallasProtocolService:
    def __init__(self, data_dir: Path, config: Config) -> None:
        self._data_dir = data_dir
        self._resource_root = resource_dir()
        self._config = config
        self._instances_root = instances_root_for(self._data_dir, self._config)
        self._accounts_file = self._data_dir / "accounts.json"
        self._accounts: dict[str, dict] = {}
        self._runtimes: dict[str, NapCatRuntime] = {}
        self._runtime_store = NapCatRuntimeStore(data_dir, config)
        self._snowluma_store = SnowLumaRuntimeStore(data_dir, config)
        self._runtime_profile_path = self._data_dir / "runtime_profile.json"
        self._launch = LaunchManager(
            self._data_dir,
            self._resource_root,
            self._config,
            instances_root=self._instances_root,
            runtime_dir_provider=self._runtime_store.resolved_program_dir,
            snowluma_runtime_dir_provider=self._snowluma_store.resolved_program_dir,
            runtime_dir_for_account=self._napcat_runtime_dir_for_account,
            snowluma_runtime_dir_for_account=self._snowluma_runtime_dir_for_account,
            runtime_profile_provider=self.runtime_profile,
            snowluma_docker_allocate_host_ports=self._snowluma_docker_allocate_auto_host_ports,
        )
        self._configs = AccountConfigManager(
            self._config.pallas_protocol_bind_host,
            webui_port_fallback_min=int(getattr(self._config, "pallas_protocol_webui_port_min", 6099)),
        )

    def _protocol_runtime_backend(
        self, account: dict | None = None, *, kind: str | None = None
    ) -> ProtocolRuntimeBackend:
        raw = kind if kind is not None else (account or {}).get(ACCOUNT_PROTOCOL_BACKEND_KEY, "")
        slug = (str(raw).strip() if raw is not None else "") or DEFAULT_PROTOCOL_BACKEND
        return make_protocol_runtime_backend(self, slug)

    def effective_runtime_program_dir(self) -> Path | None:
        configured = str(getattr(self._config, "pallas_protocol_program_dir", "")).strip()
        if configured:
            p = Path(configured)
            return p if p.is_dir() else None
        return self._runtime_store.resolved_program_dir()

    def _default_runtime_mode(self) -> str:
        if os.name == "nt":
            return "shell"
        if sys.platform.startswith("linux"):
            if bool(getattr(self._config, "pallas_protocol_linux_use_docker", False)):
                return "docker"
            return "appimage"
        return "shell"

    def runtime_profile(self) -> dict[str, object]:
        default_sl_img = (
            str(getattr(self._config, "pallas_protocol_snowluma_docker_image", "") or "").strip()
            or "motricseven7/snowluma:latest"
        )
        def_mode = self._default_runtime_mode()
        default = {
            "runtime_mode": def_mode,
            "napcat_runtime_mode": def_mode,
            "snowluma_runtime_mode": def_mode,
            "target_platform": "auto",
            "docker_image": str(getattr(self._config, "pallas_protocol_docker_image", "") or "").strip()
            or "mlikiowa/napcat-docker:latest",
            "snowluma_docker_image": default_sl_img,
            "follow_bot_lifecycle": bool(getattr(self._config, "pallas_protocol_follow_bot_lifecycle", True)),
        }
        if not self._runtime_profile_path.exists():
            return default
        try:
            raw = json.loads(self._runtime_profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        if not isinstance(raw, dict):
            return default
        legacy = _coerce_linux_runtime_mode(raw.get("runtime_mode"), def_mode)
        nap = _coerce_linux_runtime_mode(raw.get("napcat_runtime_mode"), legacy)
        snow = _coerce_linux_runtime_mode(raw.get("snowluma_runtime_mode"), legacy)
        platform = str(raw.get("target_platform", "")).strip().lower()
        if platform not in ("auto", "linux-amd64", "linux-arm64", "windows-amd64"):
            platform = "auto"
        image = str(raw.get("docker_image", "")).strip() or default["docker_image"]
        sl_img = str(raw.get("snowluma_docker_image", "")).strip() or default["snowluma_docker_image"]
        follow = raw.get("follow_bot_lifecycle", default["follow_bot_lifecycle"])
        if isinstance(follow, str):
            follow = follow.strip().lower() in ("1", "true", "yes", "on")
        else:
            follow = bool(follow)
        return {
            "runtime_mode": nap,
            "napcat_runtime_mode": nap,
            "snowluma_runtime_mode": snow,
            "target_platform": platform,
            "docker_image": image,
            "snowluma_docker_image": sl_img,
            "follow_bot_lifecycle": follow,
        }

    def _apply_runtime_profile_to_config(self, profile: dict[str, object] | None = None) -> None:
        p = profile or self.runtime_profile()
        defm = self._default_runtime_mode()
        nap = _coerce_linux_runtime_mode(
            p.get("napcat_runtime_mode") or p.get("runtime_mode"),
            defm,
        )
        snow = _coerce_linux_runtime_mode(
            p.get("snowluma_runtime_mode") or p.get("runtime_mode"),
            defm,
        )
        image = str(p.get("docker_image", "")).strip() or "mlikiowa/napcat-docker:latest"
        sl_img = (
            str(p.get("snowluma_docker_image", "")).strip()
            or str(getattr(self._config, "pallas_protocol_snowluma_docker_image", "") or "").strip()
            or "motricseven7/snowluma:latest"
        )
        follow = p.get("follow_bot_lifecycle", True)
        if isinstance(follow, str):
            follow = follow.strip().lower() in ("1", "true", "yes", "on")
        else:
            follow = bool(follow)
        self._config.pallas_protocol_linux_use_docker = nap == "docker"
        if nap == "docker":
            self._config.pallas_protocol_docker_image = image
        self._config.pallas_protocol_snowluma_linux_use_docker = snow == "docker"
        self._config.pallas_protocol_snowluma_docker_image = sl_img
        self._config.pallas_protocol_follow_bot_lifecycle = bool(follow)

    async def update_runtime_profile(self, payload: dict) -> dict[str, object]:
        current = self.runtime_profile()
        defm = self._default_runtime_mode()
        has_split = "napcat_runtime_mode" in payload or "snowluma_runtime_mode" in payload
        if has_split:
            nap = _coerce_linux_runtime_mode(
                payload.get("napcat_runtime_mode", current["napcat_runtime_mode"]),
                str(current["napcat_runtime_mode"]),
            )
            snow = _coerce_linux_runtime_mode(
                payload.get("snowluma_runtime_mode", current["snowluma_runtime_mode"]),
                str(current["snowluma_runtime_mode"]),
            )
        else:
            leg = _coerce_linux_runtime_mode(
                payload.get("runtime_mode", current.get("runtime_mode")),
                defm,
            )
            nap = snow = leg
        platform = str(payload.get("target_platform", current["target_platform"])).strip().lower()
        if platform not in ("auto", "linux-amd64", "linux-arm64", "windows-amd64"):
            raise ValueError("target_platform 仅支持 auto/linux-amd64/linux-arm64/windows-amd64")
        image = str(payload.get("docker_image", current["docker_image"])).strip() or current["docker_image"]
        sl_image = str(payload.get("snowluma_docker_image", current.get("snowluma_docker_image", ""))).strip()
        if not sl_image:
            sl_image = str(current.get("snowluma_docker_image", "") or "").strip() or "motricseven7/snowluma:latest"
        follow = payload.get("follow_bot_lifecycle", current["follow_bot_lifecycle"])
        if isinstance(follow, str):
            follow = follow.strip().lower() in ("1", "true", "yes", "on")
        else:
            follow = bool(follow)
        updated = {
            "runtime_mode": nap,
            "napcat_runtime_mode": nap,
            "snowluma_runtime_mode": snow,
            "target_platform": platform,
            "docker_image": image,
            "snowluma_docker_image": sl_image,
            "follow_bot_lifecycle": follow,
        }
        self._runtime_profile_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        self._apply_runtime_profile_to_config(updated)
        prune = str(payload.get("prune_containers", "all")).strip().lower()
        if prune not in ("all", "napcat", "snowluma"):
            prune = "all"
        prev_nap = str(current.get("napcat_runtime_mode") or current.get("runtime_mode", "") or "").strip().lower()
        prev_snow = str(current.get("snowluma_runtime_mode") or current.get("runtime_mode", "") or "").strip().lower()
        if not prev_nap:
            prev_nap = defm
        if not prev_snow:
            prev_snow = defm
        nc_flip = (prev_nap == "docker") != (nap == "docker")
        sl_flip = (prev_snow == "docker") != (snow == "docker")
        if nc_flip and sl_flip and prune != "all":
            raise ValueError(
                "NapCat 与 SnowLuma 的运行模式均涉及 Docker 开关变化时，须选择「NapCat 与 SnowLuma 全部」"
                "：保存会先停进程并按范围删容器，仅选一侧无法同时清两套栈的旧容器。"
            )
        if nc_flip and prune not in ("all", "napcat"):
            raise ValueError(
                "NapCat 运行模式在 Docker 与非 Docker 间切换时，须选择「全部」或「仅 NapCat」作为容器清理范围。"
            )
        if sl_flip and prune not in ("all", "snowluma"):
            raise ValueError(
                "SnowLuma 运行模式在 Docker 与非 Docker 间切换时，须选择「全部」或「仅 SnowLuma」作为容器清理范围。"
            )
        await self._prune_all_protocol_docker_containers_after_runtime_profile_change(prune_containers=prune)
        return updated

    async def _prune_all_protocol_docker_containers_after_runtime_profile_change(
        self, *, prune_containers: str = "all"
    ) -> None:
        from nonebot import logger

        for account_id, account in list(self._accounts.items()):
            if not (account.get("napcat_linux_docker") or account.get("snowluma_linux_docker")):
                continue
            if prune_containers == "napcat" and not account.get("napcat_linux_docker"):
                continue
            if prune_containers == "snowluma" and not account.get("snowluma_linux_docker"):
                continue
            try:
                await self.stop_account(account_id)
            except Exception:
                logger.exception(f"Pallas-Bot 协议端: 全局 runtime 切换时停止账号 {account_id} 异常")
            try:
                if prune_containers == "all":
                    await self._remove_both_linux_docker_container_names_for_account(account)
                elif prune_containers == "napcat":
                    await self._remove_napcat_linux_docker_container_for_account(account)
                else:
                    await self._remove_snowluma_linux_docker_container_for_account(account)
            except Exception:
                logger.exception(f"Pallas-Bot 协议端: 全局 runtime 切换时删除 Docker 容器 {account_id} 异常")
        for account in self._accounts.values():
            self._launch.apply_defaults(account, self._resolve_qq)
            be = self._protocol_runtime_backend(account)
            be.prepare_dirs(account)
            be.sync_all_configs(account, self._resolve_qq)
            self._refresh_linux_docker_run_argv(account)
            account["updated_at"] = datetime.now(UTC).isoformat()
        self._save_accounts()

    def runtime_overview(self) -> dict:
        manifest = self._runtime_store.read_manifest()
        eff = self.effective_runtime_program_dir()
        profile = self.runtime_profile()
        target_platform = str(profile.get("target_platform", "auto") or "auto")
        raw_asset = str(getattr(self._config, "pallas_protocol_release_asset", "") or "").strip()
        raw_repo = str(getattr(self._config, "pallas_protocol_github_repo", "") or "").strip()
        if not raw_asset:
            resolved_asset = default_release_asset_for_platform(
                self._config.pallas_protocol_release_tag.strip() or "",
                target_platform=target_platform,
            )
        else:
            auto_asset = default_release_asset_for_platform()
            if target_platform != "auto" and raw_asset == auto_asset:
                resolved_asset = default_release_asset_for_platform(
                    self._config.pallas_protocol_release_tag.strip() or "",
                    target_platform=target_platform,
                )
            else:
                resolved_asset = raw_asset
        if not raw_repo:
            resolved_repo = default_release_repo_for_platform(target_platform)
        else:
            auto_repo = default_release_repo_for_platform("auto")
            resolved_repo = (
                default_release_repo_for_platform(target_platform)
                if (target_platform != "auto" and raw_repo == auto_repo)
                else raw_repo
            )
        return {
            "job": self._runtime_store.job_snapshot(),
            "manifest": manifest.to_json() if manifest else None,
            "effective_program_dir": str(eff) if eff else None,
            "profile": profile,
            "download": {
                "repo": resolved_repo,
                "asset": resolved_asset,
                "tag": self._config.pallas_protocol_release_tag.strip() or "latest",
            },
            "snowluma": self.snowluma_runtime_overview(),
        }

    def effective_snowluma_program_dir(self) -> Path | None:
        configured = str(getattr(self._config, "pallas_protocol_snowluma_program_dir", "") or "").strip()
        if configured:
            p = Path(configured)
            return p if p.is_dir() else None
        return self._snowluma_store.resolved_program_dir()

    def snowluma_runtime_overview(self) -> dict[str, object]:
        manifest = self._snowluma_store.read_manifest()
        eff = self.effective_snowluma_program_dir()
        raw_repo = (
            str(getattr(self._config, "pallas_protocol_snowluma_github_repo", "") or "").strip() or "SnowLuma/SnowLuma"
        )
        raw_asset = str(getattr(self._config, "pallas_protocol_snowluma_release_asset", "") or "").strip()
        raw_tag = str(getattr(self._config, "pallas_protocol_snowluma_release_tag", "") or "").strip()
        auto_name = default_snowluma_asset_name_for_tag(raw_tag) if raw_tag else ""
        resolved_asset = raw_asset or auto_name
        return {
            "job": self._snowluma_store.job_snapshot(),
            "manifest": manifest.to_json() if manifest else None,
            "effective_program_dir": str(eff) if eff else None,
            "download": {
                "repo": raw_repo,
                "asset": resolved_asset or None,
                "tag": raw_tag or "latest",
            },
        }

    def start_snowluma_runtime_download(
        self, *, tag: str | None = None, target_platform: str | None = None
    ) -> dict[str, object]:
        self._snowluma_store.start_background_download(
            tag=tag or None,
            target_platform=target_platform,
            on_success=lambda: self.sync_follow_global_runtime_paths_after_manifest_change(backend="snowluma"),
        )
        return self.snowluma_runtime_overview()

    async def fetch_snowluma_runtime_releases(self, *, limit: int = 10) -> list[dict]:
        return await self._snowluma_store.fetch_releases(limit=limit)

    def start_runtime_download(
        self, *, tag: str | None = None, target_platform: str | None = None, runtime_mode: str | None = None
    ) -> dict:
        profile = self.runtime_profile()
        mode = (
            str(
                runtime_mode or profile.get("napcat_runtime_mode") or profile.get("runtime_mode", ""),
            )
            .strip()
            .lower()
        )
        if mode == "docker":
            raise ValueError("Docker 模式请使用镜像拉取，无需通过本页下载发行包；请使用「NapCat Docker 镜像」拉取。")
        platform_hint = str(target_platform or profile.get("target_platform", "auto")).strip().lower()
        self._runtime_store.start_background_download(
            tag=tag,
            target_platform=platform_hint,
            on_success=lambda: self.sync_follow_global_runtime_paths_after_manifest_change(backend="napcat"),
        )
        return self.runtime_overview()

    async def pull_docker_image(self, image: str | None = None) -> dict[str, object]:
        profile = self.runtime_profile()
        img = str(image or profile.get("docker_image", "")).strip() or "mlikiowa/napcat-docker:latest"
        if not shutil.which("docker"):
            return {
                "ok": False,
                "image": img,
                "code": -1,
                "output": (
                    "未找到 docker 命令。默认 Bot 容器镜像不含 Docker CLI，且 compose 未挂载 docker.sock；"
                    "可在宿主机执行 docker pull 拉取 NapCat/SnowLuma 镜像，或按 docker-compose.yml 注释挂载 socket "
                    "并在镜像内安装 docker CLI。"
                ),
            }
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "pull",
                img,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
        except FileNotFoundError:
            return {
                "ok": False,
                "image": img,
                "code": -1,
                "output": "无法启动 docker 进程（未找到可执行文件）。",
            }
        except OSError as e:
            return {
                "ok": False,
                "image": img,
                "code": -1,
                "output": f"执行 docker pull 失败：{e}",
            }
        text = out.decode("utf-8", errors="replace") if out else ""
        return {
            "ok": proc.returncode == 0,
            "image": img,
            "code": proc.returncode,
            "output": text[-4000:],
        }

    async def list_local_docker_images(self, *, protocol: str | None = None) -> dict[str, object]:
        if not shutil.which("docker"):
            return {"ok": False, "detail": "未找到 docker 命令", "images": []}
        proto = str(protocol or "").strip().lower()
        want_repo = ""
        if proto == "napcat":
            p = self.runtime_profile()
            ref = str(p.get("docker_image", "")).strip() or "mlikiowa/napcat-docker:latest"
            want_repo = docker_repository_from_ref(ref)
        elif proto == "snowluma":
            p = self.runtime_profile()
            ref = (
                str(p.get("snowluma_docker_image", "")).strip()
                or str(getattr(self._config, "pallas_protocol_snowluma_docker_image", "") or "").strip()
                or "motricseven7/snowluma:latest"
            )
            want_repo = docker_repository_from_ref(ref)

        proc = await asyncio.create_subprocess_exec(
            "docker",
            "images",
            "--format",
            "{{.Repository}}:{{.Tag}}|{{.ID}}|{{.CreatedSince}}|{{.Size}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        text = out.decode("utf-8", errors="replace") if out else ""
        rows: list[dict[str, str]] = []
        for line in text.splitlines():
            item = line.strip()
            if not item:
                continue
            parts = item.split("|", 3)
            while len(parts) < 4:
                parts.append("")
            name = parts[0]
            if want_repo:
                row_repo = docker_repository_from_ref(name)
                if row_repo.lower() != want_repo.lower():
                    continue
            rows.append({
                "name": name,
                "id": parts[1],
                "created_since": parts[2],
                "size": parts[3],
            })
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "images": rows,
            "protocol": proto or None,
            "filter_repository": want_repo or None,
            "output": text[-4000:] if proc.returncode != 0 else "",
        }

    async def stop_all_labeled_docker_containers(self) -> dict[str, object]:
        if not shutil.which("docker"):
            return {"ok": False, "detail": "未找到 docker 命令", "stopped": 0}
        ps = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=pallas.protocol=napcat",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await ps.communicate()
        ids = [x.strip() for x in (out.decode("utf-8", errors="replace") if out else "").splitlines() if x.strip()]
        if not ids:
            return {"ok": True, "stopped": 0}
        stop = await asyncio.create_subprocess_exec(
            "docker",
            "stop",
            *ids,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        sout, _ = await stop.communicate()
        return {
            "ok": stop.returncode == 0,
            "code": stop.returncode,
            "stopped": len(ids) if stop.returncode == 0 else 0,
            "output": (sout.decode("utf-8", errors="replace") if sout else "")[-4000:],
        }

    async def prune_stopped_labeled_docker_containers(self) -> dict[str, object]:
        if not shutil.which("docker"):
            return {"ok": False, "detail": "未找到 docker 命令", "removed": 0}
        ps = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=pallas.protocol=napcat",
            "--filter",
            "status=exited",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await ps.communicate()
        ids = [x.strip() for x in (out.decode("utf-8", errors="replace") if out else "").splitlines() if x.strip()]
        if not ids:
            return {"ok": True, "removed": 0}
        rm = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            *ids,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        rout, _ = await rm.communicate()
        return {
            "ok": rm.returncode == 0,
            "code": rm.returncode,
            "removed": len(ids) if rm.returncode == 0 else 0,
            "output": (rout.decode("utf-8", errors="replace") if rout else "")[-4000:],
        }

    async def fetch_runtime_releases(self, *, limit: int = 10) -> list[dict]:
        return await self._runtime_store.fetch_releases(limit=limit)

    def rescan_runtime_extract(self) -> dict:
        m = self._runtime_store.rescan_existing_extract()
        if m is not None:
            self.sync_follow_global_runtime_paths_after_manifest_change(backend="napcat")
        return {**self.runtime_overview(), "rescanned": m is not None}

    def cleanup_runtime_dist_caches(self) -> dict[str, object]:
        n_nc = self._runtime_store.clear_dist_file_cache()
        n_sl = self._snowluma_store.clear_dist_file_cache()
        return {
            "ok": True,
            "napcat_files_removed": n_nc,
            "snowluma_files_removed": n_sl,
        }

    def napcat_local_inventory(self) -> dict[str, object]:
        return self._runtime_store.list_local_inventory()

    def _napcat_runtime_dir_for_account(self, account: dict) -> Path | None:
        p = self.runtime_profile()
        mode = str(p.get("napcat_runtime_mode") or p.get("runtime_mode", "") or "").strip().lower()
        if mode == "docker":
            return None
        tag = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        if not tag:
            return None
        return self._runtime_store.resolve_program_dir_for_tag_slug(tag)

    def _snowluma_runtime_dir_for_account(self, account: dict) -> Path | None:
        tag = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        if not tag:
            return None
        return self._snowluma_store.resolve_program_dir_for_tag_slug(tag)

    def activate_napcat_extract(self, folder_name: str) -> dict[str, object]:
        self._runtime_store.activate_extract_folder(folder_name)
        self.sync_follow_global_runtime_paths_after_manifest_change(backend="napcat")
        return self.runtime_overview()

    def activate_napcat_by_tag(self, tag: str) -> dict[str, object]:
        self._runtime_store.activate_extract_by_tag(tag)
        self.sync_follow_global_runtime_paths_after_manifest_change(backend="napcat")
        return self.runtime_overview()

    def snowluma_local_inventory(self) -> dict[str, object]:
        return self._snowluma_store.list_local_inventory()

    def activate_snowluma_extract(self, folder_name: str) -> dict[str, object]:
        self._snowluma_store.activate_extract_folder(folder_name)
        self.sync_follow_global_runtime_paths_after_manifest_change(backend="snowluma")
        return self.snowluma_runtime_overview()

    def activate_snowluma_by_tag(self, tag: str) -> dict[str, object]:
        self._snowluma_store.activate_extract_by_tag(tag)
        self.sync_follow_global_runtime_paths_after_manifest_change(backend="snowluma")
        return self.snowluma_runtime_overview()

    def _rewrite_webui_for_all_accounts(self) -> None:
        for account in self._accounts.values():
            be = self._protocol_runtime_backend(account)
            be.apply_defaults(account, self._resolve_qq)
            be.sync_webui(account, self._resolve_qq)

    def _pull_all_webui_from_disk(self) -> None:
        changed = False
        for account in self._accounts.values():
            if self._protocol_runtime_backend(account).read_webui_into_account(account):
                changed = True
        if changed:
            self._save_accounts()

    def _merge_onebot_ws_from_env(self, account: dict, *, force: bool = False) -> bool:
        docker_linux = bool(account.get("napcat_linux_docker") or account.get("snowluma_linux_docker"))
        dh = ""
        if docker_linux:
            from .docker_onebot_host import resolve_docker_onebot_host_from_config
            from .linux_docker import (
                rewrite_onebot_ws_url_for_container,
                ws_url_host_should_rewrite_for_docker_bridge,
            )

            dh = resolve_docker_onebot_host_from_config(self._config)
            current = str(account.get("ws_url", "")).strip()
            if current and ws_url_host_should_rewrite_for_docker_bridge(current):
                rewritten = rewrite_onebot_ws_url_for_container(current, dh)
                if rewritten and rewritten != current:
                    account["ws_url"] = rewritten
                    return True
        if not force and str(account.get("ws_url", "")).strip():
            return False
        qq = str(account.get("qq", "") or account.get("id", "")).strip()
        base_url, name, tok = resolve_onebot_ws_settings(self._config, bot_id=qq)
        if not base_url:
            return False
        if docker_linux:
            url = rewrite_onebot_ws_url_for_container(base_url, dh)
        else:
            url = base_url
        changed = False
        if account.get("ws_url") != url:
            account["ws_url"] = url
            changed = True
        if account.get("ws_name") != name:
            account["ws_name"] = name
            changed = True
        if account.get("ws_token") != tok:
            account["ws_token"] = tok
            changed = True
        return changed

    def _apply_onebot_ws_to_all_accounts(self) -> None:
        c = False
        for acc in self._accounts.values():
            if self._merge_onebot_ws_from_env(acc, force=False):
                c = True
        if c:
            self._save_accounts()

    def connection_hints(self) -> dict[str, object]:
        return onebot_connection_hints(self._config)

    async def initialize(self) -> None:
        self._apply_runtime_profile_to_config()
        self._load_accounts()
        self._pull_all_webui_from_disk()
        for account in self._accounts.values():
            self._protocol_runtime_backend(account).apply_defaults(account, self._resolve_qq)
        self._apply_onebot_ws_to_all_accounts()
        for account in self._accounts.values():
            self._protocol_runtime_backend(account).sync_onebot(account, self._resolve_qq)
        self._rewrite_webui_for_all_accounts()
        if self._config.pallas_protocol_auto_download_runtime and self.effective_runtime_program_dir() is None:
            if not self._runtime_store.is_busy():
                try:
                    self._runtime_store.start_background_download(
                        on_success=lambda: self.sync_follow_global_runtime_paths_after_manifest_change(
                            backend="napcat"
                        ),
                    )
                except RuntimeError:
                    pass

    async def start_all_enabled_accounts(self) -> None:
        from nonebot import logger

        for account_id, account in list(self._accounts.items()):
            if not bool(account.get("enabled", True)):
                continue
            self._protocol_runtime_backend(account).apply_defaults(account, self._resolve_qq)
            if account.get("napcat_linux_docker") or account.get("snowluma_linux_docker"):
                if self._linux_docker_container_running_sync(account):
                    await self.ensure_docker_logs_if_needed(account_id)
                    continue
            if self.is_running(account_id):
                continue
            try:
                await self.start_account(account_id)
            except ValueError as e:
                logger.warning(f"Pallas-Bot 协议端: 自动启动账号 {account_id} 失败：{e}")
            except Exception:
                logger.exception(f"Pallas-Bot 协议端: 自动启动账号 {account_id} 出现未预期异常")

    async def stop_all_enabled_accounts(self) -> None:
        from nonebot import logger

        for account_id, account in list(self._accounts.items()):
            if not bool(account.get("enabled", True)):
                continue
            if not self.is_running(account_id):
                continue
            try:
                await self.stop_account(account_id)
            except Exception:
                logger.exception(f"Pallas-Bot 协议端: 自动停止账号 {account_id} 出现未预期异常")

    def _snowluma_docker_mapped_host_ports_on_account(self, account: dict) -> set[int]:
        ports: set[int] = set()
        if not account.get("snowluma_linux_docker"):
            return ports
        from .snowluma_docker import (
            snowluma_docker_effective_host_novnc_port,
            snowluma_docker_effective_host_vnc_port,
        )

        for key in ("snowluma_docker_host_onebot_http", "snowluma_docker_host_onebot_ws"):
            raw = account.get(key)
            try:
                px = int(str(raw).strip()) if raw is not None and str(raw).strip() != "" else 0
            except (TypeError, ValueError):
                px = 0
            if 1 <= px <= 65535:
                ports.add(px)
        for fn in (snowluma_docker_effective_host_novnc_port, snowluma_docker_effective_host_vnc_port):
            v = fn(account, self._config)
            if 1 <= v <= 65535:
                ports.add(v)
        return ports

    def _used_webui_ports(self, exclude_account_id: str | None = None) -> set[int]:
        used: set[int] = set()
        for aid, acc in self._accounts.items():
            if exclude_account_id is not None and aid == exclude_account_id:
                continue
            p = acc.get("webui_port")
            if isinstance(p, int) and 1 <= p <= 65535:
                used.add(p)
            elif isinstance(p, str) and str(p).strip().isdigit():
                used.add(int(str(p).strip()))
            for key in ("snowluma_docker_host_onebot_http", "snowluma_docker_host_onebot_ws"):
                raw = acc.get(key)
                try:
                    px = int(str(raw).strip()) if raw is not None and str(raw).strip() != "" else 0
                except (TypeError, ValueError):
                    px = 0
                if 1 <= px <= 65535:
                    used.add(px)
            if acc.get("snowluma_linux_docker"):
                from .snowluma_docker import (
                    snowluma_docker_effective_host_novnc_port,
                    snowluma_docker_effective_host_vnc_port,
                )

                for eff in (
                    snowluma_docker_effective_host_novnc_port(acc, self._config),
                    snowluma_docker_effective_host_vnc_port(acc, self._config),
                ):
                    if 1 <= eff <= 65535:
                        used.add(eff)
        return used

    def _next_free_webui_port(self, *, exclude_account_id: str | None = None) -> int:
        lo = int(getattr(self._config, "pallas_protocol_webui_port_min", 6099))
        hi = int(getattr(self._config, "pallas_protocol_webui_port_max", 7999))
        if hi < lo:
            lo, hi = hi, lo
        used = self._used_webui_ports(exclude_account_id=exclude_account_id)
        for port in range(lo, hi + 1):
            if port not in used:
                return port
        msg = f"在 {lo}-{hi} 内无可用 NapCat WebUI 端口"
        raise ValueError(msg)

    def _is_host_port_available(self, port: int) -> bool:
        if not (1 <= int(port) <= 65535):
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", int(port)))
        except OSError:
            return False
        finally:
            sock.close()
        return True

    def _next_free_bindable_webui_port(self, *, exclude_account_id: str | None = None) -> int:
        lo = int(getattr(self._config, "pallas_protocol_webui_port_min", 6099))
        hi = int(getattr(self._config, "pallas_protocol_webui_port_max", 7999))
        if hi < lo:
            lo, hi = hi, lo
        used = self._used_webui_ports(exclude_account_id=exclude_account_id)
        for port in range(lo, hi + 1):
            if port in used:
                continue
            if self._is_host_port_available(port):
                return port
        msg = f"在 {lo}-{hi} 内无可绑定的内置 WebUI 端口"
        raise ValueError(msg)

    def _snowluma_docker_allocate_auto_host_ports(self, account: dict) -> dict[str, int]:
        """为 SnowLuma Docker 挑选不与其它账号冲突且本机可 bind 的宿主机端口。"""
        aid = str(account.get("id", "") or "").strip() or None
        used = set(self._used_webui_ports(exclude_account_id=aid))
        try:
            wu = int(str(account.get("webui_port", "")).strip())
        except (TypeError, ValueError):
            wu = 0
        if 1 <= wu <= 65535:
            used.add(wu)

        lo = int(getattr(self._config, "pallas_protocol_snowluma_docker_auto_bind_port_lo", 17100) or 17100)
        hi = int(getattr(self._config, "pallas_protocol_snowluma_docker_auto_bind_port_hi", 19998) or 19998)
        if hi < lo + 1:
            lo, hi = 17100, 19998

        one_h: int | None = None
        one_w: int | None = None
        for h in range(lo, hi):
            w = h + 1
            if w > hi:
                break
            if h in used or w in used:
                continue
            if self._is_host_port_available(h) and self._is_host_port_available(w):
                one_h, one_w = h, w
                break
        if one_h is None or one_w is None:
            msg = f"SnowLuma Docker：在 {lo}-{hi} 内找不到可用的连续 OneBot 宿主机端口对"
            raise ValueError(msg)

        used2 = used | {one_h, one_w}

        aux_lo = int(getattr(self._config, "pallas_protocol_snowluma_docker_auto_aux_bind_lo", 23100) or 23100)
        aux_hi = int(getattr(self._config, "pallas_protocol_snowluma_docker_auto_aux_bind_hi", 29998) or 29998)
        if aux_hi < aux_lo:
            aux_lo, aux_hi = 23100, 29998

        nn: int | None = None
        for p in range(aux_lo, aux_hi + 1):
            if p in used2:
                continue
            if self._is_host_port_available(p):
                nn = p
                break
        if nn is None:
            msg = f"SnowLuma Docker：在 {aux_lo}-{aux_hi} 内找不到可用的 noVNC 宿主机端口"
            raise ValueError(msg)

        used3 = used2 | {nn}
        vc: int | None = None
        for p in range(aux_lo, aux_hi + 1):
            if p in used3:
                continue
            if self._is_host_port_available(p):
                vc = p
                break
        if vc is None:
            msg = f"SnowLuma Docker：在 {aux_lo}-{aux_hi} 内找不到可用的 VNC 宿主机端口"
            raise ValueError(msg)

        return {
            "onebot_http": one_h,
            "onebot_ws": one_w,
            "host_novnc": nn,
            "host_vnc": vc,
        }

    def _refresh_linux_docker_run_argv(self, account: dict) -> None:
        if account.get("napcat_linux_docker"):
            from .linux_docker import build_docker_run_argv

            account["args"] = build_docker_run_argv(account, self._config, self._resolve_qq)
        elif account.get("snowluma_linux_docker"):
            from .snowluma_docker import build_snowluma_docker_run_argv

            account["args"] = build_snowluma_docker_run_argv(account, self._config, self._resolve_qq)

    def _migrate_account_webui_fields(self, account_id: str, account: dict) -> bool:
        changed = False
        if (
            ACCOUNT_PROTOCOL_BACKEND_KEY not in account
            or not str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or "").strip()
        ):
            account[ACCOUNT_PROTOCOL_BACKEND_KEY] = DEFAULT_PROTOCOL_BACKEND
            changed = True
        if "webui_port" not in account:
            account["webui_port"] = self._next_free_webui_port(exclude_account_id=account_id)
            changed = True
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
        bk = bk or DEFAULT_PROTOCOL_BACKEND
        if "webui_token" not in account and bk != SNOWLUMA_PROTOCOL_BACKEND:
            account["webui_token"] = secrets.token_hex(6)
            changed = True
        return changed

    def _load_accounts(self) -> None:
        if not self._accounts_file.exists():
            self._accounts = {}
            return
        try:
            self._accounts = json.loads(self._accounts_file.read_text(encoding="utf-8"))
            changed = False
            for account_id, account in self._accounts.items():
                before = json.dumps(account, ensure_ascii=False, sort_keys=True)
                self._protocol_runtime_backend(account).apply_defaults(account, self._resolve_qq)
                if self._migrate_account_webui_fields(account_id, account):
                    changed = True
                after = json.dumps(account, ensure_ascii=False, sort_keys=True)
                if before != after:
                    changed = True
            if changed:
                self._save_accounts()
        except Exception:
            self._accounts = {}

    def _save_accounts(self) -> None:
        self._accounts_file.write_text(json.dumps(self._accounts, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            from src.platform.multi_bot.fleet import invalidate_fleet_bot_cache

            invalidate_fleet_bot_cache()
        except Exception:
            pass

    def _docker_logs_follow_tail(self) -> str:
        n = int(getattr(self._config, "pallas_protocol_max_log_lines", 500) or 500)
        return str(max(100, min(n, 3000)))

    def _linux_docker_container_name(self, account: dict) -> str:
        if account.get("snowluma_linux_docker"):
            from .snowluma_docker import snowluma_docker_container_name

            return snowluma_docker_container_name(account)
        from .linux_docker import docker_container_name

        return docker_container_name(account)

    def _linux_docker_container_running_sync(self, account: dict) -> bool:
        if not (account.get("snowluma_linux_docker") or account.get("napcat_linux_docker")):
            return False
        name = self._linux_docker_container_name(account)
        if account.get("snowluma_linux_docker"):
            from .snowluma_docker import snowluma_docker_container_running_sync

            return snowluma_docker_container_running_sync(name)
        from .linux_docker import docker_container_running_sync

        return docker_container_running_sync(name)

    async def _remove_napcat_linux_docker_container_for_account(self, account: dict) -> None:
        stub = {"id": str(account.get("id", "x")).strip() or "x"}
        from .linux_docker import docker_container_name, docker_remove_force

        nap = docker_container_name(stub)
        if os.name == "nt":
            from .docker_cli import docker_stop_async

            await docker_stop_async(nap)
        await docker_remove_force(nap)

    async def _remove_snowluma_linux_docker_container_for_account(self, account: dict) -> None:
        stub = {"id": str(account.get("id", "x")).strip() or "x"}
        from .snowluma_docker import snowluma_docker_container_name, snowluma_docker_remove_force

        sl = snowluma_docker_container_name(stub)
        if os.name == "nt":
            from .docker_cli import docker_stop_async

            await docker_stop_async(sl)
        await snowluma_docker_remove_force(sl)

    async def _remove_both_linux_docker_container_names_for_account(self, account: dict) -> None:
        await self._remove_napcat_linux_docker_container_for_account(account)
        await self._remove_snowluma_linux_docker_container_for_account(account)

    def sync_follow_global_runtime_paths_after_manifest_change(self, *, backend: str = "both") -> None:
        changed = False
        nap_rt_str = ""
        if backend in ("napcat", "both"):
            p = self._runtime_store.resolved_program_dir()
            nap_rt_str = str(p).strip() if p else ""
        sl_rt_str = ""
        if backend in ("snowluma", "both"):
            sp = self._snowluma_store.resolved_program_dir()
            sl_rt_str = str(sp).strip() if sp else ""

        for account in self._accounts.values():
            if str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip():
                continue
            bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
            bk = bk or DEFAULT_PROTOCOL_BACKEND
            if bk == SNOWLUMA_PROTOCOL_BACKEND:
                if backend not in ("snowluma", "both") or not sl_rt_str or account.get("snowluma_linux_docker"):
                    continue
                before_pd = str(account.get("program_dir", "") or "").strip()
                self._launch._refresh_snowluma_managed_runtime_refs(account, sl_rt_str)
                if str(account.get("program_dir", "") or "").strip() != before_pd:
                    changed = True
                continue
            if backend not in ("napcat", "both") or account.get("napcat_linux_docker") or not nap_rt_str:
                continue
            before = (
                str(account.get("program_dir", "") or "").strip(),
                str(account.get("working_dir", "") or "").strip(),
                str(account.get("command", "") or "").strip(),
                json.dumps(account.get("args") or [], ensure_ascii=False),
            )
            self._launch._refresh_managed_runtime_refs(account, nap_rt_str)
            after = (
                str(account.get("program_dir", "") or "").strip(),
                str(account.get("working_dir", "") or "").strip(),
                str(account.get("command", "") or "").strip(),
                json.dumps(account.get("args") or [], ensure_ascii=False),
            )
            if before != after:
                changed = True
        if changed:
            self._save_accounts()

    def _runtime(self, account_id: str) -> NapCatRuntime:
        if account_id not in self._runtimes:
            self._runtimes[account_id] = NapCatRuntime(logs=deque(maxlen=self._config.pallas_protocol_max_log_lines))
        return self._runtimes[account_id]

    def list_accounts(self) -> list[dict]:
        out: list[dict] = []
        for account_id, account in self._accounts.items():
            out.append(self._compose_account_state(account_id, account, brief=True))
        return out

    def has_account(self, account_id: str) -> bool:
        return account_id in self._accounts

    def get_account(self, account_id: str, *, brief: bool = False) -> dict | None:
        account = self._accounts.get(account_id)
        if not account:
            return None
        return self._compose_account_state(account_id, account, brief=brief)

    def snowluma_webui_http_base(self, account: dict) -> str:
        h = str(getattr(self._config, "pallas_protocol_bind_host", "127.0.0.1") or "127.0.0.1").strip()
        if h in ("0.0.0.0", "::", "[::]"):
            h = "127.0.0.1"
        wp = account.get("webui_port")
        try:
            p = int(wp) if wp is not None and str(wp).strip() != "" else 0
        except (TypeError, ValueError):
            p = 0
        if not (1 <= p <= 65535):
            raise ValueError("账号未设置有效的内置 WebUI 端口 webui_port")
        return f"http://{h}:{p}"

    async def snowluma_inject_hook_via_webui(self, account_id: str) -> dict[str, object]:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
        bk = bk or DEFAULT_PROTOCOL_BACKEND
        if bk != SNOWLUMA_PROTOCOL_BACKEND:
            raise ValueError("仅 SnowLuma 协议端支持通过 WebUI 自动注入 Hook")
        qq = str(self._resolve_qq(account) or "").strip()
        if not qq.isdigit() or len(qq) < 5:
            raise ValueError("账号 QQ 无效")
        pwd = resolve_snowluma_webui_temp_password(account, self.tail_logs(account_id, 900))
        if not pwd:
            raise ValueError(
                "无法获取 SnowLuma WebUI 登录口令：请先启动本实例并在进程日志中查找 "
                "「initial credentials: user=admin password=…」（旧版为「临时密码」）。"
            )
        base = self.snowluma_webui_http_base(account).rstrip("/")
        timeout = httpx.Timeout(25.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            lr = await client.post(f"{base}/api/login", json={"password": pwd})
            lr.raise_for_status()
            login_body = lr.json()
            if not isinstance(login_body, dict) or not login_body.get("success"):
                msg = ""
                if isinstance(login_body, dict):
                    msg = str(login_body.get("message") or login_body.get("status") or "")
                raise ValueError(f"SnowLuma WebUI 登录失败: {msg or lr.text}")
            token = str(login_body.get("token") or "").strip()
            if not token:
                raise ValueError("SnowLuma WebUI 未返回登录 token")
            headers = {"Authorization": f"Bearer {token}"}
            pr = await client.get(f"{base}/api/processes", headers=headers)
            pr.raise_for_status()
            plist_raw = pr.json()
            procs: list = []
            if isinstance(plist_raw, dict):
                procs = plist_raw.get("list") or []
            if not isinstance(procs, list):
                procs = []
            hit: dict | None = None
            for item in procs:
                if isinstance(item, dict) and str(item.get("uin") or "").strip() == qq:
                    hit = item
                    break
            if hit is None:
                preview = [f"PID={p.get('pid')} UIN={p.get('uin')}" for p in procs[:12] if isinstance(p, dict)]
                hint = "；".join(preview) if preview else "（列表为空，请先在本机启动并登录 NTQQ）"
                raise ValueError(f"未找到已登录且 UIN 为 {qq} 的 QQ 进程。当前摘要：{hint}")
            pid = hit.get("pid")
            if not isinstance(pid, int) or pid <= 0:
                raise ValueError("SnowLuma 返回了无效的进程 PID")
            ur = await client.post(f"{base}/api/processes/{pid}/load", headers=headers)
            ur.raise_for_status()
            try:
                load_body = ur.json()
            except Exception:
                load_body = {"raw": ur.text}
        return {"ok": True, "pid": pid, "uin": qq, "snowluma": load_body}

    def create_account(self, payload: dict) -> dict:
        qq = str(payload.get("qq", "")).strip() or str(payload.get("id", "")).strip()
        if not qq:
            raise ValueError("QQ 号不能为空")
        if not qq.isdigit() or len(qq) < 5:
            raise ValueError("QQ 号需为 5 位以上数字")
        account_id = qq
        if account_id in self._accounts:
            raise ValueError("该 QQ 对应账号已存在")

        from src.platform.shard import context as shard_ctx
        from src.platform.shard.registry.store import assign_bot_to_shard

        if shard_ctx.sharding_active():
            assign_bot_to_shard(qq)
        url, name, tok = resolve_onebot_ws_settings(self._config, bot_id=qq)
        if not url:
            raise ValueError(
                "未配置 OneBot：请在 .env 设置 PALLAS_PROTOCOL_ONEBOT_HOST/PORT 与 PALLAS_PROTOCOL_ACCESS_TOKEN，"
                "或开启分片后配置 PALLAS_SHARD_WORKER_BASE_PORT / PALLAS_SHARD_WS_HOST。"
            )
        disp = str(payload.get("display_name", "")).strip()
        proto_backend = str(payload.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or "").strip() or DEFAULT_PROTOCOL_BACKEND
        account = {
            "id": account_id,
            "display_name": disp or account_id,
            ACCOUNT_PROTOCOL_BACKEND_KEY: proto_backend,
            "command": str(payload.get("command", "")).strip(),
            "args": payload.get("args"),
            "working_dir": str(payload.get("working_dir", "")).strip(),
            "env": payload.get("env", {}),
            "enabled": bool(payload.get("enabled", True)),
            "qq": qq,
            "ws_url": url,
            "ws_name": name,
            "ws_token": tok,
            "program_dir": str(payload.get("program_dir", "")).strip(),
            "account_data_dir": str(payload.get("account_data_dir", "")).strip(),
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            MANAGED_RUNTIME_TAG_KEY: str(payload.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip(),
        }
        wport_raw = payload.get("webui_port")
        if wport_raw is not None and str(wport_raw).strip() != "":
            try:
                wp = int(str(wport_raw).strip())
            except ValueError as e:
                raise ValueError("webui_port 必须为整数") from e
            if not (1 <= wp <= 65535):
                raise ValueError("webui_port 必须在 1-65535 之间")
            if wp in self._used_webui_ports():
                raise ValueError("WebUI 端口已被其他账号占用")
            account["webui_port"] = wp
        wtok = str(payload.get("webui_token", "")).strip()
        if wtok:
            account["webui_token"] = wtok
        # payload 中显式提供的 ws 字段优先级高于 env 默认值
        for ws_key in ("ws_url", "ws_name", "ws_token"):
            v = str(payload.get(ws_key, "")).strip() if ws_key != "ws_token" else payload.get(ws_key, "")
            if v:
                account[ws_key] = v
        be = self._protocol_runtime_backend(account)
        be.apply_defaults(account, self._resolve_qq)
        if "webui_port" not in account:
            account["webui_port"] = self._next_free_webui_port()
        _bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
        if "webui_token" not in account and _bk != SNOWLUMA_PROTOCOL_BACKEND:
            account["webui_token"] = secrets.token_hex(6)
        # 与 update_account 一致：合并 env / Docker 主机重写
        self._merge_onebot_ws_from_env(account)
        be.prepare_dirs(account)
        be.sync_all_configs(account, self._resolve_qq)
        self._accounts[account_id] = account
        self._save_accounts()
        return self._compose_account_state(account_id, account)

    async def update_account(self, account_id: str, payload: dict, *, restart: bool = True) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        old_backend = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
        old_backend = old_backend or DEFAULT_PROTOCOL_BACKEND
        need_restart = self._napcat_core_running(account_id, account)
        editable_keys = (
            "display_name",
            "command",
            "args",
            "working_dir",
            "env",
            "enabled",
            "qq",
            "program_dir",
            "account_data_dir",
            "webui_token",
            "ws_url",
            "ws_name",
            "ws_token",
            ACCOUNT_PROTOCOL_BACKEND_KEY,
            MANAGED_RUNTIME_TAG_KEY,
            "snowluma_docker_host_onebot_http",
            "snowluma_docker_host_onebot_ws",
        )
        for key in editable_keys:
            if key in payload:
                account[key] = payload[key]
        if ACCOUNT_PROTOCOL_BACKEND_KEY in account:
            v = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or "").strip()
            account[ACCOUNT_PROTOCOL_BACKEND_KEY] = v or DEFAULT_PROTOCOL_BACKEND
        new_backend = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
        new_backend = new_backend or DEFAULT_PROTOCOL_BACKEND
        if ACCOUNT_PROTOCOL_BACKEND_KEY in payload and new_backend != old_backend:
            if account.get("napcat_linux_docker") or account.get("snowluma_linux_docker"):
                await self.stop_account(account_id)
                await self._remove_both_linux_docker_container_names_for_account(account)
            account["program_dir"] = ""
            account["command"] = ""
            account["args"] = []
            account["account_data_dir"] = ""
            account["working_dir"] = ""
            account[MANAGED_RUNTIME_TAG_KEY] = ""
            account.pop("napcat_linux_docker", None)
            account.pop("snowluma_linux_docker", None)
            account.pop("snowluma_docker_host_onebot_http", None)
            account.pop("snowluma_docker_host_onebot_ws", None)
            account.pop("snowluma_docker_host_novnc_port", None)
            account.pop("snowluma_docker_host_vnc_port", None)
        if "webui_port" in payload:
            try:
                wp = int(str(payload["webui_port"]).strip())
            except ValueError as e:
                raise ValueError("webui_port 必须为整数") from e
            if not (1 <= wp <= 65535):
                raise ValueError("webui_port 必须在 1-65535 之间")
            if wp in self._snowluma_docker_mapped_host_ports_on_account(account):
                raise ValueError("WebUI 端口与当前账号 SnowLuma Docker 其它映射端口冲突")
            if wp in self._used_webui_ports(exclude_account_id=account_id):
                raise ValueError("WebUI 端口已被其他账号占用")
            account["webui_port"] = wp
        for vk in ("snowluma_docker_host_novnc_port", "snowluma_docker_host_vnc_port"):
            if vk not in payload:
                continue
            raw = payload[vk]
            if raw is None or (isinstance(raw, str) and not str(raw).strip()):
                account.pop(vk, None)
                continue
            try:
                pv = int(str(raw).strip())
            except ValueError as e:
                raise ValueError(f"{vk} 须为整数") from e
            if not (0 <= pv <= 65535):
                raise ValueError(f"{vk} 须在 0-65535 之间")
            try:
                same = vk in account and int(str(account[vk]).strip()) == pv
            except (TypeError, ValueError):
                same = False
            if same:
                account[vk] = pv
                continue
            if 1 <= pv <= 65535:
                try:
                    wpp = int(str(account.get("webui_port", "")).strip())
                except (TypeError, ValueError):
                    wpp = 0
                if pv == wpp:
                    raise ValueError(f"{vk} 不能与内置 WebUI 端口相同")
                for ok in ("snowluma_docker_host_onebot_http", "snowluma_docker_host_onebot_ws"):
                    try:
                        op = int(str(account.get(ok, "")).strip())
                    except (TypeError, ValueError):
                        op = 0
                    if op == pv:
                        raise ValueError(f"{vk} 不能与当前账号 OneBot 映射端口相同")
                if pv in self._used_webui_ports(exclude_account_id=account_id):
                    raise ValueError(f"端口 {pv} 已被其他账号或映射占用")
            account[vk] = pv
        be = self._protocol_runtime_backend(account)
        be.apply_defaults(account, self._resolve_qq)
        # 前端会始终带上 ws_url；仍需合并：Docker 下重写主机、留空时用 env 补全。
        self._merge_onebot_ws_from_env(account)
        be.prepare_dirs(account)
        be.sync_all_configs(account, self._resolve_qq)
        self._refresh_linux_docker_run_argv(account)
        account["updated_at"] = datetime.now(UTC).isoformat()
        self._save_accounts()
        restarted = bool(need_restart and restart)
        if restarted:
            await self.restart_account(account_id)
        return {
            "account": self._compose_account_state(account_id, account),
            "restarted": restarted,
            "needs_restart": bool(need_restart),
        }

    async def delete_account(self, account_id: str) -> None:
        if account_id not in self._accounts:
            raise KeyError("账号不存在")
        account = self._accounts.get(account_id) or {}
        account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
        try:
            await self.stop_account(account_id)
        except Exception:
            pass
        if account.get("napcat_linux_docker") or account.get("snowluma_linux_docker"):
            try:
                await self._remove_both_linux_docker_container_names_for_account(account)
            except Exception:
                pass
        self._accounts.pop(account_id, None)
        self._runtimes.pop(account_id, None)
        try:
            if await asyncio.to_thread(account_data_dir.is_dir):
                data_dir_resolved = await asyncio.to_thread(account_data_dir.resolve)
                instances_root_resolved = await asyncio.to_thread(self._instances_root.resolve)
                # 清理实例目录数据
                if data_dir_resolved == instances_root_resolved or instances_root_resolved in data_dir_resolved.parents:
                    shutil.rmtree(data_dir_resolved, ignore_errors=True)
        except OSError:
            pass
        self._save_accounts()

    def is_running(self, account_id: str) -> bool:
        account = self._accounts.get(account_id)
        if not account:
            return False
        if self._napcat_core_running(account_id, account):
            return True
        return self._is_bot_connected(account)

    def _napcat_core_running(self, account_id: str, account: dict | None = None) -> bool:
        acc = account if account is not None else self._accounts.get(account_id)
        if not acc:
            return False
        if acc.get("napcat_linux_docker") or acc.get("snowluma_linux_docker"):
            return self._linux_docker_container_running_sync(acc)
        runtime = self._runtimes.get(account_id)
        return bool(runtime and runtime.process and runtime.process.returncode is None)

    async def start_account(self, account_id: str) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        disk_changed = self._protocol_runtime_backend(account).read_webui_into_account(account)
        env_changed = self._merge_onebot_ws_from_env(account)
        if disk_changed or env_changed:
            self._save_accounts()
        be = self._protocol_runtime_backend(account)
        be.apply_defaults(account, self._resolve_qq)
        be.prepare_dirs(account)
        be.sync_all_configs(account, self._resolve_qq)
        runtime = self._runtime(account_id)
        async with runtime.lock:
            if account.get("napcat_linux_docker"):
                if self._linux_docker_container_running_sync(account):
                    await self._ensure_docker_logs_follower_locked(account_id, account, runtime)
                    return self._compose_account_state(account_id, account)
                return await self._start_account_linux_docker(account_id, account, runtime)
            if account.get("snowluma_linux_docker"):
                if self._linux_docker_container_running_sync(account):
                    await self._ensure_docker_logs_if_needed(account_id)
                    return self._compose_account_state(account_id, account)
                return await self._start_account_snowluma_linux_docker(account_id, account, runtime)
            if runtime.process and runtime.process.returncode is None:
                return self._compose_account_state(account_id, account)
            command = str(account.get("command", "")).strip()
            if not command:
                raise ValueError("command 不能为空")
            args = [str(item) for item in (account.get("args") or [])]
            env_map = os.environ.copy()
            account_data_dir = str(account.get("account_data_dir", "")).strip()
            if account_data_dir:
                ad_abs = await asyncio.to_thread(_realpath_sync, account_data_dir)
                raw_pb = account.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or ""
                bk = str(raw_pb).strip().lower() or DEFAULT_PROTOCOL_BACKEND
                if bk != SNOWLUMA_PROTOCOL_BACKEND:
                    # 设置 NapCat 工作目录
                    env_map["NAPCAT_WORKDIR"] = ad_abs
                    if self._launch.should_set_home_to_workdir():
                        env_map["HOME"] = ad_abs
            env_map.update({str(k): str(v) for k, v in (account.get("env") or {}).items()})
            command, args, env_map, cwd_quick = self._launch.resolve_boot_launch(
                account, command, args, env_map, self._resolve_qq
            )
            if (
                os.name != "nt"
                and os.geteuid() == 0
                and "--no-sandbox" not in args
                and (Path(command).suffix == ".AppImage" or any(Path(str(a)).suffix == ".AppImage" for a in args))
            ):
                # 追加 no-sandbox 参数
                args.append("--no-sandbox")
            launch_issues = be.check_launch_issues(account, self._resolve_qq)
            if launch_issues:
                raise ValueError("; ".join(launch_issues))
            # 读取工作目录
            workdir = str(account.get("working_dir", "")).strip() or None
            runtime.logs.clear()
            runtime.tracked_child_root_pid = None
            runtime.expect_bootmain_detach = bool(cwd_quick)
            cwd_final = (cwd_quick or "").strip() or workdir
            if (
                os.name != "nt"
                and account_data_dir
                and (Path(command).suffix == ".AppImage" or any(Path(str(a)).suffix == ".AppImage" for a in args))
            ):
                # AppImage 使用账号目录作为 cwd
                cwd_final = account_data_dir
            runtime.process = await asyncio.create_subprocess_exec(
                command,
                *args,
                cwd=cwd_final,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env_map,
                creationflags=self._launch.creation_flags(),
            )
            runtime.started_at = datetime.now(UTC)
            runtime.drain_task = asyncio.create_task(self._drain_logs(account_id))
        return self._compose_account_state(account_id, account)

    async def ensure_docker_logs_if_needed(self, account_id: str) -> None:
        account = self._accounts.get(account_id)
        if not account or not (account.get("napcat_linux_docker") or account.get("snowluma_linux_docker")):
            return
        self._protocol_runtime_backend(account).apply_defaults(account, self._resolve_qq)
        runtime = self._runtime(account_id)
        async with runtime.lock:
            await self._ensure_docker_logs_follower_locked(account_id, account, runtime)

    async def _ensure_docker_logs_follower_locked(self, account_id: str, account: dict, runtime: NapCatRuntime) -> None:
        from nonebot import logger

        name = self._linux_docker_container_name(account)
        if not self._linux_docker_container_running_sync(account):
            return

        following_ok = (
            runtime.process is not None
            and runtime.process.returncode is None
            and runtime.drain_task is not None
            and not runtime.drain_task.done()
        )
        if following_ok:
            return

        if runtime.drain_task and not runtime.drain_task.done():
            runtime.drain_task.cancel()
            try:
                await runtime.drain_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    f"NapCat Docker 日志跟随：等待 drain 任务结束时出现未预期异常 (account_id={account_id})"
                )
        runtime.drain_task = None

        proc = runtime.process
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
            except ProcessLookupError:
                pass
        runtime.process = None

        logp = await asyncio.create_subprocess_exec(
            "docker",
            "logs",
            "-f",
            "--tail",
            self._docker_logs_follow_tail(),
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        runtime.docker_container_name = name
        if runtime.started_at is None:
            runtime.started_at = datetime.now(UTC)
        runtime.process = logp
        runtime.drain_task = asyncio.create_task(self._drain_logs(account_id))

    async def _start_account_linux_docker(self, account_id: str, account: dict, runtime: NapCatRuntime) -> dict:
        be = self._protocol_runtime_backend(account)
        from .linux_docker import build_docker_run_argv

        await self._remove_both_linux_docker_container_names_for_account(account)
        if os.name == "nt":
            await asyncio.sleep(0.25)
        try:
            current_port = int(str(account.get("webui_port", "")).strip())
        except ValueError:
            current_port = 0
        if current_port <= 0 or not self._is_host_port_available(current_port):
            account["webui_port"] = self._next_free_bindable_webui_port(exclude_account_id=account_id)
            be.sync_webui(account, self._resolve_qq)
            self._save_accounts()
        account["args"] = build_docker_run_argv(account, self._config, self._resolve_qq)
        args = [str(x) for x in (account.get("args") or [])]
        launch_issues = be.check_launch_issues(account, self._resolve_qq)
        if launch_issues:
            raise ValueError("; ".join(launch_issues))
        name = self._linux_docker_container_name(account)
        await self._remove_both_linux_docker_container_names_for_account(account)
        runtime.logs.clear()
        runtime.tracked_child_root_pid = None
        runtime.expect_bootmain_detach = False
        runtime.docker_container_name = name
        cwd_run = str(account.get("account_data_dir", "")).strip() or None
        for attempt in range(3):
            proc = await asyncio.create_subprocess_exec(
                "docker",
                *args,
                cwd=cwd_run,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            text = out.decode("utf-8", errors="replace") if out else ""
            if text.strip():
                runtime.logs.append(text.strip())
            if proc.returncode == 0:
                break
            if attempt < 2 and (
                _docker_stderr_suggests_host_port_bind_conflict(text)
                or _docker_stderr_suggests_container_name_conflict(text)
            ):
                await self._remove_both_linux_docker_container_names_for_account(account)
                if _docker_stderr_suggests_host_port_bind_conflict(text):
                    # 不排除本账号：否则当前 webui_port 不会进入占用集，在 Win 上 bind 探测不准时会反复选回同一端口。
                    account["webui_port"] = self._next_free_bindable_webui_port(exclude_account_id=None)
                    be.sync_webui(account, self._resolve_qq)
                    self._save_accounts()
                account["args"] = build_docker_run_argv(account, self._config, self._resolve_qq)
                args = [str(x) for x in (account.get("args") or [])]
                continue
            err = f"docker run 失败 (exit {proc.returncode})"
            if text:
                err += ": " + text[:1200]
            raise ValueError(err)
        else:
            raise ValueError("docker run 启动失败")
        if not self._linux_docker_container_running_sync(account):
            raise ValueError("容器已创建但未在运行，请检查: docker logs " + name)
        runtime.started_at = datetime.now(UTC)
        logp = await asyncio.create_subprocess_exec(
            "docker",
            "logs",
            "-f",
            "--tail",
            self._docker_logs_follow_tail(),
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        runtime.process = logp
        runtime.drain_task = asyncio.create_task(self._drain_logs(account_id))
        return self._compose_account_state(account_id, account)

    async def _start_account_snowluma_linux_docker(
        self, account_id: str, account: dict, runtime: NapCatRuntime
    ) -> dict:
        be = self._protocol_runtime_backend(account)
        from .snowluma_docker import (
            build_snowluma_docker_run_argv,
            snowluma_docker_container_running_sync,
        )

        await self._remove_both_linux_docker_container_names_for_account(account)
        if os.name == "nt":
            await asyncio.sleep(0.25)
        try:
            current_port = int(str(account.get("webui_port", "")).strip())
        except ValueError:
            current_port = 0
        if current_port <= 0 or not self._is_host_port_available(current_port):
            account["webui_port"] = self._next_free_bindable_webui_port(exclude_account_id=account_id)
            be.sync_webui(account, self._resolve_qq)
            self._save_accounts()
        be.apply_defaults(account, self._resolve_qq)
        account["args"] = build_snowluma_docker_run_argv(account, self._config, self._resolve_qq)
        args = [str(x) for x in (account.get("args") or [])]
        launch_issues = be.check_launch_issues(account, self._resolve_qq)
        if launch_issues:
            raise ValueError("; ".join(launch_issues))
        name = self._linux_docker_container_name(account)
        await self._remove_both_linux_docker_container_names_for_account(account)
        runtime.logs.clear()
        runtime.tracked_child_root_pid = None
        runtime.expect_bootmain_detach = False
        runtime.docker_container_name = name
        cwd_run = str(account.get("account_data_dir", "")).strip() or None
        for attempt in range(3):
            proc = await asyncio.create_subprocess_exec(
                "docker",
                *args,
                cwd=cwd_run,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            text = out.decode("utf-8", errors="replace") if out else ""
            if text.strip():
                runtime.logs.append(text.strip())
            if proc.returncode == 0:
                break
            if attempt < 2 and (
                _docker_stderr_suggests_host_port_bind_conflict(text)
                or _docker_stderr_suggests_container_name_conflict(text)
            ):
                await self._remove_both_linux_docker_container_names_for_account(account)
                if _docker_stderr_suggests_host_port_bind_conflict(text):
                    # 不排除本账号：否则当前 webui_port 不会进入占用集，在 Win 上 bind 探测不准时会反复选回同一端口。
                    account["webui_port"] = self._next_free_bindable_webui_port(exclude_account_id=None)
                    account["snowluma_docker_host_onebot_http"] = 0
                    account["snowluma_docker_host_onebot_ws"] = 0
                    be.apply_defaults(account, self._resolve_qq)
                    be.sync_all_configs(account, self._resolve_qq)
                    self._save_accounts()
                account["args"] = build_snowluma_docker_run_argv(account, self._config, self._resolve_qq)
                args = [str(x) for x in (account.get("args") or [])]
                continue
            err = f"docker run 失败 (exit {proc.returncode})"
            if text:
                err += ": " + text[:1200]
            raise ValueError(err)
        else:
            raise ValueError("docker run 启动失败")
        if not snowluma_docker_container_running_sync(name):
            raise ValueError("容器已创建但未在运行，请检查: docker logs " + name)
        runtime.started_at = datetime.now(UTC)
        logp = await asyncio.create_subprocess_exec(
            "docker",
            "logs",
            "-f",
            "--tail",
            self._docker_logs_follow_tail(),
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        runtime.process = logp
        runtime.drain_task = asyncio.create_task(self._drain_logs(account_id))
        return self._compose_account_state(account_id, account)

    async def _stop_account_linux_docker(self, account_id: str, account: dict) -> dict | None:
        name = self._linux_docker_container_name(account)
        runtime = self._runtimes.get(account_id) or self._runtime(account_id)
        async with runtime.lock:
            if runtime.drain_task and not runtime.drain_task.done():
                runtime.drain_task.cancel()
            proc = runtime.process
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=6)
                except TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
            runtime.process = None
            if account.get("snowluma_linux_docker"):
                from .snowluma_docker import snowluma_docker_stop

                await snowluma_docker_stop(name)
            else:
                from .linux_docker import docker_stop

                await docker_stop(name)
            runtime.docker_container_name = None
        return self._compose_account_state(account_id, account)

    async def stop_account(self, account_id: str) -> dict | None:
        account = self._accounts.get(account_id)
        runtime = self._runtimes.get(account_id)
        if account is None:
            return None
        if account.get("napcat_linux_docker") or account.get("snowluma_linux_docker"):
            return await self._stop_account_linux_docker(account_id, account)
        if not runtime:
            return self._compose_account_state(account_id, account)
        async with runtime.lock:
            proc = runtime.process
            if proc and proc.returncode is None:
                # 结束进程树
                if proc.pid:
                    await asyncio.to_thread(self._launch.kill_process_tree, proc.pid)
                else:
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=12)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            # 无论 proc 是否存在，都尝试杀掉 BootMain 脱离后追踪到的子进程
            if runtime.tracked_child_root_pid:
                await asyncio.to_thread(
                    self._launch.kill_process_tree,
                    runtime.tracked_child_root_pid,
                )
                runtime.tracked_child_root_pid = None
            if runtime.drain_task and not runtime.drain_task.done():
                runtime.drain_task.cancel()
            runtime.process = None
        return self._compose_account_state(account_id, account)

    async def restart_account(self, account_id: str) -> dict:
        await self.stop_account(account_id)
        return await self.start_account(account_id)

    def tail_logs(self, account_id: str, lines: int = 200) -> list[str]:
        if lines <= 0:
            return []
        runtime = self._runtime(account_id)
        return list(runtime.logs)[-lines:]

    def account_qrcode_path(self, account_id: str) -> Path | None:
        account = self._accounts.get(account_id)
        if not account:
            return None
        cache_qr = Path(str(account.get("account_data_dir", "")).strip()) / "cache" / "qrcode.png"
        return cache_qr if cache_qr.is_file() else None

    def account_qrcode_meta(self, account_id: str) -> dict:
        path = self.account_qrcode_path(account_id)
        if path is None:
            return {"exists": False}
        try:
            st = path.stat()
        except OSError:
            return {"exists": False}
        return {
            "exists": True,
            "updated_at": int(st.st_mtime),
            "size": int(st.st_size),
        }

    def get_account_configs(self, account_id: str) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        be = self._protocol_runtime_backend(account)
        be.apply_defaults(account, self._resolve_qq)
        return be.get_account_configs(account, self._resolve_qq)

    async def update_account_configs(self, account_id: str, payload: dict, *, restart: bool = True) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        need_restart = self._napcat_core_running(account_id, account)
        be = self._protocol_runtime_backend(account)
        be.apply_defaults(account, self._resolve_qq)
        merged = be.update_account_configs(account, payload, self._resolve_qq)
        self._merge_onebot_ws_from_env(account)
        be.sync_all_configs(account, self._resolve_qq)
        account["updated_at"] = datetime.now(UTC).isoformat()
        self._save_accounts()
        restarted = bool(need_restart and restart)
        if restarted:
            await self.restart_account(account_id)
            merged = self.get_account_configs(account_id)
        return {**merged, "restarted": restarted, "needs_restart": bool(need_restart)}

    def bulk_register(self, accounts: dict[str, dict]) -> None:
        changed = False
        for account_id, account in accounts.items():
            if account_id in self._accounts:
                continue
            be = self._protocol_runtime_backend(account)
            be.apply_defaults(account, self._resolve_qq)
            self._migrate_account_webui_fields(account_id, account)
            be.prepare_dirs(account)
            be.sync_all_configs(account, self._resolve_qq)
            self._accounts[account_id] = account
            changed = True
        if changed:
            self._save_accounts()

    def _resolve_qq(self, account: dict) -> str:
        explicit = str(account.get("qq", "")).strip()
        if explicit.isdigit():
            return explicit
        account_id = str(account.get("id", "")).strip()
        if account_id.isdigit():
            return account_id
        match = re.search(r"\d{5,}", account_id)
        return match.group(0) if match else ""

    def _is_bot_connected(self, account: dict) -> bool:
        qq = self._resolve_qq(account)
        if not qq or not qq.isdigit():
            return False
        try:
            from src.platform.shard import context as shard_ctx

            if shard_ctx.sharding_active() and shard_ctx.is_hub():
                from src.platform.shard.presence import get_cluster_online_bot_ids

                return int(qq) in get_cluster_online_bot_ids()
        except Exception:
            pass
        try:
            from nonebot import get_bots

            return qq in get_bots()
        except Exception:
            return False

    async def _drain_logs(self, account_id: str) -> None:
        runtime = self._runtime(account_id)
        process = runtime.process
        if not process or not process.stdout:
            return
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                runtime.logs.append(text)
                qr_saved = re.search(r"二维码已保存到\s+(.+qrcode\.png)\s*$", text)
                if qr_saved:
                    try:
                        src_qr = Path(qr_saved.group(1).strip())
                        account = self._accounts.get(account_id) or {}
                        account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
                        if await asyncio.to_thread(src_qr.is_file) and account_data_dir:
                            account_cache_dir = account_data_dir / "cache"
                            account_cache_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src_qr, account_cache_dir / "qrcode.png")
                    except OSError:
                        pass
                m = re.search(r"Main Process ID[:\s]+(\d+)", text, re.IGNORECASE)
                if m:
                    try:
                        runtime.tracked_child_root_pid = int(m.group(1))
                    except ValueError:
                        pass
                if "Please run this script in administrator mode." in text:
                    runtime.logs.append(
                        "[pallas-protocol] 检测到启动器触发提权/进程脱离，后续输出可能无法被当前进程捕获。"
                    )
        except asyncio.CancelledError:
            pass
        finally:
            if process.returncode is None:
                await process.wait()
            code = process.returncode
            acc = self._accounts.get(account_id) or {}
            if acc.get("napcat_linux_docker") or acc.get("snowluma_linux_docker"):
                runtime.process = None
            elif runtime.expect_bootmain_detach:
                if code == 0:
                    runtime.logs.append(
                        "[pallas-protocol] BootMain 已退出（常见）。"
                        "「Process exited」多为启动器结束，QQ/NapCat 仍在子进程；以「已连接」或任务管理器为准。"
                    )
                elif code is not None:
                    runtime.logs.append(f"[pallas-protocol] BootMain 退出码 {code}，若未连上 Bot 请结合上文排查。")
                runtime.expect_bootmain_detach = False
                runtime.process = None
            else:
                runtime.process = None

    def _compose_account_state(self, account_id: str, account: dict, *, brief: bool = False) -> dict:
        be = self._protocol_runtime_backend(account)
        be.apply_defaults(account, self._resolve_qq)
        runtime = self._runtimes.get(account_id)
        process_running = False
        pid = None
        started_at = None
        if account.get("napcat_linux_docker") or account.get("snowluma_linux_docker"):
            process_running = self._linux_docker_container_running_sync(account)
            started_at = runtime.started_at.isoformat() if runtime and runtime.started_at else None
        elif runtime and runtime.process and runtime.process.returncode is None:
            process_running = True
            pid = runtime.process.pid
            started_at = runtime.started_at.isoformat() if runtime.started_at else None
        connected = self._is_bot_connected(account)
        launch_issues = be.check_launch_issues(account, self._resolve_qq)
        bind = str(getattr(self._config, "pallas_protocol_bind_host", "127.0.0.1") or "127.0.0.1").strip()
        wport = account.get("webui_port", "")
        wtok = str(account.get("webui_token", "")).strip()
        native_webui = ""
        native_webui_auth_note = ""
        snowluma_runtime_webui_password: str | None = None
        snowluma_webui_default_user: str | None = None
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
        bk = bk or DEFAULT_PROTOCOL_BACKEND
        try:
            if str(wport).strip():
                p = int(wport)
                if bk == SNOWLUMA_PROTOCOL_BACKEND:
                    # SnowLuma 仅使用根地址；初始口令见日志或预置 webui.json
                    native_webui = f"http://{bind}:{p}/"
                    snowluma_webui_default_user = "admin"
                    if brief:
                        snowluma_runtime_webui_password = None
                        native_webui_auth_note = "列表页不解析日志口令；进入账号控制台查看。"
                    else:
                        tail_logs = self.tail_logs(account_id, 900)
                        snowluma_runtime_webui_password = resolve_snowluma_webui_temp_password(account, tail_logs)
                        native_webui_auth_note = ""
                        if not snowluma_runtime_webui_password:
                            native_webui_auth_note = (
                                "未从日志解析到初始口令：请查看进程日志中的 "
                                "「initial credentials: user=admin password=…」（旧版为「临时密码」）。"
                            )
                else:
                    base = f"http://{bind}:{p}/webui/"
                    native_webui = f"{base}?token={quote(wtok, safe='')}" if wtok else base
        except (TypeError, ValueError):
            pass
        runtime_version = self._resolve_account_runtime_version(account)
        runtime_source = self._resolve_account_runtime_source(account)
        prof_rt = self.runtime_profile()
        grm = str(prof_rt.get("napcat_runtime_mode") or prof_rt.get("runtime_mode") or "").strip().lower()
        if not grm:
            grm = self._default_runtime_mode()
        grm_sl = str(prof_rt.get("snowluma_runtime_mode") or prof_rt.get("runtime_mode") or "").strip().lower()
        if not grm_sl:
            grm_sl = self._default_runtime_mode()
        snowluma_publish_ports: dict[str, object] | None = None
        snowluma_docker_novnc: dict[str, object] | None = None
        if account.get("snowluma_linux_docker"):
            from .snowluma_docker import (
                snowluma_docker_effective_host_novnc_port,
                snowluma_docker_effective_host_vnc_port,
            )

            in_wui = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_webui_port", 5099) or 5099)
            in_http = int(
                getattr(self._config, "pallas_protocol_snowluma_docker_internal_onebot_http_port", 3000) or 3000
            )
            in_ws = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_onebot_ws_port", 3001) or 3001)
            in_nn = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_novnc_port", 6081) or 6081)
            in_vc = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_vnc_port", 5900) or 5900)
            items: list[dict[str, int | str]] = []
            try:
                hp = int(str(wport).strip())
                if 1 <= hp <= 65535:
                    items.append({"label": "WebUI", "host": hp, "container": in_wui})
            except (TypeError, ValueError):
                pass
            try:
                ohh = int(str(account.get("snowluma_docker_host_onebot_http", "")).strip())
                oww = int(str(account.get("snowluma_docker_host_onebot_ws", "")).strip())
                if 1 <= ohh <= 65535:
                    items.append({"label": "OneBot HTTP", "host": ohh, "container": in_http})
                if 1 <= oww <= 65535:
                    items.append({"label": "OneBot WS", "host": oww, "container": in_ws})
            except (TypeError, ValueError):
                pass
            h_nn = snowluma_docker_effective_host_novnc_port(account, self._config)
            h_vc = snowluma_docker_effective_host_vnc_port(account, self._config)
            if 1 <= int(h_nn) <= 65535:
                items.append({"label": "noVNC", "host": int(h_nn), "container": in_nn})
                vnc_pw_cfg = str(getattr(self._config, "pallas_protocol_snowluma_docker_vnc_passwd", "") or "").strip()
                snowluma_docker_novnc = {
                    "url": f"http://{bind}:{int(h_nn)}/vnc.html",
                    "bind_host": bind,
                    "host_port": int(h_nn),
                    "uses_default_vnc_password": not bool(vnc_pw_cfg),
                }
            if 1 <= int(h_vc) <= 65535:
                items.append({"label": "VNC", "host": int(h_vc), "container": in_vc})
            snowluma_publish_ports = {"bind_host": bind, "items": items}
        return {
            **account,
            "global_runtime_mode": grm,
            "global_napcat_runtime_mode": grm,
            "global_snowluma_runtime_mode": grm_sl,
            "snowluma_publish_ports": snowluma_publish_ports,
            "snowluma_docker_novnc": snowluma_docker_novnc,
            "running": process_running or connected,
            "connected": connected,
            "process_running": process_running,
            "launch_ready": len(launch_issues) == 0,
            "launch_issues": launch_issues,
            "pid": pid,
            "started_at": started_at,
            "data_path_hints": be.describe_account_data_paths(account),
            "native_webui_url": native_webui,
            "native_webui_auth_note": native_webui_auth_note,
            "snowluma_runtime_webui_password": snowluma_runtime_webui_password,
            "snowluma_webui_default_user": snowluma_webui_default_user,
            "runtime_version": runtime_version,
            "runtime_source": runtime_source,
        }

    def _resolve_account_runtime_version(self, account: dict) -> str:
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
        bk = bk or DEFAULT_PROTOCOL_BACKEND
        if bk == SNOWLUMA_PROTOCOL_BACKEND:
            return self._resolve_snowluma_account_runtime_version(account)
        pinned = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        if pinned:
            return pinned
        if account.get("napcat_linux_docker"):
            image = str(account.get("program_dir", "") or "").strip()
            if image.startswith("docker:"):
                image = image[len("docker:") :].strip()
            if ":" in image:
                _, tag = image.rsplit(":", 1)
                return tag.strip() or "latest"
            return "latest" if image else "docker"

        manifest = self._runtime_store.read_manifest()
        if manifest is None:
            return "未知"
        tag = str(manifest.release_tag or "").strip() or "latest"

        acc_program = str(account.get("program_dir", "") or "").strip()
        if not acc_program:
            return tag
        try:
            acc_path = Path(acc_program).resolve()
            manifest_program = Path(manifest.program_dir).resolve()
            manifest_extract = Path(manifest.extract_root).resolve()
        except OSError:
            return "自定义"

        if acc_path == manifest_program:
            return tag
        if acc_path == manifest_extract or manifest_extract in acc_path.parents:
            return tag
        return "自定义"

    def _resolve_snowluma_account_runtime_version(self, account: dict) -> str:
        pinned = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        if pinned:
            return pinned
        if account.get("snowluma_linux_docker"):
            image = str(account.get("program_dir", "") or "").strip()
            if image.startswith("docker:snowluma:"):
                image = image[len("docker:snowluma:") :].strip()
            elif image.startswith("docker:"):
                image = image[len("docker:") :].strip()
            if ":" in image:
                _, tag = image.rsplit(":", 1)
                return tag.strip() or "latest"
            return "latest" if image else "docker"
        manifest = self._snowluma_store.read_manifest()
        if manifest is None:
            return "未知"
        tag = str(manifest.release_tag or "").strip() or "latest"

        acc_program = str(account.get("program_dir", "") or "").strip()
        if not acc_program:
            return tag
        try:
            acc_path = Path(acc_program).resolve()
            manifest_program = Path(manifest.program_dir).resolve()
            manifest_extract = Path(manifest.extract_root).resolve()
        except OSError:
            return "自定义"

        if acc_path == manifest_program:
            return tag
        if acc_path == manifest_extract or manifest_extract in acc_path.parents:
            return tag
        return "自定义"

    def _resolve_account_runtime_source(self, account: dict) -> str:
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or DEFAULT_PROTOCOL_BACKEND).strip().lower()
        bk = bk or DEFAULT_PROTOCOL_BACKEND
        if bk == SNOWLUMA_PROTOCOL_BACKEND:
            return self._resolve_snowluma_account_runtime_source(account)
        pinned = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        if pinned:
            return "NapCat 实例选用托管版本（个别版本）"
        if account.get("napcat_linux_docker"):
            image = str(account.get("program_dir", "") or "").strip()
            if image.startswith("docker:"):
                image = image[len("docker:") :].strip()
            return f"NapCat Docker 镜像（{image or '未设置'}）"

        manifest = self._runtime_store.read_manifest()
        if manifest is None:
            return "未知来源"

        acc_program = str(account.get("program_dir", "") or "").strip()
        if not acc_program:
            return "NapCat 托管发行包"
        try:
            acc_path = Path(acc_program).resolve()
            manifest_program = Path(manifest.program_dir).resolve()
            manifest_extract = Path(manifest.extract_root).resolve()
        except OSError:
            return "自定义路径"

        if acc_path == manifest_program:
            return "NapCat 托管发行包"
        if acc_path == manifest_extract or manifest_extract in acc_path.parents:
            return "NapCat 托管发行包"
        return "自定义路径"

    def _resolve_snowluma_account_runtime_source(self, account: dict) -> str:
        pinned = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        if pinned:
            return "SnowLuma 实例选用托管版本（个别版本）"
        if account.get("snowluma_linux_docker"):
            image = str(account.get("program_dir", "") or "").strip()
            if image.startswith("docker:snowluma:"):
                image = image[len("docker:snowluma:") :].strip()
            elif image.startswith("docker:"):
                image = image[len("docker:") :].strip()
            return f"SnowLuma Docker 镜像（{image or '未设置'}）"
        manifest = self._snowluma_store.read_manifest()
        if manifest is None:
            return "未知来源"

        acc_program = str(account.get("program_dir", "") or "").strip()
        if not acc_program:
            return "SnowLuma 托管发行包"
        try:
            acc_path = Path(acc_program).resolve()
            manifest_program = Path(manifest.program_dir).resolve()
            manifest_extract = Path(manifest.extract_root).resolve()
        except OSError:
            return "自定义路径"

        if acc_path == manifest_program:
            return "SnowLuma 托管发行包"
        if acc_path == manifest_extract or manifest_extract in acc_path.parents:
            return "SnowLuma 托管发行包"
        return "自定义路径"
