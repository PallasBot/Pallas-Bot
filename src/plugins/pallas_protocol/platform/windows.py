from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .base import NapcatPlatform


def _resolve_napcat_win_boot_main(program_dir: Path, qq_path: str | None) -> Path | None:
    direct = program_dir / "NapCatWinBootMain.exe"
    if direct.is_file():
        return direct
    if qq_path:
        alt = Path(qq_path).parent / "NapCatWinBootMain.exe"
        if alt.is_file():
            return alt
    return None


def _use_windows_boot_only_quick(boot_dir: Path, qq_path: str | None) -> bool:
    boot = boot_dir / "NapCatWinBootMain.exe"
    if not boot.is_file():
        return False
    if boot_dir.name.lower() == "bootmain":
        return True
    if not qq_path:
        return False
    try:
        return Path(qq_path).resolve().parent == boot_dir.resolve()
    except OSError:
        return False


def _find_bundled_qq_exe(program_dir: Path, *, max_depth: int = 8) -> str | None:
    root = program_dir.resolve()
    if not root.is_dir():
        return None

    def depth(p: Path) -> int:
        try:
            return len(p.relative_to(root).parts)
        except ValueError:
            return 999

    for path in root.rglob("QQ.exe"):
        if "node_modules" in path.parts:
            continue
        if depth(path) > max_depth:
            continue
        return str(path)
    return None


class WindowsNapcatPlatform(NapcatPlatform):
    def creation_flags(self) -> int:
        return subprocess.CREATE_NO_WINDOW

    def kill_process_tree(self, pid: int) -> None:
        if os.name != "nt" or pid <= 0:
            return
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def resolve_default_command(self, default_command: str) -> str:
        if default_command.lower() != "node":
            return default_command
        preferred = Path(r"C:\Program Files\nodejs\node.exe")
        if preferred.exists():
            return str(preferred)
        return default_command

    def detect_qq_path(self, program_dir: Path | None) -> str | None:
        if os.name != "nt":
            return None
        if program_dir is not None:
            bundled = _find_bundled_qq_exe(program_dir)
            if bundled:
                return bundled
        try:
            import winreg

            key_path = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                uninstall, _ = winreg.QueryValueEx(key, "UninstallString")
            qq_exe = Path(uninstall.strip().strip('"')).parent / "QQ.exe"
            return str(qq_exe) if qq_exe.exists() else None
        except Exception:
            return None

    def resolve_boot_launch(
        self,
        account: dict[str, Any],
        command: str,
        args: list[str],
        env_map: dict[str, str],
        resolve_qq,
    ) -> tuple[str, list[str], dict[str, str], str | None]:
        if os.name != "nt":
            return command, args, env_map, None
        program_dir = Path(str(account.get("program_dir", "")).strip())
        qq_path = self.detect_qq_path(program_dir)
        boot_main = _resolve_napcat_win_boot_main(program_dir, qq_path)
        if boot_main is None or not boot_main.is_file():
            return command, args, env_map, None
        boot_dir = boot_main.parent
        inject = boot_dir / "NapCatWinBootHook.dll"
        patch = boot_dir / "qqnt.json"
        main_mjs = boot_dir / "napcat.mjs"
        load_path = boot_dir / "loadNapCat.js"
        qq_uin = str(resolve_qq(account) or "").strip()
        quick = _use_windows_boot_only_quick(boot_dir, qq_path)
        if quick and qq_uin.isdigit():
            return str(boot_main), [qq_uin], env_map, str(boot_dir)
        if quick:
            return str(boot_main), [], env_map, str(boot_dir)
        if not quick and inject.exists() and patch.exists() and qq_path and main_mjs.exists():
            file_url = "file:///" + quote(str(main_mjs).replace("\\", "/"), safe="/:-._~")
            load_path.write_text(f'(async () => {{await import("{file_url}")}})()', encoding="utf-8")
            merged = {
                **env_map,
                "NAPCAT_PATCH_PACKAGE": str(patch),
                "NAPCAT_LOAD_PATH": str(load_path),
                "NAPCAT_INJECT_PATH": str(inject),
                "NAPCAT_LAUNCHER_PATH": str(boot_main),
                "NAPCAT_MAIN_PATH": str(main_mjs),
            }
            return str(boot_main), [qq_path, str(inject)], merged, None
        if qq_uin.isdigit():
            return str(boot_main), [qq_uin], env_map, str(boot_dir)
        return command, args, env_map, None

    def collect_qq_nt_hints(self, account: dict[str, Any]) -> list[str]:
        out: list[str] = []
        up = (os.environ.get("USERPROFILE") or "").strip()
        if up:
            out.append(str((Path(up) / ".config" / "QQ").resolve()))
        pd_raw = str(account.get("program_dir", "")).strip()
        if pd_raw:
            pd = Path(pd_raw).resolve()
            out.append(str(pd))
            exe = self.detect_qq_path(pd)
            if exe:
                out.append(str(Path(exe).resolve().parent))
        return out
