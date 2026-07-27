"""Pallas-Bot WebUI console API: AI extension routes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from packages.pb_webui.console_openapi_models import _ApiOkResponse

from .console_read_cache import cached_read, drop_read_cache
from .data_dir import pb_webui_data_dir
from .extended_common import (
    check_pallas_write_token,
)
from .manager import pallas_bot_repo_root

if TYPE_CHECKING:
    from .config import Config


def _ai_extension_config_path():
    return pb_webui_data_dir() / "ai_extension.json"


def _ai_extension_log_roots() -> list[Path]:
    from pallas.console.web.ai_extension_logs import ai_extension_log_roots

    return ai_extension_log_roots(pallas_bot_repo_root())


def _is_allowed_log_path(path_s: str) -> bool:
    from pallas.console.web.ai_extension_logs import is_allowed_log_path

    return is_allowed_log_path(path_s, _ai_extension_log_roots())


def _normalize_ai_extension_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    d = raw or {}
    base_url = str(d.get("base_url", "")).strip() or "http://127.0.0.1:9099"
    api_prefix = str(d.get("api_prefix", "")).strip() or "/api"
    if not api_prefix.startswith("/"):
        api_prefix = "/" + api_prefix
    token = str(d.get("token", "")).strip()
    health_paths_raw = d.get("health_paths", ["/health"])
    if isinstance(health_paths_raw, list):
        health_paths = [str(x).strip() for x in health_paths_raw if str(x).strip()]
    else:
        health_paths = ["/health"]
    if not health_paths:
        health_paths = ["/health"]
    from pallas.console.web.ai_extension_logs import normalize_ai_extension_log_paths

    root = pallas_bot_repo_root()
    log_paths = normalize_ai_extension_log_paths(d, bot_repo_root=root)
    uvicorn_log_file = log_paths["uvicorn_log_file"]
    celery_log_file = log_paths["celery_log_file"]
    celery_media_log_file = log_paths["celery_media_log_file"]
    timeout_sec = d.get("timeout_sec", 8)
    try:
        timeout_i = int(timeout_sec)
    except (TypeError, ValueError):
        timeout_i = 8
    timeout_i = max(2, min(timeout_i, 30))
    return {
        "base_url": base_url.rstrip("/"),
        "api_prefix": api_prefix,
        "token": token,
        "health_paths": health_paths,
        "uvicorn_log_file": uvicorn_log_file,
        "celery_log_file": celery_log_file,
        "celery_media_log_file": celery_media_log_file,
        "timeout_sec": timeout_i,
    }


def _load_ai_extension_config() -> dict[str, Any]:
    path = _ai_extension_config_path()
    if not path.exists():
        return _normalize_ai_extension_config(None)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return _normalize_ai_extension_config(None)
    if not isinstance(raw, dict):
        return _normalize_ai_extension_config(None)
    return _normalize_ai_extension_config(raw)


def _save_ai_extension_config(data: dict[str, Any]) -> dict[str, Any]:
    clean = _normalize_ai_extension_config(data)
    path = _ai_extension_config_path()
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


async def ai_extension_http_json(
    *,
    method: Literal["GET", "POST"],
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    cfg = _load_ai_extension_config()
    base = str(cfg["base_url"]).rstrip("/")
    api_prefix = str(cfg.get("api_prefix", "/api")).strip() or "/api"
    if not api_prefix.startswith("/"):
        api_prefix = "/" + api_prefix
    merged_path = f"{api_prefix.rstrip('/')}/{path.lstrip('/')}"
    p = merged_path if merged_path.startswith("/") else f"/{merged_path}"
    url = f"{base}{p}"
    headers = {"Content-Type": "application/json"}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    data_b = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data_b)

    def _do() -> tuple[int, str]:
        with urllib.request.urlopen(req, timeout=float(cfg["timeout_sec"])) as resp:
            status_code = int(getattr(resp, "status", 200) or 200)
            txt = resp.read().decode("utf-8", errors="ignore")
            return status_code, txt

    try:
        status_code, txt = await asyncio.to_thread(_do)
        try:
            data = json.loads(txt) if txt else {}
        except Exception:  # noqa: BLE001
            data = {"raw": txt}
        return {"ok": 200 <= status_code < 300, "status_code": status_code, "url": url, "data": data, "error": None}
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status_code": int(getattr(e, "code", 0) or 0),
            "url": url,
            "data": {},
            "error": str(e),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status_code": None, "url": url, "data": {}, "error": str(e)}


class _AiExtensionConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=7, max_length=200)
    api_prefix: str = Field(default="/api", min_length=1, max_length=50)
    token: str = Field(
        default="",
        max_length=300,
        description="Bearer Token；须与 AI 侧 PALLAS_AI_API_TOKEN 一致，供 /api/ops/logs 等 HTTP 回退鉴权",
    )
    health_paths: list[str] = Field(default_factory=lambda: ["/health"], max_length=8)
    uvicorn_log_file: str = Field(default="", max_length=500)
    celery_log_file: str = Field(default="", max_length=500)
    celery_media_log_file: str = Field(default="", max_length=500)
    timeout_sec: int = Field(default=8, ge=2, le=30)


class _AiNcmSendSmsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=5, max_length=32)
    ctcode: int = Field(default=86, ge=1, le=999)


class _AiNcmVerifySmsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=5, max_length=32)
    captcha: str = Field(min_length=2, max_length=16)
    ctcode: int = Field(default=86, ge=1, le=999)


class _AiInstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["clone", "bootstrap", "clone_and_bootstrap"] = "clone_and_bootstrap"
    no_start: bool = False
    # 兼容旧客户端；bootstrap 已固定媒体栈，以下两项忽略
    remote_only: bool = False
    with_media: bool = True
    use_gpu: bool = False


class _AiRuntimeControlBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 兼容旧客户端；启动固定 media + api
    with_media: bool = True


class _AiExtensionTestData(BaseModel):
    ok: bool
    status_code: int | None = None
    health_url: str = ""
    tried_urls: list[str] = Field(default_factory=list)
    error: str | None = None
    media_tasks: dict[str, Any] | None = None
    llm_detail: str | None = None
    image_circuit: dict[str, Any] | None = None
    llm_health: dict[str, Any] | None = None
    tts_health: dict[str, Any] | None = None


def register_ai_extension_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/ai-extension/config", include_in_schema=True)
    async def _ai_extension_get() -> JSONResponse:
        from packages.pb_webui import extended_api as ext

        return JSONResponse({"ok": True, "data": ext._load_ai_extension_config()})

    @router.put(f"{x}/ai-extension/config", include_in_schema=True)
    async def _ai_extension_put(
        body: _AiExtensionConfigBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        clean = _save_ai_extension_config(body.model_dump())
        from pallas.console.webui.ai_install_writeback import sync_ai_server_from_extension_base_url

        synced = sync_ai_server_from_extension_base_url(str(clean.get("base_url") or ""))
        return JSONResponse({"ok": True, "data": clean, "synced_ai_server": synced})

    @router.post(
        f"{x}/ai-extension/test",
        include_in_schema=True,
        response_model=_ApiOkResponse[_AiExtensionTestData],
    )
    async def _ai_extension_test() -> dict[str, Any]:
        import json
        import urllib.error
        import urllib.request

        from packages.pb_webui import extended_api as ext

        cfg = ext._load_ai_extension_config()
        tried_urls: list[str] = []
        headers: dict[str, str] = {}
        if cfg.get("token"):
            headers["Authorization"] = f"Bearer {cfg['token']}"
        base = str(cfg["base_url"]).rstrip("/")
        paths = [str(x) for x in cfg.get("health_paths", []) if str(x).strip()]
        last_error = "未命中可用健康检查地址"
        last_status: int | None = None
        last_url = ""
        last_media_tasks: dict[str, int] | None = None
        last_llm_detail: str | None = None
        last_image_circuit: dict[str, object] | None = None
        last_llm_health: dict[str, object] | None = None
        last_tts_health: dict[str, object] | None = None

        def parse_health_payload(
            payload: object,
        ) -> tuple[
            dict[str, Any] | None,
            str | None,
            dict[str, object] | None,
            dict[str, object] | None,
            dict[str, object] | None,
        ]:
            from pallas.product.llm.ai_health_parse import (
                image_health_circuit,
                llm_health_runtime_detail,
                llm_health_summary,
                parse_media_tasks,
                tts_health_summary,
            )

            media_tasks = parse_media_tasks(payload)
            llm_detail = llm_health_runtime_detail(payload)
            image_circuit = image_health_circuit(payload)
            llm_health = llm_health_summary(payload)
            tts_health = tts_health_summary(payload)
            return media_tasks, llm_detail, image_circuit, llm_health, tts_health

        for p in paths:
            pp = p if p.startswith("/") else f"/{p}"
            health_url = f"{base}{pp}"
            tried_urls.append(health_url)
            req = urllib.request.Request(health_url, method="GET", headers=headers)

            def _do_request(
                _req=req,
            ) -> tuple[
                int,
                dict[str, Any] | None,
                str | None,
                dict[str, object] | None,
                dict[str, object] | None,
                dict[str, object] | None,
            ]:
                with urllib.request.urlopen(_req, timeout=float(cfg["timeout_sec"])) as resp:
                    status_code = int(getattr(resp, "status", 200) or 200)
                    media_tasks = None
                    llm_detail = None
                    image_circuit = None
                    llm_health = None
                    tts_health = None
                    try:
                        body_text = resp.read().decode("utf-8", errors="replace")
                        (
                            media_tasks,
                            llm_detail,
                            image_circuit,
                            llm_health,
                            tts_health,
                        ) = parse_health_payload(json.loads(body_text))
                    except (json.JSONDecodeError, UnicodeError, ValueError, TypeError):
                        pass
                    return status_code, media_tasks, llm_detail, image_circuit, llm_health, tts_health

            try:
                (
                    status_code,
                    media_tasks,
                    llm_detail,
                    image_circuit,
                    llm_health,
                    tts_health,
                ) = await asyncio.to_thread(_do_request)
                if 200 <= status_code < 300:
                    return {
                        "ok": True,
                        "data": {
                            "ok": True,
                            "status_code": status_code,
                            "health_url": health_url,
                            "tried_urls": tried_urls,
                            "error": None,
                            "media_tasks": media_tasks,
                            "llm_detail": llm_detail,
                            "image_circuit": image_circuit,
                            "llm_health": llm_health,
                            "tts_health": tts_health,
                        },
                    }
                last_status = status_code
                last_error = f"HTTP {status_code}"
                last_url = health_url
                last_media_tasks = media_tasks
                last_llm_detail = llm_detail
                last_image_circuit = image_circuit
                last_llm_health = llm_health
                last_tts_health = tts_health
            except urllib.error.HTTPError as e:
                last_status = int(getattr(e, "code", 0) or 0)
                last_error = str(e)
                # 失败时保留首次尝试地址，避免末尾兼容路径（如 /api/health）掩盖规范 /health
                if not last_url:
                    last_url = health_url
                try:
                    body_text = e.read().decode("utf-8", errors="replace")
                    (
                        last_media_tasks,
                        last_llm_detail,
                        last_image_circuit,
                        last_llm_health,
                        last_tts_health,
                    ) = parse_health_payload(json.loads(body_text))
                except (json.JSONDecodeError, UnicodeError, ValueError, TypeError):
                    last_media_tasks = None
                    last_llm_detail = None
                    last_image_circuit = None
                    last_llm_health = None
                    last_tts_health = None
            except Exception as e:  # noqa: BLE001
                last_status = None
                last_error = str(e)
                if not last_url:
                    last_url = health_url
        if not last_url and tried_urls:
            last_url = tried_urls[0]
        return {
            "ok": True,
            "data": {
                "ok": False,
                "status_code": last_status,
                "health_url": last_url,
                "tried_urls": tried_urls,
                "error": last_error,
                "media_tasks": last_media_tasks,
                "llm_detail": last_llm_detail,
                "image_circuit": last_image_circuit,
                "llm_health": last_llm_health,
                "tts_health": last_tts_health,
            },
        }

    async def _ai_extension_http_json(
        *,
        method: Literal["GET", "POST"],
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        from packages.pb_webui import extended_api as ext

        cfg = ext._load_ai_extension_config()
        base = str(cfg["base_url"]).rstrip("/")
        api_prefix = str(cfg.get("api_prefix", "/api")).strip() or "/api"
        if not api_prefix.startswith("/"):
            api_prefix = "/" + api_prefix
        merged_path = f"{api_prefix.rstrip('/')}/{path.lstrip('/')}"
        p = merged_path if merged_path.startswith("/") else f"/{merged_path}"
        url = f"{base}{p}"
        headers = {"Content-Type": "application/json"}
        if cfg.get("token"):
            headers["Authorization"] = f"Bearer {cfg['token']}"
        data_b = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
        req = urllib.request.Request(url, method=method, headers=headers, data=data_b)

        def _do() -> tuple[int, str]:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout_sec"])) as resp:
                status_code = int(getattr(resp, "status", 200) or 200)
                txt = resp.read().decode("utf-8", errors="ignore")
                return status_code, txt

        try:
            status_code, txt = await asyncio.to_thread(_do)
            try:
                data = json.loads(txt) if txt else {}
            except Exception:  # noqa: BLE001
                data = {"raw": txt}
            return {"ok": 200 <= status_code < 300, "status_code": status_code, "url": url, "data": data, "error": None}
        except urllib.error.HTTPError as e:
            return {
                "ok": False,
                "status_code": int(getattr(e, "code", 0) or 0),
                "url": url,
                "data": {},
                "error": str(e),
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "status_code": None, "url": url, "data": {}, "error": str(e)}

    @router.get(f"{x}/ai-extension/logs", include_in_schema=True)
    async def _ai_extension_logs(
        kind: Literal["uvicorn", "celery", "celery-media"] = Query(default="uvicorn"),
        n: int = Query(default=200, ge=1, le=2000),
    ) -> JSONResponse:
        from packages.pb_webui import extended_api as ext
        from pallas.console.web.ai_extension_log_read import read_ai_extension_logs_payload

        cfg = ext._load_ai_extension_config()
        data = await read_ai_extension_logs_payload(
            cfg,
            kind,
            n,
            http_json=ai_extension_http_json,
            is_allowed_log_path=_is_allowed_log_path,
        )
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/ai-extension/logs/stream", include_in_schema=True)
    async def _ai_extension_logs_stream(
        kind: Literal["uvicorn", "celery", "celery-media"] = Query(default="uvicorn"),
        last_event_id: int | None = Query(
            default=None,
            description="断点续传：仅发送字节偏移大于该值的新行",
        ),
        last_event_id_header: int | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        from packages.pb_webui import extended_api as ext
        from pallas.console.web.ai_extension_log_remote import iter_remote_ai_extension_logs_sse
        from pallas.console.web.ai_extension_logs import (
            ai_extension_log_missing_message,
            resolve_log_path_for_kind,
        )
        from pallas.console.web.ai_log_sse import iter_ai_log_file_sse

        cfg = ext._load_ai_extension_config()
        path_s = resolve_log_path_for_kind(cfg, kind)
        if not _is_allowed_log_path(path_s):

            async def _denied() -> Any:
                payload = {
                    "type": "error",
                    "kind": kind,
                    "path": path_s,
                    "error": "日志路径越界，已拒绝",
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                _denied(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        p = Path(path_s)
        use_local = await asyncio.to_thread(p.is_file)
        resume_id = last_event_id if last_event_id is not None else last_event_id_header
        if use_local:
            stream = iter_ai_log_file_sse(
                p,
                kind=kind,
                last_event_id=resume_id,
                missing_message=ai_extension_log_missing_message(cfg, path_s=path_s),
            )
        else:
            stream = iter_remote_ai_extension_logs_sse(
                cfg,
                kind,
                http_json=ai_extension_http_json,
            )
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get(f"{x}/ai-extension/install/status", include_in_schema=True)
    async def _ai_extension_install_status() -> JSONResponse:
        from pallas.console.cli.ai_install import ai_install_status

        data = await asyncio.to_thread(ai_install_status)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/ai-extension/install", include_in_schema=True)
    async def _ai_extension_install(
        body: _AiInstallBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.ai_install import clone_ai_repo, run_ai_bootstrap_captured
        from pallas.console.cli.ai_ops import resolve_ai_repo_root
        from pallas.console.webui.ai_install_progress import create_ai_install_job, run_ai_install_job

        job = create_ai_install_job(body.action)

        def _runner(j: Any) -> None:
            try:
                ai_root = None
                if body.action in ("clone", "clone_and_bootstrap"):
                    j.push("running", "正在克隆 Pallas-Bot-AI…")
                    existing = resolve_ai_repo_root()
                    if existing is not None:
                        if body.action == "clone":
                            j.result = {"ai_root": str(existing), "skipped_clone": True}
                            j.push("done", "已检测到 AI 仓，跳过克隆", result=j.result)
                            return
                        j.push("running", "已检测到 AI 仓，跳过克隆")
                        ai_root = existing
                    else:
                        ai_root = clone_ai_repo()
                        j.push("running", f"克隆完成: {ai_root}")
                if body.action in ("bootstrap", "clone_and_bootstrap"):
                    ai_root = ai_root or resolve_ai_repo_root()
                    if ai_root is None:
                        j.push("failed", error="未找到 Pallas-Bot-AI，请先克隆")
                        return
                    j.push("running", "正在运行 ai_bootstrap.sh…")
                    code, output = run_ai_bootstrap_captured(
                        ai_root=ai_root,
                        no_start=body.no_start,
                        remote_only=body.remote_only,
                        with_media=body.with_media,
                        use_gpu=body.use_gpu,
                    )
                    j.result = {
                        "ai_root": str(ai_root),
                        "exit_code": code,
                        "output_tail": output[-8000:],
                    }
                    if code != 0:
                        j.push("failed", error=f"bootstrap 退出码 {code}", result=j.result)
                        return
                    from pallas.console.webui.ai_install_writeback import (
                        apply_ai_install_connection_writeback,
                    )

                    writeback = apply_ai_install_connection_writeback()
                    from pallas.console.cli.ai_supervisor import ai_runtime_status

                    j.result = {
                        **j.result,
                        **writeback,
                        "runtime": ai_runtime_status(ai_root=ai_root),
                    }
                    j.message = "bootstrap 完成"
                elif body.action == "clone":
                    j.result = {"ai_root": str(ai_root)}
                    j.message = "克隆完成"
            except Exception as e:  # noqa: BLE001
                j.push("failed", error=str(e))

        asyncio.create_task(run_ai_install_job(job, _runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "action": job.action}})

    @router.get(f"{x}/ai-extension/install/jobs/{{job_id}}/stream", include_in_schema=True)
    async def _ai_extension_install_job_stream(job_id: str) -> StreamingResponse:
        from pallas.console.webui.ai_install_progress import iter_ai_install_job_sse

        return StreamingResponse(
            iter_ai_install_job_sse(job_id.strip()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get(f"{x}/ai-extension/runtime/status", include_in_schema=True)
    async def _ai_extension_runtime_status() -> JSONResponse:
        from pallas.console.cli.ai_supervisor import ai_runtime_status

        data = await asyncio.to_thread(ai_runtime_status)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/ai-extension/runtime/start", include_in_schema=True)
    async def _ai_extension_runtime_start(
        body: _AiRuntimeControlBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.ai_supervisor import start_ai_runtime

        data = await asyncio.to_thread(start_ai_runtime, with_media=body.with_media)
        status = 200 if data.get("ok") else 400
        return JSONResponse({"ok": bool(data.get("ok")), "data": data}, status_code=status)

    @router.post(f"{x}/ai-extension/runtime/stop", include_in_schema=True)
    async def _ai_extension_runtime_stop(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.ai_supervisor import stop_ai_runtime

        data = await asyncio.to_thread(stop_ai_runtime)
        status = 200 if data.get("ok") else 400
        return JSONResponse({"ok": bool(data.get("ok")), "data": data}, status_code=status)

    @router.get(f"{x}/ai-extension/ncm/status", include_in_schema=True)
    async def _ai_extension_ncm_status() -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return await _ai_extension_http_json(method="GET", path="/ncm/login/status")

        d = await cached_read(key="ai_extension_ncm_status", loader=_load, ttl_sec=3.0, stale_sec=30.0)
        return JSONResponse({"ok": True, "data": d})

    @router.post(f"{x}/ai-extension/ncm/send-sms", include_in_schema=True)
    async def _ai_extension_ncm_send_sms(
        body: _AiNcmSendSmsBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        d = await _ai_extension_http_json(
            method="POST",
            path="/ncm/login/cellphone/send-sms",
            body=body.model_dump(),
        )
        drop_read_cache(("ai_extension_ncm_status",))
        return JSONResponse({"ok": True, "data": d})

    @router.post(f"{x}/ai-extension/ncm/verify-sms", include_in_schema=True)
    async def _ai_extension_ncm_verify_sms(
        body: _AiNcmVerifySmsBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        d = await _ai_extension_http_json(
            method="POST",
            path="/ncm/login/cellphone/verify-sms",
            body=body.model_dump(),
        )
        drop_read_cache(("ai_extension_ncm_status",))
        return JSONResponse({"ok": True, "data": d})

    @router.post(f"{x}/ai-extension/ncm/logout", include_in_schema=True)
    async def _ai_extension_ncm_logout(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        d = await _ai_extension_http_json(method="POST", path="/ncm/login/logout", body={})
        drop_read_cache(("ai_extension_ncm_status",))
        return JSONResponse({"ok": True, "data": d})
