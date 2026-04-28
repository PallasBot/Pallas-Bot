"""批量导入旧协议端留存账号。"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003


@dataclass
class ImportResult:
    imported: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


def _extract_qq(config_dir: Path) -> str | None:
    for pat in (r"onebot11_(\d{5,})\.json", r"onebot_(\d{5,})\.json"):
        for f in config_dir.glob("*.json"):
            m = re.fullmatch(pat, f.name)
            if m:
                return m.group(1)
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


def _safe_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _used_ports(accounts: dict) -> set[int]:
    used: set[int] = set()
    for acc in accounts.values():
        try:
            used.add(int(acc.get("webui_port")))
        except (TypeError, ValueError):
            pass
    return used


def _next_port(accounts: dict, lo: int = 6099, hi: int = 7999) -> int:
    used = _used_ports(accounts)
    for p in range(lo, hi + 1):
        if p not in used:
            return p
    raise ValueError("无可用端口")


def _sync_configs(
    config_dir: Path, qq: str, webui_port: int, webui_token: str, ws_url: str, ws_name: str, ws_token: str
) -> None:
    # webui.json
    wp = config_dir / "webui.json"
    wd = _safe_json(wp)
    wd.setdefault("loginRate", 10)
    wd["autoLoginAccount"] = qq
    wd.setdefault("disableWebUI", False)
    wd.setdefault("accessControlMode", "none")
    wd.setdefault("ipWhitelist", [])
    wd.setdefault("ipBlacklist", [])
    wd.setdefault("enableXForwardedFor", False)
    wd["host"] = "127.0.0.1"
    wd["port"] = webui_port
    wd["token"] = webui_token
    wp.write_text(json.dumps(wd, ensure_ascii=False, indent=2), encoding="utf-8")

    # napcat.json
    for np in (config_dir / "napcat.json", config_dir / f"napcat_{qq}.json"):
        nd = _safe_json(np)
        nd["fileLog"] = False
        nd.setdefault("consoleLog", True)
        nd.setdefault("consoleLogLevel", "info")
        nd.setdefault("packetBackend", "auto")
        nd.setdefault("packetServer", "")
        nd.setdefault("o3HookMode", 1)
        nd.setdefault("autoTimeSync", True)
        np.write_text(json.dumps(nd, ensure_ascii=False, indent=2), encoding="utf-8")

    # onebot config
    preferred = [config_dir / f"onebot11_{qq}.json", config_dir / f"onebot_{qq}.json"]
    ob_path = next((p for p in preferred if p.exists()), None)
    if ob_path is None:
        has_legacy = any(p.name.startswith("onebot_") for p in config_dir.glob("onebot_*.json"))
        ob_path = config_dir / (f"onebot_{qq}.json" if has_legacy else f"onebot11_{qq}.json")
    od = _safe_json(ob_path)
    if not isinstance(od.get("network"), dict):
        od["network"] = {}
    net = od["network"]
    net.setdefault("httpServers", [])
    net.setdefault("httpSseServers", [])
    net.setdefault("httpClients", [])
    net.setdefault("websocketServers", [])
    net.setdefault("plugins", [])
    clients = net.get("websocketClients")
    if not isinstance(clients, list):
        clients = []
    if not clients:
        clients.append({})
    c = clients[0]
    c["enable"] = True
    c["name"] = ws_name or "pallas"
    c["url"] = ws_url or "ws://127.0.0.1:8088/onebot/v11/ws"
    c["reportSelfMessage"] = False
    c["messagePostFormat"] = "array"
    c["token"] = ws_token or ""
    c["debug"] = False
    c["heartInterval"] = 5000
    c["reconnectInterval"] = 3000
    net["websocketClients"] = clients
    od.setdefault("musicSignUrl", "https://ss.xingzhige.com/music_card/card")
    od.setdefault("enableLocalFile2Url", False)
    od.setdefault("parseMultMsg", False)
    for tp in {ob_path, config_dir / f"onebot11_{qq}.json"}:
        tp.write_text(json.dumps(od, ensure_ascii=False, indent=2), encoding="utf-8")


def run_import(
    source_dir: Path,
    existing_accounts: dict,
    *,
    dry_run: bool = False,
    skip_existing: bool = True,
    ws_url: str = "",
    ws_name: str = "pallas",
    ws_token: str = "",
    instances_root: Path | None = None,
) -> tuple[ImportResult, dict]:
    """
    扫描 source_dir，返回 (ImportResult, new_accounts_dict)。
    new_accounts_dict 是合并后的完整账号字典（dry_run 时与 existing_accounts 相同）。

    instances_root: 若提供，则将账号数据复制到 instances_root/<qq>/ 并以此作为
                    account_data_dir；否则原地注册（account_data_dir = source folder）。
    """
    result = ImportResult()
    accounts = dict(existing_accounts)

    subfolders = sorted(p for p in source_dir.iterdir() if p.is_dir())
    for folder in subfolders:
        config_dir = folder / "config"
        if not config_dir.is_dir():
            result.skipped.append({"folder": folder.name, "reason": "没有 config/ 子目录"})
            continue

        qq = _extract_qq(config_dir)
        if not qq:
            result.failed.append({"folder": folder.name, "reason": "无法从 config/ 提取 QQ 号"})
            continue

        if skip_existing and qq in accounts:
            result.skipped.append({"folder": folder.name, "qq": qq, "reason": "已存在"})
            continue

        webui_port = _next_port(accounts)
        webui_token = secrets.token_hex(6)

        # 决定 account_data_dir：优先使用 instances_root/<qq>，否则原地注册
        if instances_root is not None:
            account_data_dir = str((instances_root / qq).resolve())
        else:
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

        qq_copied: str | None = None
        if not dry_run:
            if instances_root is not None:
                # 将数据复制到 instances_root/<qq>/
                inst_dir = instances_root / qq
                inst_config_dir = inst_dir / "config"
                inst_config_dir.mkdir(parents=True, exist_ok=True)
                # 复制 config/ 下的所有文件
                for f in config_dir.iterdir():
                    if f.is_file():
                        shutil.copy2(str(f), str(inst_config_dir / f.name))
                # 复制 QQ NT 数据：优先 QQ/，其次 .config/QQ/
                qq_src = folder / "QQ"
                qq_src_legacy = folder / ".config" / "QQ"
                inst_qq_dst = inst_dir / ".config" / "QQ"
                if qq_src.is_dir() and not inst_qq_dst.exists():
                    inst_qq_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(str(qq_src), str(inst_qq_dst))
                    qq_copied = str(inst_qq_dst)
                elif qq_src_legacy.is_dir() and not inst_qq_dst.exists():
                    inst_qq_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(str(qq_src_legacy), str(inst_qq_dst))
                    qq_copied = str(inst_qq_dst)
                # 在 instances 目录写入最终配置
                _sync_configs(inst_config_dir, qq, webui_port, webui_token, ws_url, ws_name, ws_token)
            else:
                # 原地注册：在源目录写入配置
                config_dir.mkdir(parents=True, exist_ok=True)
                _sync_configs(config_dir, qq, webui_port, webui_token, ws_url, ws_name, ws_token)
                qq_src = folder / "QQ"
                qq_dst = folder / ".config" / "QQ"
                if qq_src.is_dir() and not qq_dst.exists():
                    qq_dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(str(qq_src), str(qq_dst))
                    qq_copied = str(qq_dst)

        accounts[qq] = account
        result.imported.append({
            "folder": folder.name,
            "qq": qq,
            "webui_port": webui_port,
            "account_data_dir": account_data_dir,
            **({"qq_copied_to": qq_copied} if qq_copied else {}),
        })

    return result, accounts
