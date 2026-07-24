"""LLM 会话 / 记忆 / Persona 运维控制台 API。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from packages.pb_webui.config import Config


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
        from pallas.product.llm.session_ops import build_llm_history_stats

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
        from pallas.product.llm.session_ops import clear_llm_history_session

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
        from pallas.product.llm.session_ops import inject_llm_history_message

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
        from pallas.product.llm.session_ops import compact_llm_history_session

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
        from pallas.product.llm.ops_config import get_llm_session_ops_config

        return JSONResponse({"ok": True, "data": get_llm_session_ops_config().model_dump()})

    @router.put(f"{x}/common-config/llm/session", include_in_schema=True)
    async def _llm_session_ops_config_put(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.env_sections import apply_webui_env_section_patch
        from pallas.product.llm.ops_config import get_llm_session_ops_config, session_ops_patch_dict

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
        from pallas.product.llm.ops_config import get_llm_memory_ops_config

        return JSONResponse({"ok": True, "data": get_llm_memory_ops_config().model_dump()})

    @router.put(f"{x}/common-config/llm/memory", include_in_schema=True)
    async def _llm_memory_ops_config_put(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.env_sections import apply_webui_env_section_patch
        from pallas.product.llm.ops_config import get_llm_memory_ops_config, memory_ops_patch_dict

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
        from pallas.product.llm.memory.ops import build_memory_stats

        try:
            data = await build_memory_stats(bot_id=bot_id, group_id=group_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/conversation-kernel/memory/retrieve", include_in_schema=True)
    async def _llm_memory_retrieve_post(body: dict[str, Any]) -> JSONResponse:
        from pallas.product.llm.memory.ops import preview_memory_retrieve

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
        from pallas.product.llm.memory.ops import clear_memory_entries

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
        from pallas.product.llm.memory.ops import apply_memory_lifecycle

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
        from pallas.product.llm.memory.ops import list_memory_preferences

        items = list_memory_preferences(bot_id=bot_id, group_id=group_id, limit=limit)
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.post(f"{x}/llm/conversation-kernel/memory/preferences", include_in_schema=True)
    async def _llm_memory_preferences_upsert(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.memory.ops import upsert_memory_preference

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
        from pallas.product.llm.memory.ops import delete_memory_preference

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
        from pallas.product.llm.memory.ops import list_memory_entity_summaries_async

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
        from pallas.product.llm.memory.mid_term import list_mid_term_summaries

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

    @router.get(f"{x}/common-config/llm/persona/export", include_in_schema=True)
    async def _llm_persona_export_get(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        plain_text: str = Query(default="", description="编译用人设原文；可空"),
        purpose: str = Query(default="chat"),
        mode: str = Query(default="normal"),
        include_repeater_overlay: bool = Query(default=False),
    ) -> JSONResponse:
        from pallas.product.persona.bundle_export import build_persona_asset_bundle_v1

        try:
            data = await build_persona_asset_bundle_v1(
                bot_id,
                group_id,
                plain_text,
                purpose=purpose,
                mode=mode,
                include_repeater_overlay=include_repeater_overlay,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data.model_dump()})

    @router.get(f"{x}/common-config/llm/persona/group-style", include_in_schema=True)
    async def _llm_persona_group_style_get(
        group_id: int = Query(..., ge=1),
        window_hours: int = Query(default=168, ge=1, le=720),
    ) -> JSONResponse:
        from pallas.core.foundation.db import make_context_repository, make_message_repository
        from pallas.product.persona.group_profiler import build_group_style_profile_from_recent_repos

        try:
            data = await build_group_style_profile_from_recent_repos(
                group_id=group_id,
                message_repo=make_message_repository(),
                context_repo=make_context_repository(),
                window_hours=window_hours,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})
