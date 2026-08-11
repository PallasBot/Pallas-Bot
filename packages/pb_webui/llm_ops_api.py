"""LLM 会话 / 记忆 / Persona 运维控制台 API。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from packages.pb_webui.console_openapi_models import _ApiOkResponse
from pallas.product.persona.group_expression_profile import GroupExpressionProfile

if TYPE_CHECKING:
    from packages.pb_webui.config import Config


class _StickerLabelStatsData(BaseModel):
    total: int = 0
    sticker: int = 0
    not_sticker: int = 0
    current_version: int = 0
    low_confidence: int = 0


class _StickerLabelJobErrorData(BaseModel):
    job_id: str = ""
    created_at: float = 0
    state: str = ""
    error: str = ""


class _StickerLabelJobStatsData(BaseModel):
    pending: int = 0
    failed: int = 0
    recent_errors: list[_StickerLabelJobErrorData] = Field(default_factory=list)


class _StickerLabelOverviewData(BaseModel):
    labels: _StickerLabelStatsData
    jobs: _StickerLabelJobStatsData
    lazy_labels_paused: bool = False
    label_circuit_open: bool = False
    vlm_refine_avoided: int = 0
    vlm_refine_actual: int = 0
    send_hits: int = 0


class _StickerLabelRequeueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["requeue"]


class _StickerLabelPauseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["pause"]
    paused: bool


class _StickerLabelClearBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["clear"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


StickerLabelMaintenanceBody = Annotated[
    _StickerLabelRequeueBody | _StickerLabelPauseBody | _StickerLabelClearBody,
    Field(discriminator="action"),
]


class _StickerLabelRequeueResult(BaseModel):
    requeued: int = 0
    queued: int = 0
    skipped: int = 0
    missing_cache: int = 0


class _StickerLabelPauseResult(BaseModel):
    lazy_labels_paused: bool


class _StickerLabelClearResult(BaseModel):
    cleared: bool


StickerLabelMaintenanceResult = _StickerLabelRequeueResult | _StickerLabelPauseResult | _StickerLabelClearResult


def register_llm_ops_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    check_write_token,
) -> None:
    @router.get(f"{x}/common-config/llm/history/stats", include_in_schema=True)
    async def _llm_history_stats_get(
        bot_id: int | None = Query(default=None, ge=1),
        group_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import build_llm_history_stats

        try:
            data = await build_llm_history_stats(bot_id=bot_id, group_id=group_id, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/common-config/llm/history/session/clear", include_in_schema=True)
    async def _llm_history_session_clear(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import clear_llm_history_session

        bot_id = int(body.get("bot_id") or 0)
        if bot_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id required")
        group_id = body.get("group_id")
        user_id = body.get("user_id")
        try:
            data = await clear_llm_history_session(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else None,
                user_id=int(user_id) if user_id is not None else None,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/common-config/llm/history/session/inject", include_in_schema=True)
    async def _llm_history_session_inject(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import inject_llm_history_message

        bot_id = int(body.get("bot_id") or 0)
        user_id = int(body.get("user_id") or 0)
        content = str(body.get("content") or "").strip()
        role = str(body.get("role") or "user").strip().lower()
        if bot_id <= 0 or user_id <= 0 or not content:
            raise HTTPException(status_code=400, detail="bot_id, user_id, content required")
        if role not in {"user", "assistant"}:
            raise HTTPException(status_code=400, detail="role must be user or assistant")
        try:
            data = await inject_llm_history_message(
                bot_id=bot_id,
                group_id=int(body["group_id"]) if body.get("group_id") is not None else None,
                user_id=user_id,
                content=content,
                role=role,  # type: ignore[arg-type]
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not data.get("ok"):
            raise HTTPException(status_code=400, detail="session inject rejected or unavailable")
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/common-config/llm/history/session/compact", include_in_schema=True)
    async def _llm_history_session_compact(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import compact_llm_history_session

        bot_id = int(body.get("bot_id") or 0)
        user_id = int(body.get("user_id") or 0)
        summary = str(body.get("summary") or "").strip()
        if bot_id <= 0 or user_id <= 0 or not summary:
            raise HTTPException(status_code=400, detail="bot_id, user_id, summary required")
        keep = body.get("keep_messages")
        try:
            data = await compact_llm_history_session(
                bot_id=bot_id,
                group_id=int(body["group_id"]) if body.get("group_id") is not None else None,
                user_id=user_id,
                summary=summary,
                keep_messages=int(keep) if keep is not None else None,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not data.get("ok"):
            raise HTTPException(status_code=400, detail="compact rejected or unavailable")
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/common-config/llm/session", include_in_schema=True)
    async def _llm_session_ops_config_get() -> JSONResponse:
        from pallas.product.llm.ops_api import get_llm_session_ops_config

        return JSONResponse({"ok": True, "data": get_llm_session_ops_config().model_dump()})

    @router.put(f"{x}/common-config/llm/session", include_in_schema=True)
    async def _llm_session_ops_config_put(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.env_sections import apply_webui_env_section_patch
        from pallas.product.llm.ops_api import get_llm_session_ops_config, session_ops_patch_dict

        try:
            patch = session_ops_patch_dict(dict(body or {}))
            apply_webui_env_section_patch("llm", patch)
            data = get_llm_session_ops_config().model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/common-config/llm/memory", include_in_schema=True)
    async def _llm_memory_ops_config_get() -> JSONResponse:
        from pallas.product.llm.ops_api import get_llm_memory_ops_config

        return JSONResponse({"ok": True, "data": get_llm_memory_ops_config().model_dump()})

    @router.put(f"{x}/common-config/llm/memory", include_in_schema=True)
    async def _llm_memory_ops_config_put(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.env_sections import apply_webui_env_section_patch
        from pallas.product.llm.ops_api import get_llm_memory_ops_config, memory_ops_patch_dict

        try:
            patch = memory_ops_patch_dict(dict(body or {}))
            apply_webui_env_section_patch("llm", patch)
            data = get_llm_memory_ops_config().model_dump()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/llm/conversation-kernel/memory/stats", include_in_schema=True)
    async def _llm_memory_stats_get(
        bot_id: int | None = Query(default=None, ge=1),
        group_id: int | None = Query(default=None, ge=0),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import build_memory_stats

        try:
            data = await build_memory_stats(bot_id=bot_id, group_id=group_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/conversation-kernel/memory/retrieve", include_in_schema=True)
    async def _llm_memory_retrieve_post(body: dict[str, Any]) -> JSONResponse:
        from pallas.product.llm.ops_api import preview_memory_retrieve

        bot_id = int(body.get("bot_id") or 0)
        query = str(body.get("query") or "").strip()
        if bot_id <= 0 or not query:
            raise HTTPException(status_code=400, detail="bot_id and query required")
        try:
            data = await preview_memory_retrieve(
                bot_id,
                int(body["group_id"]) if body.get("group_id") is not None else None,
                query,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/conversation-kernel/memory/clear", include_in_schema=True)
    async def _llm_memory_clear_post(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import clear_memory_entries

        bot_id = int(body.get("bot_id") or 0)
        if bot_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id required")
        try:
            data = await clear_memory_entries(
                bot_id=bot_id,
                group_id=int(body["group_id"]) if body.get("group_id") is not None else None,
                dry_run=bool(body.get("dry_run")),
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/conversation-kernel/memory/lifecycle", include_in_schema=True)
    async def _llm_memory_lifecycle_post(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import apply_memory_lifecycle

        entry_id = int(body.get("id") or 0)
        action = str(body.get("action") or "").strip().lower()
        if entry_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        if action not in {"reinforce", "weaken", "freeze", "unfreeze", "forget"}:
            raise HTTPException(status_code=400, detail="invalid action")
        tags = body.get("entity_tags")
        try:
            data = apply_memory_lifecycle(
                entry_id,
                action=action,  # type: ignore[arg-type]
                entity_tags=[str(t) for t in tags] if isinstance(tags, list) else None,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/llm/conversation-kernel/memory/preferences", include_in_schema=True)
    async def _llm_memory_preferences_get(
        bot_id: int | None = Query(default=None, ge=1),
        group_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_memory_preferences

        items = list_memory_preferences(bot_id=bot_id, group_id=group_id, limit=limit)
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.post(f"{x}/llm/conversation-kernel/memory/preferences", include_in_schema=True)
    async def _llm_memory_preferences_upsert(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import upsert_memory_preference

        bot_id = int(body.get("bot_id") or 0)
        rule = str(body.get("rule") or "").strip()
        if bot_id <= 0 or not rule:
            raise HTTPException(status_code=400, detail="bot_id and rule required")
        try:
            data = upsert_memory_preference(
                bot_id=bot_id,
                group_id=int(body["group_id"]) if body.get("group_id") is not None else None,
                rule=rule,
                polarity=str(body.get("polarity") or "do"),
                context=str(body.get("context") or ""),
                pref_id=str(body.get("id") or "").strip() or None,
                is_active=bool(body.get("is_active", True)),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/conversation-kernel/memory/preferences/delete", include_in_schema=True)
    async def _llm_memory_preferences_delete(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import delete_memory_preference

        pref_id = str(body.get("id") or "").strip()
        if not pref_id:
            raise HTTPException(status_code=400, detail="id required")
        ok = delete_memory_preference(pref_id)
        if not ok:
            raise HTTPException(status_code=404, detail="preference not found")
        return JSONResponse({"ok": True, "data": {"id": pref_id}})

    @router.get(f"{x}/llm/conversation-kernel/memory/entities", include_in_schema=True)
    async def _llm_memory_entities_get(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_memory_entity_summaries_async

        try:
            items = await list_memory_entity_summaries_async(bot_id=bot_id, group_id=group_id, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.get(f"{x}/llm/conversation-kernel/mid-term", include_in_schema=True)
    async def _llm_mid_term_get(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        user_id: int | None = Query(default=None, ge=1),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_mid_term_summaries

        try:
            items = await list_mid_term_summaries(
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
                limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.get(f"{x}/common-config/llm/persona/scene-dialogue-examples", include_in_schema=True)
    async def _llm_scene_dialogue_examples_get(
        bot_id: int = Query(..., ge=1),
    ) -> JSONResponse:
        from pallas.product.persona.scene_dialogue_examples import list_scene_dialogue_examples

        items = [item.model_dump(mode="json") for item in list_scene_dialogue_examples(bot_id)]
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.post(f"{x}/common-config/llm/persona/scene-dialogue-examples", include_in_schema=True)
    async def _llm_scene_dialogue_examples_create(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.persona.scene_dialogue_examples import create_scene_dialogue_example

        try:
            item = create_scene_dialogue_example(
                bot_id=int(body.get("bot_id") or 0),
                scene=str(body.get("scene") or ""),
                user_cue=str(body.get("user_cue") or ""),
                positive=str(body.get("positive") or ""),
                negative=str(body.get("negative") or ""),
                enabled=bool(body.get("enabled", True)),
                order=int(body.get("order") or 0),
            )
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": item.model_dump(mode="json")})

    @router.put(f"{x}/common-config/llm/persona/scene-dialogue-examples/{{example_id}}", include_in_schema=True)
    async def _llm_scene_dialogue_examples_update(
        example_id: str,
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.persona.scene_dialogue_examples import update_scene_dialogue_example

        try:
            item = update_scene_dialogue_example(example_id, **body)
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if item is None:
            raise HTTPException(status_code=404, detail="scene dialogue example not found")
        return JSONResponse({"ok": True, "data": item.model_dump(mode="json")})

    @router.delete(f"{x}/common-config/llm/persona/scene-dialogue-examples/{{example_id}}", include_in_schema=True)
    async def _llm_scene_dialogue_examples_delete(
        example_id: str,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.persona.scene_dialogue_examples import delete_scene_dialogue_example

        if not delete_scene_dialogue_example(example_id):
            raise HTTPException(status_code=404, detail="scene dialogue example not found")
        return JSONResponse({"ok": True, "data": {"id": example_id}})

    @router.get(f"{x}/common-config/llm/persona/export", include_in_schema=True)
    async def _llm_persona_export_get(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        plain_text: str = Query(default="", description="编译用人设原文；可空"),
        mode: str = Query(default="normal"),
    ) -> JSONResponse:
        from pallas.product.persona.bundle_export import build_persona_asset_bundle_v1

        try:
            data = await build_persona_asset_bundle_v1(
                bot_id,
                group_id,
                plain_text,
                mode=mode,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data.model_dump()})

    @router.get(
        f"{x}/common-config/llm/persona/group-style",
        include_in_schema=True,
        response_model=_ApiOkResponse[GroupExpressionProfile],
    )
    async def _llm_persona_group_style_get(
        bot_id: int | None = Query(
            default=None,
            ge=1,
            description="Bot QQ；提供后合并对应 bot/group/scene 的 semantic snapshot",
        ),
        group_id: int = Query(..., ge=1),
        scene: str = Query(default="group_chat", min_length=1, max_length=64),
    ) -> dict[str, Any]:
        from pallas.core.foundation.db import make_group_config_repository
        from pallas.product.llm import repeater_semantic_style
        from pallas.product.persona.group_expression_profile import resolve_group_expression_profile

        try:
            config = await make_group_config_repository().get(group_id)
            style_profile = getattr(config, "style_profile", None) if config is not None else None
            semantic_profile = None
            if bot_id is not None:
                repeater_semantic_style.refresh_semantic_style_cache()
                semantic_profile = repeater_semantic_style.cached_semantic_style_profile(
                    bot_id,
                    group_id,
                    scene,
                )
            profile = resolve_group_expression_profile(
                style_profile if isinstance(style_profile, dict) else None,
                semantic_profile,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": profile.model_dump(mode="json")}

    @router.get(
        f"{x}/common-config/llm/persona/sticker-labels",
        include_in_schema=True,
        response_model=_ApiOkResponse[_StickerLabelOverviewData],
    )
    async def _sticker_label_overview_get() -> JSONResponse:
        from pallas.product.llm.sticker_label_observability import build_sticker_label_overview

        try:
            data = await build_sticker_label_overview()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(
        f"{x}/common-config/llm/persona/sticker-labels/manage",
        include_in_schema=True,
        response_model=_ApiOkResponse[StickerLabelMaintenanceResult],
    )
    async def _sticker_label_maintenance_post(
        body: StickerLabelMaintenanceBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm import sticker_label_observability

        action = body.action
        if action == "requeue":
            return JSONResponse({"ok": True, "data": await sticker_label_observability.requeue_stale_sticker_labels()})
        if action == "pause":
            paused = sticker_label_observability.set_lazy_sticker_labels_paused(body.paused)
            return JSONResponse({"ok": True, "data": {"lazy_labels_paused": paused}})
        if action == "clear":
            cleared = await sticker_label_observability.clear_sticker_label(body.content_hash)
            return JSONResponse({"ok": True, "data": {"cleared": cleared}})
        raise HTTPException(status_code=400, detail="action must be requeue, pause, or clear")
