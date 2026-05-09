import os
import shutil
import socket
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .contract import (
    ACCOUNT_PROTOCOL_BACKEND_KEY,
    DEFAULT_PROTOCOL_BACKEND,
    MANAGED_RUNTIME_TAG_KEY,
    SNOWLUMA_PROTOCOL_BACKEND,
    resolve_default_account_data_dir,
)
from .platform import get_napcat_platform
from .platform import windows as _win
from .platform.base import NapcatPlatform

_LINUX_RT_MODES = frozenset({"docker", "appimage", "shell"})


def _profile_linux_runtime_mode(profile: dict | None, *, split_key: str) -> str:
    if not isinstance(profile, dict):
        return ""
    for k in (split_key, "runtime_mode"):
        m = str(profile.get(k, "") or "").strip().lower()
        if m in _LINUX_RT_MODES:
            return m
    return ""


class LaunchManager:
    def __init__(
        self,
        plugin_data_dir: Path,
        resource_root: Path,
        config,
        *,
        instances_root: Path,
        runtime_dir_provider: Callable[[], Path | None] | None = None,
        snowluma_runtime_dir_provider: Callable[[], Path | None] | None = None,
        runtime_dir_for_account: Callable[[dict], Path | None] | None = None,
        snowluma_runtime_dir_for_account: Callable[[dict], Path | None] | None = None,
        runtime_profile_provider: Callable[[], dict] | None = None,
        platform: NapcatPlatform | None = None,
        snowluma_docker_allocate_host_ports: Callable[[dict], Mapping[str, int]] | None = None,
    ) -> None:
        self._plugin_data_dir = plugin_data_dir
        self._resource_root = resource_root
        self._config = config
        self._instances_root = instances_root
        self._runtime_dir_provider = runtime_dir_provider
        self._snowluma_runtime_dir_provider = snowluma_runtime_dir_provider
        self._runtime_dir_for_account = runtime_dir_for_account
        self._snowluma_runtime_dir_for_account = snowluma_runtime_dir_for_account
        self._runtime_profile_provider = runtime_profile_provider
        self._platform = platform or get_napcat_platform()
        self._snowluma_docker_allocate_host_ports = snowluma_docker_allocate_host_ports

    def _managed_runtime_extract_root(self) -> Path:
        return (self._plugin_data_dir / "runtime_extract" / "napcat").resolve()

    def _legacy_flat_runtime_extract_root(self) -> Path:
        return (self._plugin_data_dir / "runtime_extract").resolve()

    def _snowluma_runtime_extract_root(self) -> Path:
        return (self._plugin_data_dir / "runtime_extract" / "snowluma").resolve()

    def _is_managed_runtime_path(self, raw: str) -> bool:
        s = str(raw or "").strip()
        if not s:
            return False
        p = Path(s)
        try:
            rp = p.resolve()
        except OSError:
            return False
        napcat_root = self._managed_runtime_extract_root()
        snow_root = self._snowluma_runtime_extract_root()
        legacy_root = self._legacy_flat_runtime_extract_root()
        if rp == napcat_root or napcat_root in rp.parents:
            return True
        if rp == snow_root or snow_root in rp.parents:
            return False
        if rp == legacy_root or legacy_root in rp.parents:
            try:
                rp.relative_to(snow_root)
                return False
            except ValueError:
                return True
        return False

    def _is_snowluma_managed_runtime_path(self, raw: str) -> bool:
        s = str(raw or "").strip()
        if not s:
            return False
        try:
            rp = Path(s).resolve()
        except OSError:
            return False
        snow_root = self._snowluma_runtime_extract_root()
        return rp == snow_root or snow_root in rp.parents

    def _refresh_managed_runtime_refs(self, account: dict, runtime_path: str) -> None:
        if not runtime_path:
            return
        rt = Path(runtime_path)
        rt_parent = str(rt.parent)

        cur_prog = str(account.get("program_dir", "")).strip()
        if cur_prog and self._is_managed_runtime_path(cur_prog) and Path(cur_prog) != rt:
            account["program_dir"] = runtime_path

        cur_work = str(account.get("working_dir", "")).strip()
        if cur_work and self._is_managed_runtime_path(cur_work):
            account["working_dir"] = rt_parent

        cmd = str(account.get("command", "") or "").strip()
        if cmd.endswith(".AppImage") and self._is_managed_runtime_path(cmd) and Path(cmd) != rt:
            account["command"] = runtime_path

        args = [str(a) for a in (account.get("args") or [])]
        if not args:
            return
        changed = False
        for i, a in enumerate(args):
            if not a.endswith(".AppImage"):
                continue
            if self._is_managed_runtime_path(a) and Path(a) != rt:
                args[i] = runtime_path
                changed = True
        if changed:
            account["args"] = args

    def _refresh_snowluma_managed_runtime_refs(self, account: dict, program_path: str) -> None:
        if not program_path:
            return
        try:
            rt = Path(program_path).resolve()
        except OSError:
            return
        cur_prog = str(account.get("program_dir", "") or "").strip()
        if not cur_prog or not self._is_snowluma_managed_runtime_path(cur_prog):
            return
        try:
            if Path(cur_prog).resolve() == rt:
                return
        except OSError:
            return
        account["program_dir"] = str(rt)

    def apply_defaults(self, account: dict, resolve_qq) -> None:
        qq = resolve_qq(account)
        if qq:
            account["qq"] = qq
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
        if bk == SNOWLUMA_PROTOCOL_BACKEND:
            self._apply_snowluma_defaults(account, resolve_qq)
            return

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

        managed_tag = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        acc_rt: Path | None = None
        if managed_tag and self._runtime_dir_for_account:
            try:
                acc_rt = self._runtime_dir_for_account(account)
            except Exception:
                acc_rt = None

        program_dir_raw = str(account.get("program_dir", "")).strip()
        if program_dir_raw.lower().startswith("docker:"):
            program_dir_raw = ""
        lazy_rt = self._runtime_dir_provider() if self._runtime_dir_provider else None
        runtime_str = str(lazy_rt).strip() if lazy_rt else ""
        configured_program_dir = str(getattr(self._config, "pallas_protocol_program_dir", "")).strip()
        if acc_rt is not None and acc_rt.is_dir():
            program_dir_raw = str(acc_rt.resolve())
        elif not program_dir_raw:
            if configured_program_dir:
                program_dir_raw = configured_program_dir
            elif runtime_str:
                program_dir_raw = runtime_str
            else:
                fallback = self._resource_root / "napcat"
                program_dir_raw = str(fallback) if fallback.is_dir() else ""
        elif not configured_program_dir:
            if not managed_tag:
                self._refresh_managed_runtime_refs(account, runtime_str)
            program_dir_raw = str(account.get("program_dir", "")).strip() or program_dir_raw
        account["program_dir"] = program_dir_raw
        account["working_dir"] = program_dir_raw

        account_data_dir = str(account.get("account_data_dir", "")).strip()
        account_id = str(account.get("id", "")).strip()
        aid = account_id or qq
        if not account_data_dir and aid:
            bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or "").strip() or DEFAULT_PROTOCOL_BACKEND
            account_data_dir = str(resolve_default_account_data_dir(self._instances_root, aid, bk).resolve())
        account["account_data_dir"] = account_data_dir

        cmd_raw = str(account.get("command", "") or "").strip()
        if cmd_raw and Path(cmd_raw).name.lower() in ("node", "node.exe") and qq:
            mjs = str(Path(program_dir_raw) / "napcat.mjs")
            q = str(qq).strip()
            # 写入账号参数
            account["args"] = [mjs, "-q", q] if q.isdigit() else [mjs]

        self._apply_linux_docker_profile(account, resolve_qq)
        self._apply_linux_local_appimage_profile(account)
        self._apply_linux_local_xvfb_profile(account)

    def _tcp_bindable_on_host(self, port: int) -> bool:
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

    def _apply_snowluma_linux_docker_profile(self, account: dict, resolve_qq) -> None:
        from .snowluma_docker import build_snowluma_docker_run_argv, snowluma_docker_program_dir_marker

        profile_mode = ""
        if self._runtime_profile_provider is not None:
            try:
                profile_mode = _profile_linux_runtime_mode(
                    self._runtime_profile_provider(),
                    split_key="snowluma_runtime_mode",
                )
            except Exception:
                profile_mode = ""
        docker_enabled = bool(getattr(self._config, "pallas_protocol_snowluma_linux_use_docker", False))
        if profile_mode == "docker":
            docker_enabled = True
        elif profile_mode in ("appimage", "shell"):
            docker_enabled = False
        if not docker_enabled:
            pd = str(account.get("program_dir", "") or "").strip()
            if pd.lower().startswith("docker:"):
                account["program_dir"] = ""
            return
        if profile_mode != "docker" and account.get("snowluma_linux_docker") is False:
            return
        raw = str(account.get("command", "") or "").strip()
        raw_name = Path(raw).name.lower() if raw else ""
        if profile_mode != "docker" and raw and raw_name not in ("node", "node.exe", "docker", "docker.exe"):
            return
        in_http = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_onebot_http_port", 3000) or 3000)
        in_ws = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_onebot_ws_port", 3001) or 3001)
        in_novnc = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_novnc_port", 6081) or 6081)
        in_vnc = int(getattr(self._config, "pallas_protocol_snowluma_docker_internal_vnc_port", 5900) or 5900)
        try:
            ex_h = int(str(account.get("snowluma_docker_host_onebot_http", "")).strip())
        except (TypeError, ValueError):
            ex_h = 0
        try:
            ex_w = int(str(account.get("snowluma_docker_host_onebot_ws", "")).strip())
        except (TypeError, ValueError):
            ex_w = 0
        try:
            wui = int(str(account.get("webui_port", "")).strip())
        except (TypeError, ValueError):
            wui = 0
        allocated: Mapping[str, int] | None = None
        if (
            1 <= ex_h <= 65535
            and 1 <= ex_w <= 65535
            and ex_h != ex_w
            and (ex_h != in_http or ex_w != in_ws)
            and (not (1 <= wui <= 65535) or (ex_h != wui and ex_w != wui))
        ):
            account["snowluma_docker_host_onebot_http"] = ex_h
            account["snowluma_docker_host_onebot_ws"] = ex_w
        else:
            if self._snowluma_docker_allocate_host_ports is not None:
                try:
                    allocated = self._snowluma_docker_allocate_host_ports(account)
                except Exception:
                    from nonebot import logger

                    logger.exception("SnowLuma Docker 自动分配宿主机端口失败，回退为与容器内同号的宿主机端口")
                    allocated = None
            if allocated:
                account["snowluma_docker_host_onebot_http"] = int(allocated["onebot_http"])
                account["snowluma_docker_host_onebot_ws"] = int(allocated["onebot_ws"])
            else:
                account["snowluma_docker_host_onebot_http"] = in_http
                account["snowluma_docker_host_onebot_ws"] = in_ws

        try:
            cur_nn = account.get("snowluma_docker_host_novnc_port")
            cur_nn_i = int(str(cur_nn).strip()) if cur_nn is not None and str(cur_nn).strip() != "" else 0
        except (TypeError, ValueError):
            cur_nn_i = 0
        if cur_nn_i >= 1:
            account["snowluma_docker_host_novnc_port"] = cur_nn_i
        else:
            if allocated:
                account["snowluma_docker_host_novnc_port"] = int(allocated["host_novnc"])
            else:
                gn = int(getattr(self._config, "pallas_protocol_snowluma_docker_host_novnc_port", 0) or 0)
                account["snowluma_docker_host_novnc_port"] = gn if gn >= 1 else in_novnc

        try:
            cur_vc = account.get("snowluma_docker_host_vnc_port")
            cur_vc_i = int(str(cur_vc).strip()) if cur_vc is not None and str(cur_vc).strip() != "" else 0
        except (TypeError, ValueError):
            cur_vc_i = 0
        if cur_vc_i >= 1:
            account["snowluma_docker_host_vnc_port"] = cur_vc_i
        else:
            if allocated:
                account["snowluma_docker_host_vnc_port"] = int(allocated["host_vnc"])
            else:
                gv = int(getattr(self._config, "pallas_protocol_snowluma_docker_host_vnc_port", 0) or 0)
                account["snowluma_docker_host_vnc_port"] = gv if gv >= 1 else in_vnc

        account["snowluma_linux_docker"] = True
        account["command"] = "docker"
        account["args"] = build_snowluma_docker_run_argv(account, self._config, resolve_qq)
        ad = str(account.get("account_data_dir", "") or "").strip()
        account["working_dir"] = ad or ("." if os.name == "nt" else "/")
        account["program_dir"] = snowluma_docker_program_dir_marker(self._config)

    def _apply_snowluma_defaults(self, account: dict, resolve_qq) -> None:
        account.pop("snowluma_linux_docker", None)
        qq = resolve_qq(account)
        if qq:
            account["qq"] = qq

        raw_command = account.get("command", "")
        command = "" if raw_command is None else str(raw_command).strip()
        args = account.get("args")
        if not command:
            dc = getattr(self._config, "pallas_protocol_default_command", "node")
            account["command"] = self._platform.resolve_default_command(dc)
            account["args"] = []
        elif args is None:
            account["args"] = []

        managed_tag = str(account.get(MANAGED_RUNTIME_TAG_KEY, "") or "").strip()
        acc_sl: Path | None = None
        if managed_tag and self._snowluma_runtime_dir_for_account:
            try:
                acc_sl = self._snowluma_runtime_dir_for_account(account)
            except Exception:
                acc_sl = None

        configured_sd = str(getattr(self._config, "pallas_protocol_snowluma_program_dir", "") or "").strip()
        lazy_sl = ""
        if self._snowluma_runtime_dir_provider:
            try:
                p = self._snowluma_runtime_dir_provider()
                if p is not None and p.is_dir():
                    lazy_sl = str(p.resolve())
            except Exception:
                lazy_sl = ""
        program_dir_raw = str(account.get("program_dir", "") or "").strip()
        if program_dir_raw.lower().startswith("docker:"):
            program_dir_raw = ""
        if acc_sl is not None and acc_sl.is_dir():
            program_dir_raw = str(acc_sl.resolve())
        elif not program_dir_raw:
            if configured_sd:
                program_dir_raw = configured_sd
            elif lazy_sl:
                program_dir_raw = lazy_sl
            else:
                fb = self._resource_root / "snowluma"
                program_dir_raw = str(fb) if fb.is_dir() else ""
        account["program_dir"] = program_dir_raw

        account_data_dir = str(account.get("account_data_dir", "") or "").strip()
        account_id = str(account.get("id", "") or "").strip()
        aid = account_id or qq
        if not account_data_dir and aid:
            bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or "").strip() or DEFAULT_PROTOCOL_BACKEND
            account_data_dir = str(resolve_default_account_data_dir(self._instances_root, aid, bk).resolve())
        account["account_data_dir"] = account_data_dir

        account["working_dir"] = account_data_dir or program_dir_raw

        pd = Path(program_dir_raw) if program_dir_raw else Path()
        idx = pd / "index.mjs"
        cmd_raw = str(account.get("command", "") or "").strip()
        if cmd_raw and Path(cmd_raw).name.lower() in ("node", "node.exe"):
            if idx.is_file():
                account["args"] = [str(idx.resolve())]
            elif program_dir_raw:
                account["args"] = ["index.mjs"]

        account.pop("napcat_linux_docker", None)
        self._apply_snowluma_linux_docker_profile(account, resolve_qq)

    def _apply_linux_docker_profile(self, account: dict, resolve_qq) -> None:
        from .linux_docker import build_docker_run_argv

        profile_mode = ""
        if self._runtime_profile_provider is not None:
            try:
                profile_mode = _profile_linux_runtime_mode(
                    self._runtime_profile_provider(),
                    split_key="napcat_runtime_mode",
                )
            except Exception:
                profile_mode = ""
        docker_enabled = bool(getattr(self._config, "pallas_protocol_linux_use_docker", True))
        if profile_mode == "docker":
            docker_enabled = True
        elif profile_mode in ("appimage", "shell"):
            docker_enabled = False
        if not docker_enabled:
            account["napcat_linux_docker"] = False
            pd = str(account.get("program_dir", "") or "").strip()
            if pd.lower().startswith("docker:"):
                account["program_dir"] = ""
            return
        if profile_mode != "docker" and account.get("napcat_linux_docker") is False:
            return
        raw = str(account.get("command", "") or "").strip()
        raw_name = Path(raw).name.lower() if raw else ""
        if profile_mode != "docker" and raw and raw_name not in ("node", "node.exe", "docker", "docker.exe"):
            return
        account["napcat_linux_docker"] = True
        account["command"] = "docker"
        account["args"] = build_docker_run_argv(account, self._config, resolve_qq)
        in_p = int(getattr(self._config, "pallas_protocol_docker_internal_webui_port", 6099) or 6099)
        account["napcat_docker_internal_webui"] = in_p
        ad = str(account.get("account_data_dir", "")).strip()
        account["working_dir"] = ad or ("." if os.name == "nt" else "/")
        img = (getattr(self._config, "pallas_protocol_docker_image", None) or "").strip() or (
            "mlikiowa/napcat-docker:latest"
        )
        account["program_dir"] = f"docker:{img}"

    def _apply_linux_local_xvfb_profile(self, account: dict) -> None:
        # 应用 xvfb 启动配置
        if not sys.platform.startswith("linux"):
            return
        if account.get("napcat_linux_docker"):
            return
        xvfb_command = str(getattr(self._config, "pallas_protocol_linux_xvfb_command", "xvfb-run") or "").strip()
        if not bool(getattr(self._config, "pallas_protocol_linux_use_xvfb", True)):
            command = str(account.get("command", "") or "").strip()
            # 关闭 xvfb 后，兼容历史已包裹的命令并自动解包。
            if xvfb_command and command and Path(command).name == Path(xvfb_command).name:
                raw_args = [str(item) for item in (account.get("args") or [])]
                configured_xvfb_args = [
                    str(item) for item in (getattr(self._config, "pallas_protocol_linux_xvfb_args", []) or [])
                ]
                restored_command = ""
                restored_args: list[str] = []
                has_prefix = len(raw_args) > len(configured_xvfb_args) and (
                    raw_args[: len(configured_xvfb_args)] == configured_xvfb_args
                )
                if has_prefix:
                    restored_command = raw_args[len(configured_xvfb_args)]
                    restored_args = raw_args[len(configured_xvfb_args) + 1 :]
                else:
                    for i, arg in enumerate(raw_args):
                        if not str(arg).startswith("-"):
                            restored_command = arg
                            restored_args = raw_args[i + 1 :]
                            break
                if restored_command:
                    account["command"] = restored_command
                    account["args"] = restored_args
            return
        command = str(account.get("command", "") or "").strip()
        if not command:
            return
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
        if self._runtime_profile_provider is not None:
            try:
                mode = _profile_linux_runtime_mode(
                    self._runtime_profile_provider(),
                    split_key="napcat_runtime_mode",
                )
            except Exception:
                mode = ""
            if mode == "shell":
                return
        command = str(account.get("command", "") or "").strip()
        if not command:
            return
        qq = str(account.get("qq", "")).strip()
        if Path(command).suffix == ".AppImage":
            cmd_path = Path(command)
            args = [str(x) for x in (account.get("args") or [])]
            if qq.isdigit() and "-q" not in args and "--qq" not in args:
                args = [*args, "-q", qq]
            if hasattr(os, "geteuid") and os.geteuid() == 0 and "--no-sandbox" not in args:
                args = [*args, "--no-sandbox"]
            account["args"] = args
            working_dir = str(account.get("working_dir", "")).strip()
            if not working_dir:
                account["working_dir"] = str(cmd_path.parent)
            else:
                wd_path = Path(working_dir)
                if (wd_path.exists() and wd_path.is_file()) or wd_path.suffix == ".AppImage":
                    account["working_dir"] = str(wd_path.parent)
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
        appimage_args = [str(x) for x in (getattr(self._config, "pallas_protocol_linux_appimage_args", []) or [])]
        if qq.isdigit() and "-q" not in appimage_args and "--qq" not in appimage_args:
            appimage_args.extend(["-q", qq])
        if hasattr(os, "geteuid") and os.geteuid() == 0 and "--no-sandbox" not in appimage_args:
            # 追加 no-sandbox 参数
            appimage_args.append("--no-sandbox")
        account["command"] = str(appimage)
        account["args"] = appimage_args
        # 设置 AppImage 工作目录
        account["working_dir"] = str(appimage.parent)

    def prepare_dirs(self, account: dict) -> None:
        program_dir_raw = str(account.get("working_dir", "")).strip()
        if program_dir_raw.lower().startswith("docker:"):
            ad = str(account.get("account_data_dir", "") or "").strip()
            program_dir_raw = ad or ("." if os.name == "nt" else "/")
            account["working_dir"] = program_dir_raw
        if program_dir_raw:
            program_dir_path = Path(program_dir_raw)
            # 规范工作目录路径
            if program_dir_path.exists() and program_dir_path.is_file():
                program_dir_path = program_dir_path.parent
            elif program_dir_path.suffix == ".AppImage":
                program_dir_path = program_dir_path.parent
            program_dir_path.mkdir(parents=True, exist_ok=True)
            account["working_dir"] = str(program_dir_path)
        account_data_dir = str(account.get("account_data_dir", "")).strip()
        if account_data_dir:
            Path(account_data_dir).mkdir(parents=True, exist_ok=True)
        if account.get("napcat_linux_docker"):
            from .linux_docker import docker_cache_path, docker_volume_paths

            cfg, qqd = docker_volume_paths(account)
            cache = docker_cache_path(account)
            try:
                cfg.mkdir(parents=True, exist_ok=True)
                qqd.mkdir(parents=True, exist_ok=True)
                cache.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
        if bk == SNOWLUMA_PROTOCOL_BACKEND and account.get("snowluma_linux_docker"):
            from .snowluma_docker import snowluma_docker_volume_paths

            for p in snowluma_docker_volume_paths(account):
                try:
                    p.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass

    def check_launch_issues(self, account: dict, resolve_qq) -> list[str]:
        issues: list[str] = []
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
        if bk == SNOWLUMA_PROTOCOL_BACKEND:
            return self._check_snowluma_launch_issues(account, resolve_qq)

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
            from .linux_docker import docker_cache_path, docker_volume_paths

            cfg, qqd = docker_volume_paths(account)
            cache = docker_cache_path(account)
            try:
                cfg.mkdir(parents=True, exist_ok=True)
                qqd.mkdir(parents=True, exist_ok=True)
                cache.mkdir(parents=True, exist_ok=True)
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
            return ["program_dir 为空：请先在「协议资产」页下载 NapCat 发行包，或配置 PALLAS_PROTOCOL_PROGRAM_DIR"]
        workdir = Path(program_dir_raw)
        # 规范工作目录路径
        if (workdir.exists() and workdir.is_file()) or workdir.suffix == ".AppImage":
            workdir = workdir.parent
            account["working_dir"] = str(workdir)
        if not workdir.exists():
            return [f"program_dir 不存在: {workdir}"]
        if not workdir.is_dir():
            return [f"program_dir 不是目录: {workdir}"]

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

    def _check_snowluma_launch_issues(self, account: dict, _resolve_qq) -> list[str]:
        issues: list[str] = []
        if account.get("snowluma_linux_docker"):
            if not shutil.which("docker"):
                return ["未找到 docker，请安装 Docker Engine，或在「协议资产」将运行模式改为非 Docker"]
            if not str(account.get("account_data_dir", "") or "").strip():
                return ["account_data_dir 为空"]
            from .snowluma_docker import snowluma_docker_volume_paths

            for p in snowluma_docker_volume_paths(account):
                try:
                    p.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    return [f"无法创建 SnowLuma Docker 数据目录 {p}: {e}"]
            return []
        command = str(account.get("command", "") or "").strip()
        if not command:
            return ["启动命令为空"]
        if Path(command).is_absolute():
            if not Path(command).exists():
                issues.append(f"启动命令不存在: {command}")
        elif shutil.which(command) is None:
            issues.append(f"系统找不到命令: {command}")

        pd_raw = str(account.get("program_dir", "") or "").strip()
        pd = Path(pd_raw) if pd_raw else Path()
        if pd_raw and not (pd / "index.mjs").is_file():
            issues.append(
                "未找到 SnowLuma 入口 index.mjs（请配置 program_dir 或 PALLAS_PROTOCOL_SNOWLUMA_PROGRAM_DIR）"
            )

        wd_raw = str(account.get("working_dir", "") or "").strip()
        if wd_raw and not Path(wd_raw).exists():
            issues.append(f"工作目录不存在: {wd_raw}")

        args = [str(item) for item in (account.get("args") or [])]
        script_like = next((arg for arg in args if arg.endswith((".mjs", ".js", ".cjs"))), None)
        if script_like:
            sp = Path(script_like)
            if not sp.is_absolute() and wd_raw:
                sp = Path(wd_raw) / sp
            if not sp.is_file():
                issues.append(f"脚本不存在: {sp}")
        elif not (pd_raw and (pd / "index.mjs").is_file()):
            if not issues:
                issues.append("缺少入口脚本（请配置 program_dir 或账号 program_dir 字段）")

        if not str(account.get("account_data_dir", "") or "").strip():
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
        bk = str(account.get(ACCOUNT_PROTOCOL_BACKEND_KEY, "") or "").strip().lower() or DEFAULT_PROTOCOL_BACKEND
        if bk == SNOWLUMA_PROTOCOL_BACKEND:
            return self._describe_snowluma_account_paths(account)

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
                " Linux/Docker：config、.config/QQ、cache 分别挂到容器 "
                "/app/napcat/config、/app/.config/QQ、/app/napcat/cache。"
            )
        return {
            "napcat_paths": dedupe(napcat),
            "qq_nt_candidate_dirs": dedupe(qq_nt),
            "note": base_note,
        }

    def _describe_snowluma_account_paths(self, account: dict) -> dict[str, object]:
        def dedupe(xs: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for x in xs:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        paths: list[str] = []
        ad = str(account.get("account_data_dir", "") or "").strip()
        qq = str(account.get("qq", "") or "").strip()
        if ad:
            root = Path(ad).resolve()
            cfg = root / "config"
            paths = [
                str(root),
                str(cfg),
                str(cfg / "runtime.json"),
                str(cfg / (f"onebot_{qq}.json" if qq else "onebot.json")),
            ]
        qq_nt = self._platform.collect_qq_nt_hints(account)
        note = (
            "SnowLuma：需先启动桌面 QQ；在 SnowLuma WebUI/API 中对 QQ 进程注入。"
            " 账号目录为进程 cwd，config/ 下为 runtime.json 与 onebot_<uin>.json；"
            "program_dir 指向含 index.mjs、native/ 的发行根。"
        )
        if account.get("snowluma_linux_docker"):
            from .snowluma_docker import snowluma_docker_volume_paths

            note += (
                " Linux/Docker：数据绑定到容器 /app/snowluma-data、/app/.config、/app/.local/share；"
                "宿主机目录见 instances/…/docker/snowluma/。"
            )
            paths.extend(str(p.resolve()) for p in snowluma_docker_volume_paths(account))
        return {
            "snowluma_paths": dedupe(paths),
            "qq_nt_candidate_dirs": dedupe(qq_nt),
            "note": note,
        }

    def creation_flags(self) -> int:
        return self._platform.creation_flags()

    def kill_process_tree(self, pid: int) -> None:
        self._platform.kill_process_tree(pid)

    def should_set_home_to_workdir(self) -> bool:
        return self._platform.should_set_home_to_workdir()
