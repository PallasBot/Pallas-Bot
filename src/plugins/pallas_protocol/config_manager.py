import json
from pathlib import Path


class AccountConfigManager:
    def __init__(
        self,
        webui_listen_host: str = "127.0.0.1",
        *,
        webui_port_fallback_min: int = 6099,
    ) -> None:
        self._webui_listen_host = (webui_listen_host or "").strip()
        self._webui_port_fallback_min = int(webui_port_fallback_min)

    def _resolved_webui_host(self) -> str:
        # 归一化 WebUI host
        h = self._webui_listen_host
        if not h or h in ("::", "[::]", "0.0.0.0"):
            return "127.0.0.1"
        return h

    def get_account_configs(self, account: dict, resolve_qq) -> dict:
        qq = resolve_qq(account)
        account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
        config_dir = account_data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        onebot_path = self._resolve_onebot_config_path(config_dir, qq) if qq else config_dir / "onebot11_unknown.json"
        napcat_uin_path = config_dir / f"napcat_{qq}.json" if qq else config_dir / "napcat.json"
        napcat_path = napcat_uin_path if napcat_uin_path.exists() else config_dir / "napcat.json"
        webui_path = config_dir / "webui.json"
        return {
            "paths": {"onebot": str(onebot_path), "napcat": str(napcat_path), "webui": str(webui_path)},
            "onebot": self.safe_read_json(onebot_path),
            "napcat": self.safe_read_json(napcat_path),
            "webui": self.safe_read_json(webui_path),
        }

    def update_account_configs(self, account: dict, payload: dict, resolve_qq) -> dict:
        qq = resolve_qq(account)
        account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
        config_dir = account_data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        onebot_path = self._resolve_onebot_config_path(config_dir, qq) if qq else config_dir / "onebot11_unknown.json"
        napcat_uin_path = config_dir / f"napcat_{qq}.json" if qq else config_dir / "napcat.json"
        napcat_path = napcat_uin_path if napcat_uin_path.exists() else config_dir / "napcat.json"

        if "onebot" in payload and isinstance(payload["onebot"], dict):
            current = self.safe_read_json(onebot_path)
            merged = {**current, **payload["onebot"]}
            for path in self._onebot_sync_targets(config_dir, qq):
                path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            self._sync_account_onebot_fields(account, merged)
        if "napcat" in payload and isinstance(payload["napcat"], dict):
            current = self.safe_read_json(napcat_path)
            merged = {**current, **payload["napcat"]}
            napcat_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        webui_path = config_dir / "webui.json"
        if "webui" in payload and isinstance(payload["webui"], dict):
            current = self.safe_read_json(webui_path)
            merged = {**current, **payload["webui"]}
            webui_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            self._sync_account_webui_fields(account, merged)

        return self.get_account_configs(account, resolve_qq)

    def sync_onebot(self, account: dict, resolve_qq) -> None:
        raw_data_dir = str(account.get("account_data_dir", "")).strip()
        if not raw_data_dir:
            return
        account_data_dir = Path(raw_data_dir)
        qq = resolve_qq(account)
        if not qq:
            return
        config_dir = account_data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = self._resolve_onebot_config_path(config_dir, qq)
        data = self.safe_read_json(config_path)

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
        client["name"] = str(account.get("ws_name", "pallas")).strip() or "pallas"
        ws_url = str(account.get("ws_url", "")).strip()
        if ws_url:
            client["url"] = ws_url
        client.setdefault("url", "ws://127.0.0.1:8088/onebot/v11/ws")
        client["reportSelfMessage"] = False
        client["messagePostFormat"] = "array"
        client["token"] = str(account.get("ws_token", "")).strip()
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
        write_targets: list[Path] = []
        seen_paths: set[Path] = set()
        for p in [config_path, *self._onebot_sync_targets(config_dir, qq)]:
            if p not in seen_paths:
                seen_paths.add(p)
                write_targets.append(p)
        for path in write_targets:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        account["qq"] = qq
        account["onebot_config_path"] = str(config_path)

    def sync_napcat_core(self, account: dict, resolve_qq) -> None:
        account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
        if not str(account_data_dir):
            return
        qq = resolve_qq(account)
        config_dir = account_data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        targets = [config_dir / "napcat.json"]
        if qq:
            targets.append(config_dir / f"napcat_{qq}.json")
        for config_path in targets:
            data = self.safe_read_json(config_path)
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
            config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        account["napcat_config_path"] = str(targets[0])
        self.sync_webui(account, resolve_qq)

    def sync_webui(self, account: dict, resolve_qq) -> None:
        qq = resolve_qq(account)
        account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
        if not str(account_data_dir):
            return
        config_dir = account_data_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        webui_path = config_dir / "webui.json"
        data = self.safe_read_json(webui_path)
        data.setdefault("loginRate", 10)
        # 写入自动登录账号
        q = str(qq or "").strip()
        if q.isdigit():
            data["autoLoginAccount"] = q
        else:
            data.setdefault("autoLoginAccount", "")
        data.setdefault("disableWebUI", False)
        data.setdefault("accessControlMode", "none")
        data.setdefault("ipWhitelist", [])
        data.setdefault("ipBlacklist", [])
        data.setdefault("enableXForwardedFor", False)
        if account.get("napcat_linux_docker"):
            p_int = int(account.get("napcat_docker_internal_webui", 6099))
            data["host"] = "0.0.0.0"
            data["port"] = p_int
        else:
            data["host"] = self._resolved_webui_host()
            port_raw = account.get("webui_port")
            try:
                port = int(port_raw)
                if not (1 <= port <= 65535):
                    raise ValueError
            except (TypeError, ValueError):
                tail = int(qq[-3:]) if qq and qq.isdigit() else 0
                port = self._webui_port_fallback_min + (tail % 1000)
            data["port"] = port
        token = str(account.get("webui_token", "")).strip()
        if token:
            data["token"] = token
        else:
            data.setdefault("token", "")
        webui_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        account["webui_config_path"] = str(webui_path)

    def read_webui_into_account(self, account: dict) -> bool:
        """若 ``webui.json`` 中 port/token 与账号不一致，则更新内存中的 ``account``（是否落盘由调用方决定）。"""
        if account.get("napcat_linux_docker"):
            return False
        account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
        if not account_data_dir.is_dir():
            return False
        webui_path = account_data_dir / "config" / "webui.json"
        if not webui_path.is_file():
            return False
        data = self.safe_read_json(webui_path)
        changed = False
        try:
            p = int(data.get("port"))
            if not (1 <= p <= 65535):
                raise ValueError
        except (TypeError, ValueError):
            return False
        try:
            cur = int(account.get("webui_port")) if account.get("webui_port") is not None else None
        except (TypeError, ValueError):
            cur = None
        if cur != p:
            account["webui_port"] = p
            changed = True
        tok = str(data.get("token", "")).strip()
        if tok and str(account.get("webui_token", "")).strip() != tok:
            account["webui_token"] = tok
            changed = True
        return changed

    def _resolve_onebot_config_path(self, config_dir: Path, qq: str) -> Path:
        preferred = [config_dir / f"onebot11_{qq}.json", config_dir / f"onebot_{qq}.json"]
        for path in preferred:
            if path.exists():
                return path
        canonical = config_dir / "onebot11.json"
        if canonical.exists():
            return canonical
        has_legacy_prefix = any(path.name.startswith("onebot_") for path in config_dir.glob("onebot_*.json"))
        if has_legacy_prefix:
            return config_dir / f"onebot_{qq}.json"
        return config_dir / f"onebot11_{qq}.json"

    def _onebot_sync_targets(self, config_dir: Path, qq: str) -> list[Path]:
        return [config_dir / f"onebot11_{qq}.json", config_dir / "onebot11.json"]

    def safe_read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _sync_account_onebot_fields(self, account: dict, onebot_json: dict) -> None:
        network = onebot_json.get("network")
        if not isinstance(network, dict):
            return
        clients = network.get("websocketClients")
        if not isinstance(clients, list) or not clients:
            return
        first = clients[0]
        if not isinstance(first, dict):
            return
        url = str(first.get("url", "")).strip()
        name = str(first.get("name", "")).strip()
        token = str(first.get("token", "")).strip()
        if url:
            account["ws_url"] = url
        if name:
            account["ws_name"] = name
        account["ws_token"] = token

    def _sync_account_webui_fields(self, account: dict, webui_json: dict) -> None:
        try:
            port = int(webui_json.get("port"))
            if 1 <= port <= 65535:
                account["webui_port"] = port
        except (TypeError, ValueError):
            pass
        token = str(webui_json.get("token", "")).strip()
        if token:
            account["webui_token"] = token
