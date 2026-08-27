"""Pallas-Bot WebUI console API: LLM product routes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from pallas.product.llm.injection_feedback import list_injection_governance_status, undo_negative_outcome_status
from pallas.product.llm.memory.relationship import clamp_affinity
from pallas.product.llm.ops_api import (
    build_conversation_kernel_status,
    clear_feedback_entry_correction,
    clear_rage_state,
    delete_feedback_entry,
    delete_memory_entry,
    delete_relationship_note,
    find_feedback_entry,
    group_feedback_bias_snapshot,
    list_active_knowledge_sources,
    list_group_feedback_entries,
    list_memory_entries,
    list_recent_conversation_traces,
    list_relationship_notes,
    set_affinity,
    set_feedback_entry_correction,
    set_feedback_entry_eligibility,
    set_relationship_note_content,
)
from pallas.product.persona.expression_bank import ExpressionStatus, get_group_expression, list_group_expressions
from pallas.product.persona.expression_promote import resolve_expression

from .console_openapi_models import _ApiOkResponse
from .extended_common import check_pallas_write_token

if TYPE_CHECKING:
    from .config import Config


def _semantic_style():
    from pallas.product.llm import repeater_semantic_style

    return repeater_semantic_style


class _SemanticStyleDirectEnabledPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direct_enabled: bool | None = None


class InjectionGovernanceManageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["undo_outcome", "restore_expression", "restore_semantic"]
    bot_id: str
    group_id: str
    outcome_id: str | None = None
    entry_id: str | None = None
    source_example_id: str | None = None


class _ExpressionBankResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    action: Literal["approve", "reject", "restore"]
    reason: str = ""


def _injection_governance_scope(*, bot_id: str, group_id: str) -> tuple[int, int]:
    try:
        parsed_bot_id = int(str(bot_id).strip())
        parsed_group_id = int(str(group_id).strip())
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="bot_id 和 group_id 必须为正整数") from e
    if parsed_bot_id <= 0 or parsed_group_id <= 0:
        raise HTTPException(status_code=400, detail="bot_id 和 group_id 必须为正整数")
    return parsed_bot_id, parsed_group_id


class _SemanticStyleManageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "status",
        "direct_enabled",
        "clear",
        "rebuild",
        "quality",
        "recover",
        "disable",
        "enable",
        "set_governance",
    ]
    bot_id: int | None = None
    group_id: int | None = None
    scene: str = "group_chat"
    direct_enabled: bool | None = None
    collection_enabled: bool | None = None
    injection_enabled: bool | None = None
    continue_learning: bool | None = None


class _SemanticStyleProfileSummaryData(BaseModel):
    profile_ref: str
    scene: str
    sample_count: int = 0
    direct_example_count: int = 0
    direct_pair_count: int = 0
    rewrite_seed_count: int = 0
    intensity_counts: dict[str, int] = Field(default_factory=dict)
    form_counts: dict[str, int] = Field(default_factory=dict)
    bubble_count_p50: int = 0
    bubble_count_p90: int = 0
    segment_char_length_p50: int = 0
    segment_char_length_p90: int = 0
    rhythm_distribution: dict[str, float] = Field(default_factory=dict)
    updated_at: int = 0


class _SemanticStyleStatusData(BaseModel):
    enabled: bool = True
    collection_enabled: bool = True
    injection_enabled: bool = True
    direct_enabled: bool | None = None
    example_count: int = 0
    profile_count: int = 0
    backfill_cursor: dict[str, Any] = Field(default_factory=dict)
    profile_summary: _SemanticStyleProfileSummaryData | None = None


class _SemanticStyleQualityData(BaseModel):
    status: _SemanticStyleStatusData
    label_version: int
    positive_bot_style_count: int = 0


def semantic_style_response_data(
    data: dict[str, Any],
    *,
    bot_id: int | None,
    group_id: int | None,
    scene: str,
) -> dict[str, Any]:
    payload = dict(data)
    if bot_id is not None and group_id is not None:
        semantic_style = _semantic_style()
        semantic_style.refresh_semantic_style_cache()
        profile = semantic_style.cached_semantic_style_profile(bot_id, group_id, scene)
        payload["profile_summary"] = semantic_style.semantic_style_profile_summary(profile)
    return _SemanticStyleStatusData.model_validate(payload).model_dump(
        mode="json",
        exclude_none=True,
        exclude_unset=True,
    )


def semantic_style_quality_response_data(
    data: dict[str, Any],
    *,
    bot_id: int | None,
    group_id: int | None,
    scene: str,
) -> dict[str, Any]:
    return _SemanticStyleQualityData(
        status=semantic_style_response_data(
            data,
            bot_id=bot_id,
            group_id=group_id,
            scene=scene,
        ),
        label_version=int(data.get("label_version") or 0),
        positive_bot_style_count=int(data.get("positive_bot_style_count") or 0),
    ).model_dump(mode="json", exclude_none=True, exclude_unset=True)


def register_llm_product_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(
        f"{x}/llm/repeater-semantic-style",
        include_in_schema=True,
        response_model=_ApiOkResponse[_SemanticStyleStatusData],
    )
    async def _repeater_semantic_style_get(
        bot_id: int | None = Query(default=None, ge=1),
        group_id: int | None = Query(default=None, ge=1),
        scene: str = Query(default="group_chat", min_length=1, max_length=64),
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
        return JSONResponse({
            "ok": True,
            "data": semantic_style_response_data(
                data,
                bot_id=bot_id,
                group_id=group_id,
                scene=scene,
            ),
        })

    @router.post(
        f"{x}/llm/repeater-semantic-style/manage",
        include_in_schema=True,
        response_model=_ApiOkResponse[_SemanticStyleStatusData | _SemanticStyleQualityData],
    )
    async def _repeater_semantic_style_manage(
        body: _SemanticStyleManageBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        action = body.action
        bot_id = body.bot_id
        group_id = body.group_id
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
            elif action == "direct_enabled":
                if body.direct_enabled is None:
                    raise HTTPException(status_code=400, detail="direct_enabled 必须为布尔值")
                data = (
                    semantic_style.set_semantic_style_direct_enabled(body.direct_enabled, **scope)
                    if scope
                    else semantic_style.set_semantic_style_direct_enabled(body.direct_enabled)
                )
            elif action == "clear":
                clear_kwargs: dict[str, object] = {}
                if body.continue_learning is not None:
                    clear_kwargs["continue_learning"] = body.continue_learning
                data = (
                    semantic_style.clear_semantic_style_data(**clear_kwargs, **scope)
                    if scope
                    else semantic_style.clear_semantic_style_data(**clear_kwargs)
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
            elif action == "set_governance":
                if body.collection_enabled is None or body.injection_enabled is None:
                    raise HTTPException(
                        status_code=422,
                        detail="collection_enabled 和 injection_enabled 必须同时提供",
                    )
                governance_kwargs = {
                    "collection_enabled": body.collection_enabled,
                    "injection_enabled": body.injection_enabled,
                }
                data = (
                    semantic_style.set_semantic_style_governance(**governance_kwargs, **scope)
                    if scope
                    else semantic_style.set_semantic_style_governance(**governance_kwargs)
                )
            elif action == "enable":
                data = (
                    semantic_style.set_semantic_style_enabled(True, **scope)
                    if scope
                    else semantic_style.set_semantic_style_enabled(True)
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
        response_data = (
            semantic_style_quality_response_data(
                data,
                bot_id=scope.get("bot_id"),
                group_id=scope.get("group_id"),
                scene=body.scene,
            )
            if action == "quality"
            else semantic_style_response_data(
                data,
                bot_id=scope.get("bot_id"),
                group_id=scope.get("group_id"),
                scene=body.scene,
            )
        )
        return JSONResponse({
            "ok": True,
            "data": response_data,
        })

    @router.get(f"{x}/llm/repeater-feedback", include_in_schema=True)
    async def _llm_repeater_feedback_get(
        bot_id: int = Query(..., ge=1, description="Bot QQ"),
        group_id: int = Query(..., ge=1, description="群号"),
        limit: int = Query(default=20, ge=1, le=200),
    ) -> JSONResponse:
        try:
            rows = list_group_feedback_entries(group_id=group_id, bot_id=bot_id, limit=limit)
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

    @router.get(f"{x}/llm/repeater-feedback/governance", include_in_schema=True)
    async def _llm_repeater_feedback_governance_get(
        bot_id: str | None = Query(default=None, description="Bot QQ"),
        group_id: str | None = Query(default=None, description="群号"),
    ) -> JSONResponse:
        parsed_bot_id, parsed_group_id = _injection_governance_scope(
            bot_id=bot_id or "",
            group_id=group_id or "",
        )
        try:
            status, data = await asyncio.to_thread(
                list_injection_governance_status,
                bot_id=parsed_bot_id,
                group_id=parsed_group_id,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if status == "storage_error":
            raise HTTPException(status_code=500, detail="治理账本读取失败")
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/llm/repeater-feedback/governance/manage", include_in_schema=True)
    async def _llm_repeater_feedback_governance_manage(
        body: InjectionGovernanceManageRequest,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        bot_id, group_id = _injection_governance_scope(bot_id=body.bot_id, group_id=body.group_id)
        action = body.action
        if action == "restore_expression":
            entry_id = str(body.entry_id or "").strip()
            if not entry_id:
                raise HTTPException(status_code=400, detail="entry_id 必填")
            try:
                entry = await asyncio.to_thread(
                    get_group_expression,
                    group_id=group_id,
                    entry_id=entry_id,
                )
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=str(e)) from e
            if entry is None:
                raise HTTPException(status_code=404, detail="未找到该群表达记录")
            try:
                updated = await asyncio.to_thread(resolve_expression, entry_id, action="restore")
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=str(e)) from e
            if updated is None:
                raise HTTPException(status_code=404, detail="未找到该群表达记录")
            return JSONResponse({"ok": True, "data": {"entry_id": entry_id, "status": updated.status}})

        outcome_id = str(body.outcome_id or "").strip()
        if not outcome_id:
            raise HTTPException(status_code=400, detail="outcome_id 必填")
        source_example_id = str(body.source_example_id or "").strip()
        if action == "restore_semantic" and source_example_id:
            try:
                status, governance = await asyncio.to_thread(
                    list_injection_governance_status,
                    bot_id=bot_id,
                    group_id=group_id,
                )
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=str(e)) from e
            if status == "storage_error":
                raise HTTPException(status_code=500, detail="治理账本读取失败")
            outcome = next(
                (row for row in governance.get("outcomes", []) if str(row.get("outcome_id") or "") == outcome_id),
                None,
            )
            if outcome is None or not any(
                str(decision.get("source_id") or "") == source_example_id
                for decision in outcome.get("decisions", [])
                if isinstance(decision, dict)
            ):
                raise HTTPException(status_code=404, detail="未找到该语义样本对应的治理结果")
        try:
            undo_status = await asyncio.to_thread(
                undo_negative_outcome_status,
                outcome_id=outcome_id,
                bot_id=bot_id,
                group_id=group_id,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if undo_status == "storage_error":
            raise HTTPException(status_code=500, detail="治理账本写入失败")
        if undo_status != "undone":
            raise HTTPException(status_code=404, detail="未找到该群治理结果")
        data: dict[str, bool | str] = {"undone": True, "outcome_id": outcome_id}
        if action == "restore_semantic":
            data["semantic_restored"] = True
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
        raw_bot_id = body.get("bot_id")
        raw_group_id = body.get("group_id")
        if raw_bot_id is None or raw_group_id is None:
            raise HTTPException(status_code=400, detail="feedback manage 必须提供 bot_id 和 group_id")
        if (raw_bot_id is None) != (raw_group_id is None):
            raise HTTPException(status_code=400, detail="bot_id 和 group_id 必须同时提供")
        bot_id, group_id = _injection_governance_scope(
            bot_id=str(raw_bot_id),
            group_id=str(raw_group_id),
        )
        try:
            if action == "delete":
                ok = delete_feedback_entry(
                    entry_id=entry_id,
                    request_id=request_id,
                    bot_id=bot_id,
                    group_id=group_id,
                )
                if not ok:
                    raise HTTPException(status_code=404, detail="未找到该反哺记录")
                return JSONResponse({"ok": True, "data": {"deleted": True, "entry_id": entry_id or request_id}})
            if action == "correct":
                corrected_reply_text = str(body.get("corrected_reply_text") or "").strip()
                if not corrected_reply_text:
                    raise HTTPException(status_code=400, detail="corrected_reply_text 必填")
                create_fields: dict[str, Any] | None = None
                if (
                    find_feedback_entry(
                        entry_id=entry_id,
                        request_id=request_id,
                        bot_id=bot_id,
                        group_id=group_id,
                    )
                    is None
                ):
                    raw_user_id = body.get("user_id")
                    if raw_user_id is None:
                        raise HTTPException(
                            status_code=400,
                            detail="未找到反哺记录时需提供 bot_id / group_id / user_id",
                        )
                    try:
                        user_id = int(raw_user_id)
                    except (TypeError, ValueError) as e:
                        raise HTTPException(status_code=400, detail="user_id 必须为正整数") from e
                    if user_id <= 0:
                        raise HTTPException(status_code=400, detail="user_id 必须为正整数")
                    create_fields = {
                        "bot_id": bot_id,
                        "group_id": group_id,
                        "user_id": user_id,
                        "user_text": str(body.get("user_text") or "").strip(),
                        "reply_text": str(body.get("reply_text") or "").strip(),
                        "llm_route": str(body.get("llm_route") or "").strip(),
                        "behavior_scene": str(body.get("behavior_scene") or "").strip(),
                        "request_id": request_id,
                    }
                updated = set_feedback_entry_correction(
                    entry_id=entry_id,
                    request_id=request_id,
                    bot_id=bot_id,
                    group_id=group_id,
                    corrected_reply_text=corrected_reply_text,
                    create_fields=create_fields,
                )
            elif action == "clear_correction":
                updated = clear_feedback_entry_correction(
                    entry_id=entry_id,
                    request_id=request_id,
                    bot_id=bot_id,
                    group_id=group_id,
                )
            else:
                updated = set_feedback_entry_eligibility(
                    entry_id=entry_id,
                    request_id=request_id,
                    bot_id=bot_id,
                    group_id=group_id,
                    eligible_for_bias=action == "restore",
                )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if updated is None:
            raise HTTPException(status_code=404, detail="未找到该反哺记录")
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
        body: _ExpressionBankResolveRequest,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        entry_id = body.entry_id.strip()
        action = body.action
        if not entry_id:
            raise HTTPException(status_code=400, detail="entry_id required")
        try:
            updated = resolve_expression(
                entry_id,
                action=action,
                reason=body.reason.strip(),
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

    @router.post(f"{x}/llm/conversation-kernel/relationship-notes/set-affinity", include_in_schema=True)
    async def _llm_conversation_kernel_relationship_notes_set_affinity(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            bot_id = int(body.get("bot_id") or 0)
            group_id = int(body.get("group_id") or 0)
            user_id = int(body.get("user_id") or 0)
            affinity = float(body.get("affinity") or 0.0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="invalid numeric fields") from None
        if bot_id <= 0 or user_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id and user_id required")
        try:
            ok = await set_affinity(bot_id, group_id or None, user_id, affinity)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="设置好感度失败")
        clamped = clamp_affinity(affinity)
        return JSONResponse({"ok": True, "data": {"affinity": clamped}})

    @router.post(f"{x}/llm/conversation-kernel/relationship-notes/clear-rage", include_in_schema=True)
    async def _llm_conversation_kernel_relationship_notes_clear_rage(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            bot_id = int(body.get("bot_id") or 0)
            user_id = int(body.get("user_id") or 0)
            group_id = int(body.get("group_id") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="invalid numeric fields") from None
        if bot_id <= 0 or user_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id and user_id required")
        ok = await clear_rage_state(bot_id, group_id or None, user_id)
        return JSONResponse({"ok": True, "data": {"cleared": bool(ok)}})

    @router.post(f"{x}/llm/conversation-kernel/relationship-notes/set-content", include_in_schema=True)
    async def _llm_conversation_kernel_relationship_notes_set_content(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            bot_id = int(body.get("bot_id") or 0)
            group_id = int(body.get("group_id") or 0)
            user_id = int(body.get("user_id") or 0)
            content = str(body.get("content") or "").strip()
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="invalid numeric fields") from None
        if bot_id <= 0 or user_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id and user_id required")
        if not content:
            raise HTTPException(status_code=400, detail="content required")
        try:
            ok = await set_relationship_note_content(bot_id, group_id or None, user_id, content)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="未找到该关系备注")
        return JSONResponse({"ok": True, "data": {"bot_id": bot_id, "user_id": user_id}})

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
