import asyncio
import hashlib
import ipaddress
import json
import logging
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from maibot_sdk import LLMProvider, MaiBotPlugin

_ENDPOINT_PATH = "/pallas/api/internal/maibot/provider"
_TOKEN_HEADER = "X-Pallas-Internal-Token"
_MAX_RESPONSE_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_HTTP_ERROR = "Pallas provider request failed"
_HEALTH_ERROR = "Pallas provider health check failed"
_ACTIVATION_ERROR = "Pallas plugin activation lease refresh failed"
_ACTIVATION_INTERVAL_SEC = 5.0
_ACTIVATION_TIMEOUT_SEC = 2.0
_ACTIVATION_LOG_INTERVAL_SEC = 30.0
_ACTIVATION_PATH = "/activation"
_ASSET_HASH_DOMAIN = b"pallas-maibot-plugin-assets-v1\x00"
_EMBEDDING_ALIAS = re.compile(r"^pb-embedding-[0-9a-f]{24}$")
_logger = logging.getLogger(__name__)


def _plugin_identity_and_hash() -> tuple[str, str, str]:
    root = Path(__file__).resolve().parent
    manifest_bytes = (root / "_manifest.json").read_bytes()
    plugin_bytes = (root / "plugin.py").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    plugin_id, version = manifest.get("id"), manifest.get("version")
    if not isinstance(plugin_id, str) or not plugin_id or not isinstance(version, str) or not version:
        raise ValueError
    digest = hashlib.sha256(_ASSET_HASH_DOMAIN)
    for name, content in (("plugin.py", plugin_bytes), ("_manifest.json", manifest_bytes)):
        digest.update(name.encode("ascii") + b"\x00")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return plugin_id, version, digest.hexdigest()


def _endpoint_from_env() -> tuple[str, str]:
    endpoint = os.environ.get("PALLAS_MAIBOT_PROVIDER_URL", "")
    token = os.environ.get("PALLAS_MAIBOT_PROVIDER_TOKEN", "")
    if not endpoint or not endpoint.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in endpoint):
        raise ValueError
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        address = ipaddress.ip_address(host or "")
        _ = parsed.port
        token.encode("ascii")
    except (ValueError, UnicodeEncodeError):
        raise ValueError from None
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or "%" in host
        or not address.is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or "?" in endpoint
        or "#" in endpoint
        or parsed.path != _ENDPOINT_PATH
        or not token
        or any(ord(char) < 32 or ord(char) == 127 for char in token)
    ):
        raise ValueError
    return endpoint, token


def _request_payload(request: object) -> tuple[dict[str, object], float]:
    if not isinstance(request, dict) or request.get("request_kind") != "response":
        raise ValueError
    if request.get("item_schema_version") != 1 or type(request.get("item_schema_version")) is not int:
        raise ValueError
    if request.get("extra_params") != {}:
        raise ValueError
    model = request.get("model_info")
    provider = request.get("api_provider")
    if not isinstance(model, dict) or not isinstance(provider, dict):
        raise ValueError
    alias = model.get("name")
    if alias not in {"pb-route-chat", "pb-route-decision"} or model.get("model_identifier") != alias:
        raise ValueError
    if model.get("api_provider") != "pallas-managed" or model.get("extra_params") != {}:
        raise ValueError
    identity = tuple(provider.get(key) for key in ("name", "client_type", "api_key", "auth_type"))
    if (
        identity != ("pallas-managed", "pallas-managed", "", "none")
        or type(provider.get("max_retry")) is not int
        or provider.get("max_retry") != 1
    ):
        raise ValueError
    timeout_sec = provider.get("timeout")
    if type(timeout_sec) not in (int, float) or not math.isfinite(timeout_sec) or timeout_sec <= 0:
        raise ValueError
    if not isinstance(request.get("logical_turn_id"), str) or not request["logical_turn_id"]:
        raise ValueError
    if not isinstance(request.get("context_items"), list):
        raise ValueError
    return {
        "item_schema_version": 1,
        "request_id": uuid4().hex,
        "alias": alias,
        "logical_turn_id": request["logical_turn_id"],
        "context_items": request["context_items"],
        "tool_options": request.get("tool_options"),
        "tool_choice": request.get("tool_choice"),
        "response_format": request.get("response_format"),
        "max_tokens": request.get("max_tokens"),
        "temperature": request.get("temperature"),
        "deadline_ms": None,
    }, min(float(timeout_sec), 600.0)


