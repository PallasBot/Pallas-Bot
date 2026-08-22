from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.routing import _IncludedRouter

from packages.pb_webui import extended_api as mod
from packages.pb_webui import llm_ops_api
from packages.pb_webui.config import Config
from pallas.product.persona.bundle_export import PersonaAssetBundleV1
from pallas.product.persona.compile_persona_prompt import (
    PersonaPromptBundle,
    PersonaPromptMetadata,
    PersonaPromptSections,
)


def _find_console_route_endpoint(app: FastAPI, path: str, method: str | None = None):
    """FastAPI 0.141 include_router 把路由包进 _IncludedRouter，需展开查找。"""

    def _walk(routes):
        for route in routes:
            if isinstance(route, _IncludedRouter):
                yield from _walk(route.effective_candidates())
            else:
                yield route

    for candidate in _walk(app.routes):
        if getattr(candidate, "path", "") == path and (
            method is None or method.upper() in getattr(candidate, "methods", set())
        ):
            return getattr(candidate, "endpoint", None)
    raise LookupError(path)


def test_persona_export_endpoint_only_accepts_current_parameters(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())

    operation = app.openapi()["paths"]["/pallas/api/common-config/llm/persona/export"]["get"]
    names = {item["name"] for item in operation["parameters"]}

    assert names == {"bot_id", "group_id", "plain_text", "mode", "token", "X-Pallas-Token", "X-Pallas-Api-Key"}


@pytest.mark.asyncio
async def test_persona_export_endpoint_forwards_current_parameters(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    calls = []

    async def build_bundle(bot_id, group_id, plain_text, *, mode):
        calls.append((bot_id, group_id, plain_text, mode))
        return SimpleNamespace(model_dump=lambda **_: {"purpose": "chat"})

    monkeypatch.setattr(
        "pallas.product.persona.bundle_export.build_persona_asset_bundle_v1",
        build_bundle,
    )
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    endpoint = _find_console_route_endpoint(app, "/pallas/api/common-config/llm/persona/export")
    response = await endpoint(bot_id=10, group_id=20, plain_text="test", mode="normal")

    assert response.status_code == 200
    assert b'"purpose":"chat"' in response.body
    assert calls == [(10, 20, "test", "normal")]


@pytest.mark.asyncio
async def test_persona_export_endpoint_serializes_datetime_with_mode_json(monkeypatch) -> None:
    """Regression: nested datetime (e.g. raw persona dicts) must not 500 on JSONResponse."""
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)

    async def build_bundle(bot_id, group_id, plain_text, *, mode):
        return PersonaAssetBundleV1(
            exported_at=1,
            bot_id=bot_id,
            group_id=group_id,
            purpose="chat",
            plain_text=plain_text,
            prompt_bundle=PersonaPromptBundle(
                system="推导时间 {updated_at}",
                metadata=PersonaPromptMetadata(
                    bot_id=bot_id,
                    group_id=group_id,
                    persona={"updated_at": datetime.datetime(2026, 8, 21, 17, 54, 59)},
                ),
                sections=PersonaPromptSections(base="基础", bot_behavior="行为"),
            ),
        )

    monkeypatch.setattr(
        "pallas.product.persona.bundle_export.build_persona_asset_bundle_v1",
        build_bundle,
    )
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    endpoint = _find_console_route_endpoint(app, "/pallas/api/common-config/llm/persona/export")
    response = await endpoint(bot_id=10, group_id=20, plain_text="test", mode="normal")

    assert response.status_code == 200
    assert b"2026-08-21T17:54:59" in response.body


