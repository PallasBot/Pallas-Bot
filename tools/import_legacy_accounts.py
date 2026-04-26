#!/usr/bin/env python3
"""
导入旧协议端留存账号到 pallas_protocol 管理。

用法：
    uv run python tools/import_legacy_accounts.py --source /path/to/old/accounts

文件夹格式：<昵称>/
  config/
    onebot_<QQ>.json  或  onebot11_<QQ>.json  （用于提取 QQ 号）
    napcat.json / napcat_<QQ>.json
    webui.json
  QQ/                ← QQ NT 数据，会被复制到 .config/QQ/

脚本会将旧文件夹路径作为 account_data_dir 原地注册（不移动文件），
将 QQ/ 复制到 .config/QQ/，并补全 onebot/napcat/webui 配置以对接当前 Bot。
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径设置：允许从项目根目录直接 uv run
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.common.paths import plugin_data_dir  # noqa: E402


def _extract_qq_from_config_dir(config_dir: Path) -> str | None:
    """从 config/ 目录下的 onebot_*.json 文件名提取 QQ 号。"""
    patterns = [
        r"onebot11_(\d{5,})\.json",
        r"onebot_(\d{5,})\.json",
    ]
    for pat in patterns:
        for f in config_dir.glob("*.json"):
            m = re.fullmatch(pat, f.name)
            if m:
                return m.group(1)
    # 兜底：读取 webui.json 里的 autoLoginAccount
    webui = config_dir / "webui.json"
    if webui.is_file():
        try:
            data = json.loads(webui.read_text(encoding="utf-8"))
            v = str(data.get("autoLoginAccount", "")).strip()
            if v.isdigit() and len(v) >= 5:
                return v
        except Exception:
            pass
    return None


def _used_ports(accounts: dict) -> set[int]:
    used: set[int] = set()
    for acc in accounts.values():
        p = acc.get("webui_port")
        try:
            used.add(int(p))
        except (TypeError, ValueError):
            pass
    return used


def _next_free_port(accounts: dict, lo: int = 6099, hi: int = 7999) -> int:
    used = _used_ports(accounts)
    for p in range(lo, hi + 1):
        if p not in used:
            return p
    raise ValueError(f"在 {lo}-{hi} 内无可用端口")


def _safe_read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sync_webui(config_dir: Path, qq: str, webui_port: int, webui_token: str) -> None:
    """补全 webui.json，写入 autoLoginAccount / port / token。"""
    webui_path = config_dir / "webui.json"
    data = _safe_read_json(webui_path)
    data.setdefault("loginRate", 10)
    data["autoLoginAccount"] = qq
    data.setdefault("disableWebUI", False)
    data.setdefault("accessControlMode", "none")
    data.setdefault("ipWhitelist", [])
    data.setdefault("ipBlacklist", [])
    data.setdefault("enableXForwardedFor", False)
    data["host"] = "127.0.0.1"
    data["port"] = webui_port
    if webui_token:
        data["token"] = webui_token
    else:
        data.setdefault("token", "")
    webui_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sync_napcat(config_dir: Path, qq: str) -> None:
    """补全 napcat.json / napcat_<qq>.json。"""
    targets = [config_dir / "napcat.json"]
    if qq:
        targets.append(config_dir / f"napcat_{qq}.json")
    for path in targets:
        data = _safe_read_json(path)
        data["fileLog"] = False
        data.setdefault("fileLogLevel", "debug")
        data.setdefault("consoleLog", True)
        data.setdefault("consoleLogLevel", "info")
        data.setdefault("packetBackend", "auto")
        data.setdefault("packetServer", "")
        data.setdefault("o3HookMode", 1)
        data.setdefault("autoTimeSync", True)
        data.setdefault(
            "bypass",
            {"hook": False, "window": False, "module": False, "process": False, "container": False, "js": False},
        )
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_onebot_path(config_dir: Path, qq: str) -> Path:
    preferred = [config_dir / f"onebot11_{qq}.json", config_dir / f"onebot_{qq}.json"]
    for p in preferred:
        if p.exists():
            return p
    canonical = config_dir / "onebot11.json"
    if canonical.exists():
        return canonical
    has_legacy = any(p.name.startswith("onebot_") for p in config_dir.glob("onebot_*.json"))
    if has_legacy:
        return config_dir / f"onebot_{qq}.json"
    return config_dir / f"onebot11_{qq}.json"


def _sync_onebot(config_dir: Path, qq: str, ws_url: str, ws_name: str, ws_token: str) -> None:
    """补全 onebot11_<qq>.json，写入 websocketClients。"""
    onebot_path = _resolve_onebot_path(config_dir, qq)
    data = _safe_read_json(onebot_path)
    if not isinstance(data.get("network"), dict):
        data["network"] = {}
    network = data["network"]
    network.setdefault("httpServers", [])
    network.setdefault("httpSseServers", [])
    network.setdefault("httpClients", [])
    network.setdefault("websocketServers", [])
    network.setdefault("plugins", [])
    ws_clients = network.get("websocketClients")
    if not isinstance(ws_clients, list):
        ws_clients = []
    if not ws_clients:
        ws_clients.append({})
    client = ws_clients[0]
    client["enable"] = True
    client["name"] = ws_name or "pallas"
    if ws_url:
        client["url"] = ws_url
    client.setdefault("url", "ws://127.0.0.1:8088/onebot/v11/ws")
    client["reportSelfMessage"] = False
    client["messagePostFormat"] = "array"
    client["token"] = ws_token or ""
    client["debug"] = False
    client["heartInterval"] = 5000
    client["reconnectInterval"] = 3000
    network["websocketClients"] = ws_clients
    data.setdefault("musicSignUrl", "https://ss.xingzhige.com/music_card/card")
    data.setdefault("enableLocalFile2Url", False)
    data.setdefault("parseMultMsg", False)
    data.setdefault("imageDownloadProxy", "")
    data.setdefault(
        "timeout",
        {"baseTimeout": 10000, "uploadSpeedKBps": 256, "downloadSpeedKBps": 256, "maxTimeout": 1800000},
    )
    # 同步写入所有目标文件
    targets = {onebot_path, config_dir / f"onebot11_{qq}.json", config_dir / "onebot11.json"}
    for p in targets:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_env_ws_settings() -> tuple[str, str, str]:
    """尝试从 .env 或环境变量读取 WS 连接信息（仅作参考，不强制）。"""
    env_file = _REPO_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip().strip('"').strip("'")

    import os

    def _get(*keys: str) -> str:
        for k in keys:
            v = env_vars.get(k) or os.environ.get(k, "")
            if v:
                return v
        return ""

    host = _get("HOST", "ONEBOT_HOST")
    port = _get("PORT", "ONEBOT_PORT")
    token = _get("ACCESS_TOKEN")
    name = _get("PALLAS_PROTOCOL_ONEBOT_CLIENT_NAME", "ONEBOT_CLIENT_NAME") or "pallas"

    if host and port:
        # 归一化监听地址
        if host in ("0.0.0.0", "::", "[::]"):
            host = "127.0.0.1"
        ws_url = f"ws://{host}:{port}/onebot/v11/ws"
        return ws_url, name, token
    return "", name, token


def import_accounts(
    source_dir: Path,
    accounts_file: Path,
    *,
    dry_run: bool = False,
    skip_existing: bool = True,
    ws_url: str = "",
    ws_name: str = "pallas",
    ws_token: str = "",
) -> None:
    if not source_dir.is_dir():
        print(f"[ERROR] 源目录不存在: {source_dir}")
        sys.exit(1)

    # 加载现有 accounts.json
    if accounts_file.is_file():
        try:
            accounts: dict = json.loads(accounts_file.read_text(encoding="utf-8"))
        except Exception:
            accounts = {}
    else:
        accounts = {}

    subfolders = sorted(p for p in source_dir.iterdir() if p.is_dir())
    if not subfolders:
        print("[WARN] 源目录下没有子文件夹，退出。")
        return

    imported = 0
    skipped = 0
    failed = 0

    for folder in subfolders:
        config_dir = folder / "config"
        if not config_dir.is_dir():
            print(f"[SKIP] {folder.name}: 没有 config/ 子目录")
            skipped += 1
            continue

        qq = _extract_qq_from_config_dir(config_dir)
        if not qq:
            print(f"[FAIL] {folder.name}: 无法从 config/ 提取 QQ 号（未找到 onebot_*.json）")
            failed += 1
            continue

        if skip_existing and qq in accounts:
            print(f"[SKIP] {folder.name}: QQ {qq} 已存在于 accounts.json，跳过")
            skipped += 1
            continue

        webui_port = _next_free_port(accounts)
        webui_token = secrets.token_hex(6)

        account_data_dir = str(folder.resolve())

        account = {
            "id": qq,
            "display_name": folder.name,
            "protocol_backend": "napcat",
            "command": "",
            "args": None,
            "working_dir": "",
            "env": {},
            "enabled": True,
            "qq": qq,
            "ws_url": ws_url,
            "ws_name": ws_name,
            "ws_token": ws_token,
            "program_dir": "",
            "account_data_dir": account_data_dir,
            "webui_port": webui_port,
            "webui_token": webui_token,
        }

        if not dry_run:
            config_dir.mkdir(parents=True, exist_ok=True)
            _sync_onebot(config_dir, qq, ws_url, ws_name, ws_token)
            _sync_napcat(config_dir, qq)
            _sync_webui(config_dir, qq, webui_port, webui_token)
            # 将 QQ/ 复制到 .config/QQ/（NapCat 期望的 QQ NT 数据路径）
            qq_src = folder / "QQ"
            qq_dst = folder / ".config" / "QQ"
            if qq_src.is_dir() and not qq_dst.exists():
                qq_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(str(qq_src), str(qq_dst))
                print("         QQ/ → .config/QQ/ 复制完成")
            elif qq_src.is_dir() and qq_dst.exists():
                print("         .config/QQ/ 已存在，跳过复制")

        accounts[qq] = account
        print(f"[OK]   {folder.name}: QQ={qq}  webui_port={webui_port}" + ("  [DRY RUN]" if dry_run else ""))
        imported += 1

    if not dry_run and imported > 0:
        accounts_file.parent.mkdir(parents=True, exist_ok=True)
        accounts_file.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {accounts_file}")

    print(f"\n完成：导入 {imported}，跳过 {skipped}，失败 {failed}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导入旧协议端账号到 pallas_protocol")
    parser.add_argument("--source", required=True, help="旧账号文件夹的根目录")
    parser.add_argument(
        "--accounts-file",
        default=str(plugin_data_dir("pallas_protocol") / "accounts.json"),
        help="accounts.json 路径（默认 data/pallas_protocol/accounts.json）",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入任何文件")
    parser.add_argument("--no-skip-existing", action="store_true", help="覆盖已存在的账号记录")
    parser.add_argument("--ws-url", default="", help="覆盖 WS URL（默认从 .env 读取）")
    parser.add_argument("--ws-name", default="", help="覆盖 WS 连接名（默认 pallas）")
    parser.add_argument("--ws-token", default="", help="覆盖 WS token（默认从 .env 读取）")
    args = parser.parse_args()

    env_url, env_name, env_token = _load_env_ws_settings()
    ws_url = args.ws_url or env_url
    ws_name = args.ws_name or env_name or "pallas"
    ws_token = args.ws_token or env_token

    if not ws_url:
        print("[WARN] 未能从 .env 读取 WS URL，onebot 配置将使用默认值 ws://127.0.0.1:8088/onebot/v11/ws")
        print("       可用 --ws-url 手动指定，或确保 .env 中有 HOST 和 PORT。\n")

    import_accounts(
        source_dir=Path(args.source).resolve(),
        accounts_file=Path(args.accounts_file).resolve(),
        dry_run=args.dry_run,
        skip_existing=not args.no_skip_existing,
        ws_url=ws_url,
        ws_name=ws_name,
        ws_token=ws_token,
    )


if __name__ == "__main__":
    main()
