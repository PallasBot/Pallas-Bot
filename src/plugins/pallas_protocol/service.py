import asyncio
import json
import os
import re
import secrets
import shutil
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from src.common.paths import resource_dir

from .config import (
    Config,
    instances_root_for,
    onebot_connection_hints,
    resolve_onebot_ws_settings,
)
from .config_manager import AccountConfigManager
from .contract import ACCOUNT_PROTOCOL_BACKEND_KEY, DEFAULT_PROTOCOL_BACKEND
from .launch_manager import LaunchManager
from .runtime.installer import NapCatRuntimeStore


def _realpath_sync(path: str) -> str:
    return os.path.realpath(path)


@dataclass
class NapCatRuntime:
    process: asyncio.subprocess.Process | None = None
    started_at: datetime | None = None
    logs: deque[str] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    drain_task: asyncio.Task | None = None
    # BootMain 一键：父进程常立即退出；从日志解析子树根 PID 供「停止」与说明
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
        self._launch = LaunchManager(
            self._data_dir,
            self._resource_root,
            self._config,
            instances_root=self._instances_root,
            runtime_dir_provider=self._runtime_store.resolved_program_dir,
        )
        self._configs = AccountConfigManager(
            self._config.pallas_protocol_bind_host,
            webui_port_fallback_min=int(getattr(self._config, "pallas_protocol_webui_port_min", 6099)),
        )

    def effective_runtime_program_dir(self) -> Path | None:
        configured = str(getattr(self._config, "pallas_protocol_program_dir", "")).strip()
        if configured:
            p = Path(configured)
            return p if p.is_dir() else None
        return self._runtime_store.resolved_program_dir()

    def runtime_overview(self) -> dict:
        manifest = self._runtime_store.read_manifest()
        eff = self.effective_runtime_program_dir()
        return {
            "job": self._runtime_store.job_snapshot(),
            "manifest": manifest.to_json() if manifest else None,
            "effective_program_dir": str(eff) if eff else None,
            "download": {
                "repo": self._config.pallas_protocol_github_repo,
                "asset": self._config.resolved_release_asset(),
                "tag": self._config.pallas_protocol_release_tag.strip() or "latest",
            },
        }

    def start_runtime_download(self) -> dict:
        self._runtime_store.start_background_download()
        return self.runtime_overview()

    def rescan_runtime_extract(self) -> dict:
        m = self._runtime_store.rescan_existing_extract()
        return {**self.runtime_overview(), "rescanned": m is not None}

    def _rewrite_webui_for_all_accounts(self) -> None:
        """修正历史 webui.json（例如 NapCat 首次生成的 host='::'），避免 Windows 上绑定 UNKNOWN。"""
        for account in self._accounts.values():
            self._launch.apply_defaults(account, self._resolve_qq)
            self._configs.sync_webui(account, self._resolve_qq)

    def _pull_all_webui_from_disk(self) -> None:
        changed = False
        for account in self._accounts.values():
            if self._configs.read_webui_into_account(account):
                changed = True
        if changed:
            self._save_accounts()

    def _merge_onebot_ws_from_env(self, account: dict) -> bool:
        """当 URL 在配置/环境中有值时，用其覆盖账号上的 ws 三字段。"""
        base_url, name, tok = resolve_onebot_ws_settings(self._config)
        if not base_url:
            return False
        if account.get("napcat_linux_docker"):
            from .linux_docker import rewrite_onebot_ws_url_for_container

            dh = str(getattr(self._config, "pallas_protocol_docker_onebot_host", "") or "").strip() or "172.17.0.1"
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
            if self._merge_onebot_ws_from_env(acc):
                c = True
        if c:
            self._save_accounts()

    def connection_hints(self) -> dict[str, object]:
        return onebot_connection_hints(self._config)

    async def initialize(self) -> None:
        self._load_accounts()
        self._pull_all_webui_from_disk()
        for account in self._accounts.values():
            self._launch.apply_defaults(account, self._resolve_qq)
        self._apply_onebot_ws_to_all_accounts()
        for account in self._accounts.values():
            self._configs.sync_onebot(account, self._resolve_qq)
        self._rewrite_webui_for_all_accounts()
        if self._config.pallas_protocol_auto_download_runtime and self.effective_runtime_program_dir() is None:
            if not self._runtime_store.is_busy():
                try:
                    self._runtime_store.start_background_download()
                except RuntimeError:
                    pass

    async def start_all_enabled_accounts(self) -> None:
        from nonebot import logger

        for account_id, account in list(self._accounts.items()):
            if not bool(account.get("enabled", True)):
                continue
            if self.is_running(account_id):
                continue
            try:
                await self.start_account(account_id)
            except Exception:
                logger.exception("NapCat: 自动启动账号 %s 失败", account_id)

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

    def _migrate_account_webui_fields(self, account_id: str, account: dict) -> bool:
        changed = False
        if ACCOUNT_PROTOCOL_BACKEND_KEY not in account or not str(
            account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or ""
        ).strip():
            account[ACCOUNT_PROTOCOL_BACKEND_KEY] = DEFAULT_PROTOCOL_BACKEND
            changed = True
        if "webui_port" not in account:
            account["webui_port"] = self._next_free_webui_port(exclude_account_id=account_id)
            changed = True
        if "webui_token" not in account:
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
                self._launch.apply_defaults(account, self._resolve_qq)
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

    def _runtime(self, account_id: str) -> NapCatRuntime:
        if account_id not in self._runtimes:
            self._runtimes[account_id] = NapCatRuntime(logs=deque(maxlen=self._config.pallas_protocol_max_log_lines))
        return self._runtimes[account_id]

    def list_accounts(self) -> list[dict]:
        out: list[dict] = []
        for account_id, account in self._accounts.items():
            out.append(self._compose_account_state(account_id, account))
        return out

    def has_account(self, account_id: str) -> bool:
        return account_id in self._accounts

    def get_account(self, account_id: str) -> dict | None:
        account = self._accounts.get(account_id)
        if not account:
            return None
        return self._compose_account_state(account_id, account)

    def create_account(self, payload: dict) -> dict:
        qq = str(payload.get("qq", "")).strip() or str(payload.get("id", "")).strip()
        if not qq:
            raise ValueError("QQ 号不能为空")
        if not qq.isdigit() or len(qq) < 5:
            raise ValueError("QQ 号需为 5 位以上数字")
        account_id = qq
        if account_id in self._accounts:
            raise ValueError("该 QQ 对应账号已存在")

        url, name, tok = resolve_onebot_ws_settings(self._config)
        if not url:
            raise ValueError(
                "未配置 OneBot：请在 .env 设置 PALLAS_PROTOCOL_ONEBOT_HOST/PORT 与 PALLAS_PROTOCOL_ACCESS_TOKEN，"
                "或与 NoneBot 共用的 HOST、PORT、ACCESS_TOKEN。"
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
        self._launch.apply_defaults(account, self._resolve_qq)
        if "webui_port" not in account:
            account["webui_port"] = self._next_free_webui_port()
        if "webui_token" not in account:
            account["webui_token"] = secrets.token_hex(6)
        self._merge_onebot_ws_from_env(account)
        self._launch.prepare_dirs(account)
        self._configs.sync_onebot(account, self._resolve_qq)
        self._configs.sync_napcat_core(account, self._resolve_qq)
        self._configs.sync_webui(account, self._resolve_qq)
        self._accounts[account_id] = account
        self._save_accounts()
        return self._compose_account_state(account_id, account)

    async def update_account(self, account_id: str, payload: dict, *, restart: bool = True) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
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
            ACCOUNT_PROTOCOL_BACKEND_KEY,
        )
        for key in editable_keys:
            if key in payload:
                account[key] = payload[key]
        if ACCOUNT_PROTOCOL_BACKEND_KEY in account:
            v = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY) or "").strip()
            account[ACCOUNT_PROTOCOL_BACKEND_KEY] = v or DEFAULT_PROTOCOL_BACKEND
        if "webui_port" in payload:
            try:
                wp = int(str(payload["webui_port"]).strip())
            except ValueError as e:
                raise ValueError("webui_port 必须为整数") from e
            if not (1 <= wp <= 65535):
                raise ValueError("webui_port 必须在 1-65535 之间")
            for oid, oacc in self._accounts.items():
                if oid == account_id:
                    continue
                op = oacc.get("webui_port")
                if isinstance(op, str) and str(op).strip().isdigit():
                    op = int(str(op).strip())
                if isinstance(op, int) and op == wp:
                    raise ValueError("WebUI 端口已被其他账号占用")
            account["webui_port"] = wp
        self._launch.apply_defaults(account, self._resolve_qq)
        self._merge_onebot_ws_from_env(account)
        self._launch.prepare_dirs(account)
        self._configs.sync_onebot(account, self._resolve_qq)
        self._configs.sync_napcat_core(account, self._resolve_qq)
        self._configs.sync_webui(account, self._resolve_qq)
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
        await self.stop_account(account_id)
        self._accounts.pop(account_id, None)
        self._runtimes.pop(account_id, None)
        try:
            if account_data_dir.is_dir():
                data_dir_resolved = account_data_dir.resolve()
                instances_root_resolved = self._instances_root.resolve()
                # 仅清理实例根目录下的数据，避免误删用户自定义的外部路径。
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
        """NapCat 子进程 / Docker 容器是否在跑（不含「仅 OneBot 已连接」）。"""
        acc = account if account is not None else self._accounts.get(account_id)
        if not acc:
            return False
        if acc.get("napcat_linux_docker"):
            from .linux_docker import docker_container_name, docker_container_running_sync

            return docker_container_running_sync(docker_container_name(acc))
        runtime = self._runtimes.get(account_id)
        return bool(runtime and runtime.process and runtime.process.returncode is None)

    async def start_account(self, account_id: str) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        disk_changed = self._configs.read_webui_into_account(account)
        env_changed = self._merge_onebot_ws_from_env(account)
        if disk_changed or env_changed:
            self._save_accounts()
        self._launch.apply_defaults(account, self._resolve_qq)
        self._launch.prepare_dirs(account)
        self._configs.sync_onebot(account, self._resolve_qq)
        self._configs.sync_napcat_core(account, self._resolve_qq)
        self._configs.sync_webui(account, self._resolve_qq)
        runtime = self._runtime(account_id)
        async with runtime.lock:
            if account.get("napcat_linux_docker"):
                from .linux_docker import docker_container_name, docker_container_running_sync

                if docker_container_running_sync(docker_container_name(account)):
                    return self._compose_account_state(account_id, account)
                return await self._start_account_linux_docker(account_id, account, runtime)
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
                # NapCatPathWrapper 用 NAPCAT_WORKDIR。Windows 勿改 USERPROFILE/HOME，
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
                and (
                    Path(command).suffix == ".AppImage"
                    or any(Path(str(a)).suffix == ".AppImage" for a in args)
                )
            ):
                # root 启动 Electron AppImage 时带 --no-sandbox。
                args.append("--no-sandbox")
            launch_issues = self._launch.check_launch_issues(account, self._resolve_qq)
            if launch_issues:
                raise ValueError("; ".join(launch_issues))
            # check_launch_issues 可能会归一化 account["working_dir"]（如 AppImage 文件路径 -> 父目录）。
            workdir = str(account.get("working_dir", "")).strip() or None
            runtime.logs.clear()
            runtime.tracked_child_root_pid = None
            runtime.expect_bootmain_detach = bool(cwd_quick)
            cwd_final = (cwd_quick or "").strip() or workdir
            if (
                os.name != "nt"
                and account_data_dir
                and (
                    Path(command).suffix == ".AppImage"
                    or any(Path(str(a)).suffix == ".AppImage" for a in args)
                )
            ):
                # Linux AppImage 下统一以账号目录为 cwd，确保多开时 cache/config 落在各自实例目录。
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

    async def _start_account_linux_docker(
        self, account_id: str, account: dict, runtime: NapCatRuntime
    ) -> dict:
        from .linux_docker import (
            build_docker_run_argv,
            docker_container_name,
            docker_container_running_sync,
            docker_remove_force,
        )

        raw_args = account.get("args")
        if not raw_args:
            account["args"] = build_docker_run_argv(account, self._config, self._resolve_qq)
        args = [str(x) for x in (account.get("args") or [])]
        launch_issues = self._launch.check_launch_issues(account, self._resolve_qq)
        if launch_issues:
            raise ValueError("; ".join(launch_issues))
        name = docker_container_name(account)
        await docker_remove_force(name)
        runtime.logs.clear()
        runtime.tracked_child_root_pid = None
        runtime.expect_bootmain_detach = False
        runtime.docker_container_name = name
        cwd_run = str(account.get("account_data_dir", "")).strip() or None
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            cwd=cwd_run,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if out:
            o = out.decode("utf-8", errors="replace").strip()
            if o:
                runtime.logs.append(o)
        if proc.returncode != 0:
            err = f"docker run 失败 (exit {proc.returncode})"
            if out:
                err += ": " + out.decode("utf-8", errors="replace")[:1200]
            raise ValueError(err)
        if not docker_container_running_sync(name):
            raise ValueError("容器已创建但未在运行，请检查: docker logs " + name)
        runtime.started_at = datetime.now(UTC)
        logp = await asyncio.create_subprocess_exec(
            "docker",
            "logs",
            "-f",
            "--since",
            "0s",
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        runtime.process = logp
        runtime.drain_task = asyncio.create_task(self._drain_logs(account_id))
        return self._compose_account_state(account_id, account)

    async def _stop_account_linux_docker(self, account_id: str, account: dict) -> dict | None:
        from .linux_docker import docker_container_name, docker_remove_force, docker_stop_sync

        name = docker_container_name(account)
        runtime = self._runtimes.get(account_id) or self._runtime(account_id)
        async with runtime.lock:
            if runtime.drain_task and not runtime.drain_task.done():
                runtime.drain_task.cancel()
            proc = runtime.process
            if proc and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=6)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            runtime.process = None
            docker_stop_sync(name)
            await docker_remove_force(name)
            runtime.docker_container_name = None
        return self._compose_account_state(account_id, account)

    async def stop_account(self, account_id: str) -> dict | None:
        account = self._accounts.get(account_id)
        runtime = self._runtimes.get(account_id)
        if account is None:
            return None
        if account.get("napcat_linux_docker"):
            return await self._stop_account_linux_docker(account_id, account)
        if not runtime:
            return self._compose_account_state(account_id, account)
        async with runtime.lock:
            proc = runtime.process
            if proc and proc.returncode is None:
                # Linux/Windows：启动器可能派生子进程，停止时优先结束整棵进程树。
                if proc.pid:
                    await asyncio.to_thread(self._launch.kill_process_tree, proc.pid)
                else:
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=12)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            elif runtime.tracked_child_root_pid:
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

    def get_account_configs(self, account_id: str) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        self._launch.apply_defaults(account, self._resolve_qq)
        return self._configs.get_account_configs(account, self._resolve_qq)

    async def update_account_configs(self, account_id: str, payload: dict, *, restart: bool = True) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            raise KeyError("账号不存在")
        need_restart = self._napcat_core_running(account_id, account)
        self._launch.apply_defaults(account, self._resolve_qq)
        merged = self._configs.update_account_configs(account, payload, self._resolve_qq)
        account["updated_at"] = datetime.now(UTC).isoformat()
        self._save_accounts()
        restarted = bool(need_restart and restart)
        if restarted:
            await self.restart_account(account_id)
            merged = self.get_account_configs(account_id)
        return {**merged, "restarted": restarted, "needs_restart": bool(need_restart)}

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
        if not qq:
            return False
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
                        if src_qr.is_file() and account_data_dir:
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
            if acc.get("napcat_linux_docker"):
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

    def _compose_account_state(self, account_id: str, account: dict) -> dict:
        self._launch.apply_defaults(account, self._resolve_qq)
        runtime = self._runtimes.get(account_id)
        process_running = False
        pid = None
        started_at = None
        if account.get("napcat_linux_docker"):
            from .linux_docker import docker_container_name, docker_container_running_sync

            process_running = docker_container_running_sync(docker_container_name(account))
            started_at = runtime.started_at.isoformat() if runtime and runtime.started_at else None
        elif runtime and runtime.process and runtime.process.returncode is None:
            process_running = True
            pid = runtime.process.pid
            started_at = runtime.started_at.isoformat() if runtime.started_at else None
        connected = self._is_bot_connected(account)
        launch_issues = self._launch.check_launch_issues(account, self._resolve_qq)
        bind = str(getattr(self._config, "pallas_protocol_bind_host", "127.0.0.1") or "127.0.0.1").strip()
        wport = account.get("webui_port", "")
        wtok = str(account.get("webui_token", "")).strip()
        native_webui = ""
        try:
            if str(wport).strip():
                p = int(wport)
                # NapCat express 仅匹配 /webui/...；官方日志里的 /webui?token= 无尾斜杠会落不到静态页（空白）
                base = f"http://{bind}:{p}/webui/"
                native_webui = f"{base}?token={quote(wtok, safe='')}" if wtok else base
        except (TypeError, ValueError):
            pass
        return {
            **account,
            "running": process_running or connected,
            "connected": connected,
            "process_running": process_running,
            "launch_ready": len(launch_issues) == 0,
            "launch_issues": launch_issues,
            "pid": pid,
            "started_at": started_at,
            "data_path_hints": self._launch.describe_account_data_paths(account),
            "native_webui_url": native_webui,
        }
