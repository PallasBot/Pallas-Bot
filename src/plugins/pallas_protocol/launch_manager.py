import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from .platform import get_napcat_platform
from .platform import windows as _win
from .platform.base import NapcatPlatform


class LaunchManager:
    def __init__(
        self,
        plugin_data_dir: Path,
        resource_root: Path,
        config,
        *,
        instances_root: Path,
        runtime_dir_provider: Callable[[], Path | None] | None = None,
        platform: NapcatPlatform | None = None,
    ) -> None:
        self._plugin_data_dir = plugin_data_dir
        self._resource_root = resource_root
        self._config = config
        self._instances_root = instances_root
        self._runtime_dir_provider = runtime_dir_provider
        self._platform = platform or get_napcat_platform()

    def apply_defaults(self, account: dict, resolve_qq) -> None:
        qq = resolve_qq(account)
        if qq:
            account["qq"] = qq
        raw_command = account.get("command", "")
        command = "" if raw_command is None else str(raw_command).strip()
        args = account.get("args")
        if not command:
            default_command = getattr(self._config, "pallas_protocol_default_command", "node")
            default_args = getattr(self._config, "pallas_protocol_default_args", ["napcat.mjs"])
            account["command"] = self._platform.resolve_default_command(default_command)
            account["args"] = list(default_args)
        elif args is None:
            account["args"] = []

        program_dir_raw = str(account.get("program_dir", "")).strip()
        if not program_dir_raw:
            configured_program_dir = str(getattr(self._config, "pallas_protocol_program_dir", "")).strip()
            lazy_rt = self._runtime_dir_provider() if self._runtime_dir_provider else None
            runtime_str = str(lazy_rt).strip() if lazy_rt else ""
            program_dir_raw = configured_program_dir or runtime_str or str(self._resource_root / "napcat")
        account["program_dir"] = program_dir_raw
        account["working_dir"] = program_dir_raw

        account_data_dir = str(account.get("account_data_dir", "")).strip()
        account_id = str(account.get("id", "")).strip()
        aid = account_id or qq
        if not account_data_dir and aid:
            account_data_dir = str((self._instances_root / aid).resolve())
        account["account_data_dir"] = account_data_dir

        cmd_raw = str(account.get("command", "") or "").strip()
        if cmd_raw and Path(cmd_raw).name.lower() in ("node", "node.exe") and qq:
            mjs = str(Path(program_dir_raw) / "napcat.mjs")
            q = str(qq).strip()
            # 与 NapCat shell 一致：-q/--qq 让 worker 优先走本机历史会话的快速登录。
            account["args"] = [mjs, "-q", q] if q.isdigit() else [mjs]

        self._apply_linux_docker_profile(account, resolve_qq)
        self._apply_linux_local_appimage_profile(account)
        self._apply_linux_local_xvfb_profile(account)

    def _apply_linux_docker_profile(self, account: dict, resolve_qq) -> None:
        from .linux_docker import build_docker_run_argv, is_linux

        if not is_linux():
            account["napcat_linux_docker"] = False
            return
        if not bool(getattr(self._config, "pallas_protocol_linux_use_docker", True)):
            account["napcat_linux_docker"] = False
            return
        if account.get("napcat_linux_docker") is False:
            return
        raw = str(account.get("command", "") or "").strip()
        if raw and raw not in ("node", "docker", ""):
            return
        account["napcat_linux_docker"] = True
        account["command"] = "docker"
        account["args"] = build_docker_run_argv(account, self._config, resolve_qq)
        in_p = int(getattr(self._config, "pallas_protocol_docker_internal_webui_port", 6099) or 6099)
        account["napcat_docker_internal_webui"] = in_p
        ad = str(account.get("account_data_dir", "")).strip()
        account["working_dir"] = ad or "/"
        img = (getattr(self._config, "pallas_protocol_docker_image", None) or "").strip() or (
            "mlikiowa/napcat-appimage:latest"
        )
        account["program_dir"] = f"docker:{img}"

    def _apply_linux_local_xvfb_profile(self, account: dict) -> None:
        # Linux 本地模式优先使用 xvfb-run，贴近 NapCatAppImageBuild 文档的无头启动实践。
        if not sys.platform.startswith("linux"):
            return
        if account.get("napcat_linux_docker"):
            return
        if not bool(getattr(self._config, "pallas_protocol_linux_use_xvfb", True)):
            return
        command = str(account.get("command", "") or "").strip()
        if not command:
            return
        xvfb_command = str(getattr(self._config, "pallas_protocol_linux_xvfb_command", "xvfb-run") or "").strip()
        if not xvfb_command:
            return
        if Path(command).name == Path(xvfb_command).name:
            return
        original_args = [str(item) for item in (account.get("args") or [])]
        xvfb_args = [str(item) for item in (getattr(self._config, "pallas_protocol_linux_xvfb_args", []) or [])]
        account["command"] = xvfb_command
        account["args"] = [*xvfb_args, command, *original_args]

    def _apply_linux_local_appimage_profile(self, account: dict) -> None:
        if not sys.platform.startswith("linux"):
            return
        if account.get("napcat_linux_docker"):
            return
        command = str(account.get("command", "") or "").strip()
        if not command:
            return
        if Path(command).suffix == ".AppImage":
            return
        if Path(command).name.lower() not in ("node", "node.exe"):
            return
        program_dir = Path(str(account.get("program_dir", "")).strip())
        if not program_dir.exists():
            return
        appimage = program_dir if program_dir.is_file() and program_dir.suffix == ".AppImage" else None
        if appimage is None and program_dir.is_dir():
            cands = sorted(program_dir.glob("*.AppImage"))
            appimage = cands[0] if cands else None
        if appimage is None:
            return
        appimage_args = [
            str(x) for x in (getattr(self._config, "pallas_protocol_linux_appimage_args", []) or [])
        ]
        account["command"] = str(appimage)
        account["args"] = appimage_args
        # AppImage 启动时工作目录应为其所在目录，避免把二进制文件路径当目录创建。
        account["working_dir"] = str(appimage.parent)

    def prepare_dirs(self, account: dict) -> None:
        program_dir_raw = str(account.get("working_dir", "")).strip()
        if program_dir_raw:
            program_dir_path = Path(program_dir_raw)
            # 兼容历史数据：working_dir 可能被写成 AppImage 文件路径。
            if program_dir_path.exists() and program_dir_path.is_file():
                program_dir_path = program_dir_path.parent
            elif program_dir_path.suffix == ".AppImage":
                program_dir_path = program_dir_path.parent
            program_dir_path.mkdir(parents=True, exist_ok=True)
        account_data_dir = str(account.get("account_data_dir", "")).strip()
        if account_data_dir:
            Path(account_data_dir).mkdir(parents=True, exist_ok=True)
        if account.get("napcat_linux_docker"):
            from .linux_docker import docker_volume_paths

            cfg, qqd = docker_volume_paths(account)
            try:
                cfg.mkdir(parents=True, exist_ok=True)
                qqd.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def check_launch_issues(self, account: dict, resolve_qq) -> list[str]:
        issues: list[str] = []
        program_dir = Path(str(account.get("program_dir", "")).strip())
        if os.name == "nt" and program_dir.exists():
            qq_path = self._platform.detect_qq_path(program_dir)
            boot_main = _win._resolve_napcat_win_boot_main(program_dir, qq_path)
            if boot_main is not None and boot_main.is_file():
                boot_dir = boot_main.parent
                inject = boot_dir / "NapCatWinBootHook.dll"
                patch = boot_dir / "qqnt.json"
                main_mjs = boot_dir / "napcat.mjs"
                qq_uin = str(resolve_qq(account) or "").strip()
                if _win._use_windows_boot_only_quick(boot_dir, qq_path):
                    if not qq_uin.isdigit():
                        issues.append("一键目录需要有效的数字 QQ 号（account.qq）")
                    return issues
                if inject.exists() and patch.exists():
                    if not main_mjs.exists():
                        issues.append(f"缺少文件: {main_mjs}")
                    if not qq_path:
                        issues.append(
                            "未检测到 QQ.exe：请安装 Windows QQ，或改用一键包，"
                            "或将 program_dir 指向含便携 QQ.exe 的 Shell 目录"
                        )
                    return issues
                if not qq_uin.isdigit():
                    issues.append("一键启动需要有效的数字 QQ 号（account.qq）")
                return issues

        if account.get("napcat_linux_docker"):
            if not shutil.which("docker"):
                return ["未找到 docker，请安装 Docker Engine，或将 pallas_protocol_linux_use_docker=false"]
            if not str(account.get("account_data_dir", "")).strip():
                return ["account_data_dir 为空"]
            from .linux_docker import docker_volume_paths

            cfg, qqd = docker_volume_paths(account)
            try:
                cfg.mkdir(parents=True, exist_ok=True)
                qqd.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return [f"无法创建 Docker 数据目录: {e}"]
            return []
        if (
            sys.platform.startswith("linux")
            and bool(getattr(self._config, "pallas_protocol_linux_use_xvfb", True))
            and not account.get("napcat_linux_docker")
        ):
            xvfb_command = str(getattr(self._config, "pallas_protocol_linux_xvfb_command", "xvfb-run") or "").strip()
            if xvfb_command and shutil.which(xvfb_command) is None:
                issues.append(f"系统找不到命令: {xvfb_command}（可安装 xvfb，或关闭 pallas_protocol_linux_use_xvfb）")

        command = str(account.get("command", "")).strip()
        if not command:
            return ["启动命令为空"]
        if Path(command).is_absolute():
            if not Path(command).exists():
                issues.append(f"启动命令不存在: {command}")
        elif shutil.which(command) is None:
            issues.append(f"系统找不到命令: {command}")

        program_dir_raw = str(account.get("working_dir", "")).strip()
        if not program_dir_raw:
            return ["program_dir 为空"]
        workdir = Path(program_dir_raw)
        if not workdir.exists():
            return [f"program_dir 不存在: {program_dir_raw}"]

        args = [str(item) for item in (account.get("args") or [])]
        script_like = next((arg for arg in args if arg.endswith((".mjs", ".js", ".cjs"))), None)
        if script_like:
            script_path = Path(script_like)
            if not script_path.is_absolute():
                script_path = workdir / script_path
            if not script_path.exists():
                issues.append(f"脚本不存在: {script_path}")
        if not str(account.get("account_data_dir", "")).strip():
            issues.append("account_data_dir 为空")
        return issues

    def resolve_boot_launch(
        self,
        account: dict,
        command: str,
        args: list[str],
        env_map: dict[str, str],
        resolve_qq,
    ) -> tuple[str, list[str], dict[str, str], str | None]:
        return self._platform.resolve_boot_launch(account, command, args, env_map, resolve_qq)

    def describe_account_data_paths(self, account: dict) -> dict[str, object]:
        """NapCat 写入路径与 QQ NT 常见落点（启发式）。"""

        def dedupe(xs: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for x in xs:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        napcat: list[str] = []
        ad = str(account.get("account_data_dir", "")).strip()
        if ad:
            root = Path(ad).resolve()
            napcat = [
                str(root),
                str(root / "config"),
                str(root / "cache"),
                str(root / "logs"),
                str(root / "plugins"),
            ]
        qq_nt = self._platform.collect_qq_nt_hints(account)
        base_note = (
            "NapCat 由 NAPCAT_WORKDIR 决定（napcat-common/path.ts）。"
            "QQ 登录态/消息库由 NT 层决定，常见为当前用户的 .config/QQ 或便携包旁"
            "（napcat-shell/base.ts）；未必写入账号目录下的 QQ 文件夹。"
        )
        if account.get("napcat_linux_docker"):
            base_note += (
                " Linux/Docker：config 与 docker/qq 挂到容器 /app/napcat/config 与 /app/.config/QQ"
                "（NapCatAppImageBuild）。"
            )
        return {
            "napcat_paths": dedupe(napcat),
            "qq_nt_candidate_dirs": dedupe(qq_nt),
            "note": base_note,
        }

    def creation_flags(self) -> int:
        return self._platform.creation_flags()

    def kill_process_tree(self, pid: int) -> None:
        self._platform.kill_process_tree(pid)

    def should_set_home_to_workdir(self) -> bool:
        return self._platform.should_set_home_to_workdir()