@pytest.mark.asyncio
async def test_prompt_preview_endpoint_forwards_scope_and_message(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    calls = []

    async def build_preview(**kwargs):
        calls.append(kwargs)
        return {
            "preview_mode": True,
            "decision_source": "preview_default",
            "sections": [],
            "system_prompt": "preview",
        }

    monkeypatch.setattr("pallas.product.llm.prompt_preview.build_prompt_preview", build_preview)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    endpoint = _find_console_route_endpoint(app, "/pallas/api/common-config/llm/persona/prompt-preview")
    response = await endpoint(
        body=llm_ops_api._PromptPreviewBody(bot_id=10, group_id=20, user_id=30, query_text="你好"),
    )

    assert response.status_code == 200
    assert b'"system_prompt":"preview"' in response.body
    assert calls == [{"bot_id": 10, "group_id": 20, "user_id": 30, "query_text": "你好"}]


@pytest.mark.asyncio
async def test_prompt_overrides_endpoints_roundtrip_current_scope(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    saved = []
    stored = {
        "persona": {"mode": "replace", "content": "新的 persona"},
    }

    monkeypatch.setattr(
        "pallas.product.llm.assembler.prompt_overrides.load_prompt_overrides",
        lambda *, bot_id, group_id: stored if (bot_id, group_id) == (10, 20) else {},
    )

    def save_overrides(*, bot_id, group_id, sections):
        saved.append((bot_id, group_id, sections))
        return sections

    monkeypatch.setattr(
        "pallas.product.llm.assembler.prompt_overrides.save_prompt_overrides",
        save_overrides,
    )
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    get_endpoint = _find_console_route_endpoint(
        app, "/pallas/api/common-config/llm/persona/prompt-overrides", "GET"
    )
    put_endpoint = _find_console_route_endpoint(
        app, "/pallas/api/common-config/llm/persona/prompt-overrides", "PUT"
    )
    response = await get_endpoint(bot_id=10, group_id=20)
    assert response.status_code == 200
    assert json.loads(response.body)["data"]["persona"]["content"] == "新的 persona"

    body = llm_ops_api._PromptOverridesBody(
        bot_id=10,
        group_id=20,
        sections={
            "persona": {"mode": "replace", "content": "新的 persona"},
            "identity": {"mode": "append", "content": "补充身份"},
            "turn_policy": {"mode": "disable", "content": ""},
        },
    )
    response = await put_endpoint(body=body)
    assert response.status_code == 200
    assert saved == [(10, 20, body.sections)]


def test_prompt_overrides_body_rejects_invalid_scope_and_content() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        llm_ops_api._PromptOverridesBody(
            bot_id=0,
            group_id=20,
            sections={},
        )

    with pytest.raises(ValueError, match="at most 12000 characters"):
        llm_ops_api._PromptOverridesBody(
            bot_id=10,
            group_id=20,
            sections={"persona": {"mode": "replace", "content": "x" * 12001}},
        )


@pytest.mark.asyncio
async def test_prompt_preview_try_calls_provider_directly_and_requires_write_token(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr("packages.pb_webui.extended_common.check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    token_calls = []
    provider_calls = []
    plugin_config = Config()

    def check_write_token(*args, **kwargs):
        token_calls.append((args, kwargs))

    monkeypatch.setattr("packages.pb_webui.extended_common.check_pallas_write_token", check_write_token)

    async def complete_chat_message(**kwargs):
        provider_calls.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "试答结果"}}]}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", complete_chat_message)
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: SimpleNamespace(llm_model="preview-model"))
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=plugin_config)
    endpoint = _find_console_route_endpoint(
        app,
        "/pallas/api/common-config/llm/persona/prompt-preview/try",
        "POST",
    )

    response = await endpoint(
        body=llm_ops_api._PromptTrialBody(
            bot_id=10,
            group_id=20,
            user_id=30,
            system_prompt="系统提示",
            query_text="用户问题",
        ),
        token="write-token",
        x_pallas_token=None,
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload == {
        "ok": True,
        "data": {
            "text": "试答结果",
            "model": "preview-model",
            "elapsed_ms": payload["data"]["elapsed_ms"],
            "test_call": True,
        },
    }
    assert token_calls == [((plugin_config,), {"x_pallas_token": None, "token": "write-token"})]
    assert provider_calls[0]["messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户问题"},
    ]
    assert provider_calls[0]["model"] == "preview-model"
    assert provider_calls[0]["options"] == {"temperature": 0.2, "max_tokens": 512}
    assert provider_calls[0]["tools"] is None
    assert provider_calls[0]["task"] == "llm_prompt_preview"


def test_prompt_trial_body_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        llm_ops_api._PromptTrialBody(
            bot_id=1,
            group_id=0,
            user_id=0,
            system_prompt="system",
            query_text="query",
        )
    with pytest.raises(ValueError, match="at least 1 character"):
        llm_ops_api._PromptTrialBody(
            bot_id=1,
            group_id=1,
            user_id=0,
            system_prompt="",
            query_text="query",
        )
    with pytest.raises(ValueError, match="at least 1 character"):
        llm_ops_api._PromptTrialBody(
            bot_id=1,
            group_id=1,
            user_id=0,
            system_prompt="system",
            query_text="",
        )