def _embedding_request_payload(request: object) -> tuple[dict[str, object], float]:
    if not isinstance(request, dict) or request.get("request_kind") != "embedding":
        raise ValueError
    if request.keys() != {"embedding_input", "extra_params", "model_info", "request_kind", "api_provider"}:
        raise ValueError
    text = request.get("embedding_input")
    model = request.get("model_info")
    provider = request.get("api_provider")
    extra_params = request.get("extra_params")
    if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
        raise ValueError
    if not isinstance(model, dict) or not isinstance(provider, dict) or not isinstance(extra_params, dict):
        raise ValueError
    alias = model.get("name")
    if (
        not isinstance(alias, str)
        or not _EMBEDDING_ALIAS.fullmatch(alias)
        or model.get("model_identifier") != alias
        or model.get("model_type") != "embedding"
        or model.get("api_provider") != "pallas-managed"
        or not isinstance(model.get("extra_params"), dict)
    ):
        raise ValueError
    dimensions = None
    for values in (extra_params, model.get("extra_params") or {}):
        if not isinstance(values, dict) or values.keys() - {"dimensions", "output_dimensionality"}:
            raise ValueError
        for key in ("dimensions", "output_dimensionality"):
            value = values.get(key)
            if value is None:
                continue
            if type(value) is not int or value < 1 or value > 8192 or (dimensions is not None and dimensions != value):
                raise ValueError
            dimensions = value
    identity = tuple(provider.get(key) for key in ("name", "client_type", "api_key", "auth_type"))
    if (
        identity != ("pallas-managed", "pallas-managed", "", "none")
        or type(provider.get("max_retry")) is not int
        or provider.get("max_retry") != 1
    ):
        raise ValueError
    timeout_sec = provider.get("timeout")
    if type(timeout_sec) not in (int, float) or not math.isfinite(timeout_sec) or timeout_sec <= 0:
        raise ValueError
    payload: dict[str, object] = {
        "item_schema_version": 1,
        "request_id": uuid4().hex,
        "alias": alias,
        "input": text,
        "deadline_ms": min(600_000, max(0, int(float(timeout_sec) * 1000))),
    }
    if dimensions is not None:
        payload["dimensions"] = dimensions
    return payload, min(float(timeout_sec), 600.0)


