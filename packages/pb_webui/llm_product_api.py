"""Pallas-Bot WebUI console API: LLM product routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from pallas.product.llm.ops_api import (
    build_conversation_kernel_status,
    clear_feedback_entry_correction,
    delete_feedback_entry,
    delete_memory_entry,
    delete_relationship_note,
    group_feedback_bias_snapshot,
    list_active_knowledge_sources,
    list_group_feedback_entries,
    list_memory_entries,
    list_promotion_candidates,
    list_recent_conversation_traces,
    list_relationship_notes,
    resolve_promotion_candidate_with_writeback,
    set_feedback_entry_correction,
    set_feedback_entry_eligibility,
)
from pallas.product.persona.expression_bank import ExpressionStatus, list_group_expressions
from pallas.product.persona.expression_promote import resolve_expression

from .extended_common import check_pallas_write_token

if TYPE_CHECKING:
    from .config import Config


def _llm_ext():
    from packages.pb_webui import extended_api

    return extended_api


def _semantic_style():
    from pallas.product.llm import repeater_semantic_style

    return repeater_semantic_style


def register_llm_product_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/llm/repeater-semantic-style", include_in_schema=True)
    async def _repeater_semantic_style_get(
        bot_id: int | None = Query(default=None, ge=1),
        group_id: int | None = Query(default=None, ge=1),
    ) -> JSONResponse:
        if (bot_id is None) != (group_id is None):
            raise HTTPException(status_code=422, detail="bot_id 和 group_id 必须同时提供")
        try:
            data = (
                _semantic_style().semantic_style_status(bot_id=bot_id, group_id=group_id)
                if bot_id
                else _semantic_style().semantic_style_status()
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/repeater-semantic-style/manage", include_in_schema=True)
    async def _repeater_semantic_style_manage(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        action = str(body.get("action") or "").strip().lower()
        allowed_actions = {"status", "overrides", "clear", "rebuild", "quality", "recover", "disable"}
        if action not in allowed_actions:
            raise HTTPException(status_code=400, detail="action 无效")
        bot_id = body.get("bot_id")
        group_id = body.get("group_id")
        if (bot_id is None) != (group_id is None):
            raise HTTPException(status_code=422, detail="bot_id 和 group_id 必须同时提供")
        try:
            scope = {"bot_id": int(bot_id), "group_id": int(group_id)} if bot_id is not None else {}
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail="bot_id 和 group_id 必须为整数") from e
        if scope and (scope["bot_id"] <= 0 or scope["group_id"] <= 0):
            raise HTTPException(status_code=422, detail="bot_id 和 group_id 必须为正整数")
        try:
            semantic_style = _semantic_style()
            if action == "status":
                data = (
                    semantic_style.semantic_style_status(**scope) if scope else semantic_style.semantic_style_status()
                )
            elif action == "overrides":
                overrides = body.get("overrides")
                if not isinstance(overrides, dict):
                    raise HTTPException(status_code=400, detail="overrides 必须为对象")
                data = (
                    semantic_style.update_semantic_style_overrides(overrides, **scope)
                    if scope
                    else semantic_style.update_semantic_style_overrides(overrides)
                )
            elif action == "clear":
                data = (
                    semantic_style.clear_semantic_style_data(**scope)
                    if scope
                    else semantic_style.clear_semantic_style_data()
                )
            elif action == "rebuild":
                data = (
                    semantic_style.rebuild_semantic_style_profiles(**scope)
                    if scope
                    else semantic_style.rebuild_semantic_style_profiles()
                )
            elif action == "quality":
                data = (
                    semantic_style.semantic_style_quality(**scope) if scope else semantic_style.semantic_style_quality()
                )
            elif action == "recover":
                data = (
                    semantic_style.recover_semantic_style_data(**scope)
                    if scope
                    else semantic_style.recover_semantic_style_data()
                )
            else:
                data = (
                    semantic_style.set_semantic_style_enabled(False, **scope)
                    if scope
                    else semantic_style.set_semantic_style_enabled(False)
                )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/llm/repeater-feedback", include_in_schema=True)
    async def _llm_repeater_feedback_get(
        group_id: int = Query(..., ge=1, description="群号"),
        limit: int = Query(default=20, ge=1, le=200),
    ) -> JSONResponse:
        try:
            rows = list_group_feedback_entries(group_id=group_id, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({
            "ok": True,
            "data": {
                "items": [row.model_dump(mode="json") if hasattr(row, "model_dump") else row for row in rows],
                "limit": limit,
            },
        })

    @router.get(f"{x}/llm/repeater-feedback/summary", include_in_schema=True)
    async def _llm_repeater_feedback_summary_get(
        group_id: int = Query(..., ge=1, description="群号"),
        limit: int = Query(default=40, ge=1, le=200),
    ) -> JSONResponse:
        try:
            data = group_feedback_bias_snapshot(group_id=group_id, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/repeater-feedback/manage", include_in_schema=True)
    async def _llm_repeater_feedback_manage(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        entry_id = str(body.get("entry_id") or "").strip()
        request_id = str(body.get("request_id") or "").strip()
        action = str(body.get("action") or "").strip().lower()
        if not entry_id and not request_id:
            raise HTTPException(status_code=400, detail="entry_id 或 request_id 至少填一项")
        allowed_actions = {"invalidate", "restore", "delete", "correct", "clear_correction"}
        if action not in allowed_actions:
            raise HTTPException(
                status_code=400,
                detail="action 必须为 invalidate / restore / delete / correct / clear_correction",
            )
        try:
            if action == "delete":
                ok = delete_feedback_entry(entry_id=entry_id, request_id=request_id)
                if not ok:
                    raise HTTPException(status_code=404, detail="未找到该反哺记录")
                return JSONResponse({"ok": True, "data": {"deleted": True, "entry_id": entry_id or request_id}})
            if action == "correct":
                corrected_reply_text = str(body.get("corrected_reply_text") or "").strip()
                if not corrected_reply_text:
                    raise HTTPException(status_code=400, detail="corrected_reply_text 必填")
                create_fields: dict[str, Any] | None = None
                if _llm_ext().find_feedback_entry(entry_id=entry_id, request_id=request_id) is None:
                    bot_id = body.get("bot_id")
                    group_id = body.get("group_id")
                    user_id = body.get("user_id")
                    if bot_id is None or group_id is None or user_id is None:
                        raise HTTPException(
                            status_code=400,
                            detail="未找到反哺记录时需提供 bot_id / group_id / user_id",
                        )
                    create_fields = {
                        "bot_id": int(bot_id),
                        "group_id": int(group_id),
                        "user_id": int(user_id),
                        "user_text": str(body.get("user_text") or "").strip(),
                        "reply_text": str(body.get("reply_text") or "").strip(),
                        "llm_route": str(body.get("llm_route") or "").strip(),
                        "behavior_scene": str(body.get("behavior_scene") or "").strip(),
                        "request_id": request_id,
                    }
                updated = set_feedback_entry_correction(
                    entry_id=entry_id,
                    request_id=request_id,
                    corrected_reply_text=corrected_reply_text,
                    create_fields=create_fields,
                )
            elif action == "clear_correction":
                updated = clear_feedback_entry_correction(entry_id=entry_id, request_id=request_id)
            else:
                updated = set_feedback_entry_eligibility(
                    entry_id=entry_id,
                    request_id=request_id,
                    eligible_for_bias=action == "restore",
                )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if updated is None:
            raise HTTPException(status_code=404, detail="未找到该反哺记录")
        return JSONResponse({"ok": True, "data": updated.model_dump(mode="json")})

    @router.get(f"{x}/llm/repeater-feedback/promotion-candidates", include_in_schema=True)
    async def _llm_repeater_feedback_promotion_candidates_get(
        group_id: int = Query(..., ge=1, description="群号"),
        limit: int = Query(default=20, ge=1, le=200),
        include_resolved: bool = Query(default=False, description="是否包含已晋升/已拒绝"),
    ) -> JSONResponse:
        try:
            rows = list_promotion_candidates(
                group_id=group_id,
                limit=limit,
                include_resolved=include_resolved,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({
            "ok": True,
            "data": {
                "items": [row.model_dump(mode="json") for row in rows],
                "limit": limit,
            },
        })

    @router.post(f"{x}/llm/repeater-feedback/promotion-candidates/resolve", include_in_schema=True)
    async def _llm_repeater_feedback_promotion_candidates_resolve(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        candidate_id = str(body.get("candidate_id") or "").strip()
        action = str(body.get("action") or "").strip().lower()
        if not candidate_id:
            raise HTTPException(status_code=400, detail="candidate_id required")
        if action not in {"promote", "reject"}:
            raise HTTPException(status_code=400, detail="action must be promote or reject")
        try:
            updated = await resolve_promotion_candidate_with_writeback(
                candidate_id,
                action=action,  # type: ignore[arg-type]
                reason=str(body.get("reason") or "").strip(),
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if updated is None:
            raise HTTPException(status_code=404, detail="未找到候选或 writeback 未开启")
        return JSONResponse({"ok": True, "data": updated.model_dump(mode="json")})

    @router.get(f"{x}/llm/expression-bank", include_in_schema=True)
    async def _llm_expression_bank_get(
        group_id: int = Query(..., ge=1, description="群号"),
        status: Annotated[ExpressionStatus | None, Query(description="状态筛选")] = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        try:
            rows = list_group_expressions(group_id=group_id, status=status, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({
            "ok": True,
            "data": {
                "items": [row.model_dump(mode="json") for row in rows],
                "limit": limit,
            },
        })

    @router.post(f"{x}/llm/expression-bank/resolve", include_in_schema=True)
    async def _llm_expression_bank_resolve(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        entry_id = str(body.get("entry_id") or "").strip()
        action = str(body.get("action") or "").strip().lower()
        if not entry_id:
            raise HTTPException(status_code=400, detail="entry_id required")
        if action not in {"approve", "reject"}:
            raise HTTPException(status_code=400, detail="action must be approve or reject")
        try:
            updated = resolve_expression(
                entry_id,
                action=action,  # type: ignore[arg-type]
                reason=str(body.get("reason") or "").strip(),
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if updated is None:
            raise HTTPException(status_code=404, detail="未找到表达记录")
        return JSONResponse({"ok": True, "data": updated.model_dump(mode="json")})

    @router.get(f"{x}/llm/conversation-kernel/status", include_in_schema=True)
    async def _llm_conversation_kernel_status_get() -> JSONResponse:
        try:
            data = build_conversation_kernel_status()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/llm/conversation-kernel/traces", include_in_schema=True)
    async def _llm_conversation_kernel_traces_get(
        group_id: int | None = Query(default=None, ge=1, description="群号"),
        bot_id: int | None = Query(default=None, ge=1, description="Bot QQ"),
        kind: str | None = Query(
            default="decision",
            description="trace kind；decision=conversation_decision_trace",
        ),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        try:
            items = list_recent_conversation_traces(
                group_id=group_id,
                bot_id=bot_id,
                kind=kind,
                limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "limit": limit}})

    @router.get(f"{x}/llm/conversation-kernel/memory", include_in_schema=True)
    async def _llm_conversation_kernel_memory_get(
        bot_id: int = Query(..., ge=1, description="Bot QQ"),
        group_id: int | None = Query(default=None, ge=1, description="群号"),
        query: str | None = Query(default=None, description="内容/关键词搜索"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        try:
            items = await list_memory_entries(
                int(bot_id),
                group_id,
                query=str(query or "").strip(),
                limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items), "limit": limit}})

    @router.post(f"{x}/llm/conversation-kernel/memory", include_in_schema=True)
    async def _llm_conversation_kernel_memory_create(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        bot_id = int(body.get("bot_id") or 0)
        group_id = body.get("group_id")
        content = str(body.get("content") or "").strip()
        if bot_id <= 0 or not content:
            raise HTTPException(status_code=400, detail="bot_id and content required")
        gid = int(group_id) if group_id is not None else None
        try:
            from pallas.product.llm.ops_api import save_memory_entry

            ok = await save_memory_entry(bot_id, gid, content, source="teach")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=400, detail="memory save rejected or unavailable")
        return JSONResponse({"ok": True, "data": {"bot_id": bot_id, "group_id": gid}})

    @router.get(f"{x}/llm/knowledge/sources", include_in_schema=True)
    async def _llm_knowledge_sources_list() -> JSONResponse:
        try:
            from pallas.product.llm.ops_api import list_active_knowledge_sources

            rows = list_active_knowledge_sources()
            items = [
                {
                    "source_id": row.source_id,
                    "title": row.decl.title,
                    "origin": str(row.origin),
                    "plugin_name": row.plugin_name,
                    "chunk_count": len(row.decl.chunks or []),
                }
                for row in rows
            ]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.get(f"{x}/llm/tools", include_in_schema=True)
    async def _llm_tools_list() -> JSONResponse:
        try:
            from pallas.product.llm.ops_api import build_tools_catalog_ui

            data = build_tools_catalog_ui()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/tools/preview", include_in_schema=True)
    async def _llm_tools_preview(body: dict[str, Any]) -> JSONResponse:
        try:
            from pallas.product.llm.ops_api import preview_tool_intent

            text = str(body.get("text") or body.get("user_text") or "").strip()
            task = str(body.get("task") or "llm_chat").strip() or "llm_chat"
            data = preview_tool_intent(text, task=task)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/llm/tools/overrides", include_in_schema=True)
    async def _llm_tools_overrides_put(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            from pallas.product.llm.ops_api import build_tools_catalog_ui, save_tool_overrides

            raw = body.get("overrides") if isinstance(body.get("overrides"), dict) else body
            if not isinstance(raw, dict):
                raise HTTPException(status_code=400, detail="overrides must be an object")
            saved = save_tool_overrides(raw)
            data = build_tools_catalog_ui()
            data["overrides"] = saved
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.patch(f"{x}/llm/tools/overrides/{{tool_name}}", include_in_schema=True)
    async def _llm_tools_override_patch(
        tool_name: str,
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            from pallas.product.llm.ops_api import build_tools_catalog_ui, upsert_tool_override

            entry = upsert_tool_override(tool_name, body if isinstance(body, dict) else {})
            data = build_tools_catalog_ui()
            data["patched"] = {"name": tool_name, "override": entry}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/conversation-kernel/memory/delete", include_in_schema=True)
    async def _llm_conversation_kernel_memory_delete(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        entry_id = int(body.get("id") or 0)
        bot_id = int(body.get("bot_id") or 0)
        if entry_id <= 0 or bot_id <= 0:
            raise HTTPException(status_code=400, detail="id and bot_id required")
        try:
            ok = await delete_memory_entry(entry_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="未找到该记忆条目")
        return JSONResponse({"ok": True, "data": {"id": entry_id}})

    @router.get(f"{x}/llm/conversation-kernel/relationship-notes", include_in_schema=True)
    async def _llm_conversation_kernel_relationship_notes_get(
        bot_id: int = Query(..., ge=1, description="Bot QQ"),
        group_id: int | None = Query(default=None, ge=1, description="群号"),
        query: str | None = Query(default=None, description="内容搜索"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        try:
            items = await list_relationship_notes(
                int(bot_id),
                group_id,
                query=str(query or "").strip(),
                limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items), "limit": limit}})

    @router.post(f"{x}/llm/conversation-kernel/relationship-notes/delete", include_in_schema=True)
    async def _llm_conversation_kernel_relationship_notes_delete(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        note_id = int(body.get("id") or 0)
        bot_id = int(body.get("bot_id") or 0)
        if note_id <= 0 or bot_id <= 0:
            raise HTTPException(status_code=400, detail="id and bot_id required")
        try:
            ok = await delete_relationship_note(note_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="未找到该关系备注")
        return JSONResponse({"ok": True, "data": {"id": note_id}})

    @router.get(f"{x}/llm/conversation-kernel/knowledge-sources", include_in_schema=True)
    async def _llm_conversation_kernel_knowledge_sources_get() -> JSONResponse:
        try:
            items = [
                {
                    "source_id": row.source_id,
                    "title": row.decl.title,
                    "description": row.decl.description,
                    "scope": row.decl.scope.value,
                    "retrieval_mode": row.decl.retrieval_mode.value,
                    "origin": row.origin.value,
                    "plugin_name": row.plugin_name,
                    "plugin_title": row.plugin_title,
                    "default": bool(row.decl.default),
                    "chunk_count": len(row.decl.chunks),
                }
                for row in list_active_knowledge_sources()
            ]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.get(f"{x}/llm/conversation-kernel/knowledge-sources/{{source_id}}", include_in_schema=True)
    async def _llm_conversation_kernel_knowledge_source_detail_get(
        source_id: str,
        preview_limit: int = Query(default=30, ge=1, le=100),
        preview_content_len: int = Query(default=240, ge=32, le=2000),
    ) -> JSONResponse:
        try:
            from pallas.product.llm.ops_api import build_knowledge_source_detail_ui

            data = build_knowledge_source_detail_ui(
                source_id,
                preview_limit=preview_limit,
                preview_content_len=preview_content_len,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if data is None:
            raise HTTPException(status_code=404, detail="未找到该语料源")
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/conversation-kernel/knowledge-sources/retrieve", include_in_schema=True)
    async def _llm_conversation_kernel_knowledge_sources_retrieve_post(
        body: dict[str, Any],
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import probe_knowledge_source_retrieve

        query = str(body.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query required")
        source_id = str(body.get("source_id") or "").strip() or None
        top_k_raw = body.get("top_k")
        top_k = int(top_k_raw) if top_k_raw is not None and str(top_k_raw).strip() != "" else None
        try:
            data = probe_knowledge_source_retrieve(query, source_id=source_id, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if data is None:
            raise HTTPException(status_code=404, detail="未找到该语料源")
        return JSONResponse({"ok": True, "data": data})