async def _read_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    token: str,
    timeout_sec: float,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        async with asyncio.timeout(timeout_sec):
            async with client.stream(
                method,
                url,
                headers={_TOKEN_HEADER: token},
                json=payload,
                timeout=timeout_sec,
                follow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise ValueError
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes(chunk_size=_READ_CHUNK_BYTES):
                    size += len(chunk)
                    if size > _MAX_RESPONSE_BYTES:
                        raise ValueError
                    chunks.append(chunk)
        result = json.loads(b"".join(chunks).decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except asyncio.CancelledError:
        raise
    except Exception:
        raise RuntimeError(_HTTP_ERROR) from None


class PallasManagedProviderPlugin(MaiBotPlugin):
    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._endpoint = ""
        self._token = ""
        self._runtime_id = ""
        self._plugin_id = ""
        self._version = ""
        self._asset_sha256 = ""
        self._runner_pid = 0
        self._host_pid = 0
        self._activation_task: asyncio.Task[None] | None = None
        self._activation_log_at = 0.0

    async def on_load(self) -> None:
        client = None
        try:
            endpoint, token = _endpoint_from_env()
            client = httpx.AsyncClient(timeout=5.0, trust_env=False, follow_redirects=False)
            health = await _read_json(client, "GET", f"{endpoint}/health", token, 5.0)
            plugin_id, version, asset_sha256 = _plugin_identity_and_hash()
            if (
                health.get("ok") is not True
                or health.get("ready") is not True
                or (
                    health.get("binding_version"),
                    health.get("readiness_scope"),
                    health.get("budget_policy"),
                )
                != ("maibot-provider-bindings-v1", "provider-http", "native-cycle+pallas-request-v1")
                or not isinstance(health.get("runtime_id"), str)
                or not health["runtime_id"]
                or plugin_id != "pallas.maibot_managed_provider"
                or version != "1.0.0"
            ):
                raise ValueError
        except asyncio.CancelledError:
            if client is not None:
                await client.aclose()
            raise
        except Exception:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
            raise RuntimeError(_HEALTH_ERROR) from None
        self._client = client
        self._endpoint = endpoint
        self._token = token
        self._runtime_id = health["runtime_id"]
        self._plugin_id = plugin_id
        self._version = version
        self._asset_sha256 = asset_sha256
        self._runner_pid = os.getpid()
        self._host_pid = os.getppid()
        self._activation_task = asyncio.create_task(self._activation_loop(), name="pallas-maibot-activation")

    async def on_unload(self) -> None:
        client, self._client = self._client, None
        task, self._activation_task = self._activation_task, None
        endpoint, token = self._endpoint, self._token
        activation = self._activation_payload(False)
        self._endpoint = ""
        self._token = ""
        try:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current is not None and current.cancelling():
                        raise
            if client is not None and endpoint and token and activation is not None:
                try:
                    await self._post_activation(client, endpoint, token, activation)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._log_activation_failure()
        finally:
            self._runtime_id = ""
            self._plugin_id = ""
            self._version = ""
            self._asset_sha256 = ""
            self._runner_pid = self._host_pid = 0
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    raise RuntimeError(_HTTP_ERROR) from None

    def _activation_payload(self, active: bool) -> dict[str, object] | None:
        if not self._runtime_id or not self._asset_sha256 or not self._runner_pid or not self._host_pid:
            return None
        return {
            "schema_version": 1,
            "runtime_id": self._runtime_id,
            "plugin_id": self._plugin_id,
            "version": self._version,
            "asset_sha256": self._asset_sha256,
            "runner_pid": self._runner_pid,
            "host_pid": self._host_pid,
            "active": active,
        }

    async def _post_activation(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        token: str,
        payload: dict[str, object],
    ) -> None:
        result = await _read_json(
            client,
            "POST",
            f"{endpoint}{_ACTIVATION_PATH}",
            token,
            _ACTIVATION_TIMEOUT_SEC,
            payload,
        )
        if result.get("ok") is not True or result.get("active") is not payload["active"]:
            raise RuntimeError(_ACTIVATION_ERROR)

    async def _activation_loop(self) -> None:
        client = self._client
        payload = self._activation_payload(True)
        if client is None or payload is None:
            return
        while True:
            try:
                await self._post_activation(client, self._endpoint, self._token, payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._log_activation_failure()
            await asyncio.sleep(_ACTIVATION_INTERVAL_SEC)

    def _log_activation_failure(self) -> None:
        now = time.monotonic()
        if now - self._activation_log_at >= _ACTIVATION_LOG_INTERVAL_SEC:
            self._activation_log_at = now
            _logger.warning(_ACTIVATION_ERROR)

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        return None

    @LLMProvider(
        client_type="pallas-managed",
        name="Pallas Managed Provider",
        description="Routes MaiBot response and embedding requests through Pallas managed providers.",
        version="1.0.0",
    )
    async def handle_provider(self, operation: str, request: dict) -> dict[str, object]:
        if operation not in {"response", "embedding"}:
            raise RuntimeError("Unsupported MaiBot provider operation")
        client = self._client
        if client is None:
            raise RuntimeError(_HTTP_ERROR)
        try:
            if operation == "embedding":
                payload, timeout = _embedding_request_payload(request)
            else:
                payload, timeout = _request_payload(request)
            deadline = time.monotonic() + timeout
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            payload["deadline_ms"] = (
                min(int(payload["deadline_ms"]), remaining_ms)
                if operation == "embedding"
                else min(600_000, remaining_ms)
            )
            if payload["deadline_ms"] == 0:
                raise ValueError
            path = "embedding" if operation == "embedding" else "complete"
            result = await _read_json(
                client,
                "POST",
                f"{self._endpoint}/{path}",
                self._token,
                max(0.001, deadline - time.monotonic()),
                payload,
            )
            if result.get("ok") is not True or result.get("request_id") != payload["request_id"]:
                raise ValueError
            if operation == "embedding":
                vector = result.get("embedding")
                if (
                    result.get("embedding_alias") != payload["alias"]
                    or not isinstance(vector, list)
                    or not vector
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector)
                    or (payload.get("dimensions") is not None and len(vector) != payload["dimensions"])
                ):
                    raise ValueError
                return {"embedding": [float(value) for value in vector], "embedding_alias": payload["alias"]}
            if (
                type(result.get("item_schema_version")) is not int
                or result.get("item_schema_version") != 1
                or not isinstance(result.get("output_items"), list)
            ):
                raise ValueError
            return {key: value for key, value in result.items() if key not in {"ok", "request_id"}}
        except asyncio.CancelledError:
            raise
        except Exception:
            raise RuntimeError(_HTTP_ERROR) from None


def create_plugin() -> PallasManagedProviderPlugin:
    return PallasManagedProviderPlugin()
