"""社交型 Agent 平台控制台 API：人物、观察队列、任务、口癖、工具目录。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from packages.pb_webui.config import Config


def register_agent_platform_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    check_write_token,
) -> None:
    @router.get(f"{x}/llm/agent-platform/overview", include_in_schema=True)
    async def agent_platform_overview(
        bot_id: int | None = Query(default=None, ge=1),
        group_id: int | None = Query(default=None, ge=0),
    ) -> JSONResponse:
        from pallas.product.llm.memory.observation import observation_queue_size
        from pallas.product.llm.orchestration.task_store import list_tasks
        from pallas.product.llm.tools.registry import build_tools_catalog_ui, ensure_tools_loaded
        from pallas.product.persona.catchphrase_bank import list_catchphrases

        ensure_tools_loaded()
        catalog = build_tools_catalog_ui()
        tasks = [item for item in list_tasks() if group_id is None or item.group_id in (None, int(group_id))][:50]
        catchphrases = list_catchphrases(bot_id)
        tools = catalog.get("items") if isinstance(catalog, dict) else None
        return JSONResponse({
            "ok": True,
            "data": {
                "observation_queue_size": observation_queue_size(),
                "tool_count": len(tools) if isinstance(tools, list) else int(catalog.get("count") or 0),
                "task_count": len(tasks),
                "open_tasks": sum(1 for item in tasks if item.status not in {"done", "cancelled"}),
                "catchphrase_candidates": sum(1 for item in catchphrases if item.status == "candidate"),
                "catchphrase_active": sum(1 for item in catchphrases if item.status == "active"),
                "scope": {"bot_id": bot_id, "group_id": group_id},
            },
        })

    @router.get(f"{x}/llm/agent-platform/person-facts", include_in_schema=True)
    async def person_facts_list(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        user_id: int | None = Query(default=None, ge=1),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.memory.person_facts import list_person_facts

        items = list_person_facts(bot_id=bot_id, group_id=group_id, user_id=user_id, limit=limit)
        return JSONResponse({"ok": True, "data": {"items": [item.model_dump() for item in items], "count": len(items)}})

    @router.post(f"{x}/llm/agent-platform/person-facts", include_in_schema=True)
    async def person_facts_save(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.memory.person_facts import save_person_fact

        bot_id = int(body.get("bot_id") or 0)
        user_id = int(body.get("user_id") or 0)
        content = str(body.get("content") or "").strip()
        if bot_id <= 0 or user_id <= 0 or not content:
            raise HTTPException(status_code=400, detail="bot_id, user_id, content required")
        try:
            item = save_person_fact(
                bot_id=bot_id,
                group_id=int(body.get("group_id") or 0),
                user_id=user_id,
                content=content,
                source=str(body.get("source") or "manual"),
                scope=str(body.get("scope") or "group"),  # type: ignore[arg-type]
                confidence=float(body.get("confidence") or 0.6),
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "data": item.model_dump()})

    @router.post(f"{x}/llm/agent-platform/person-facts/correct", include_in_schema=True)
    async def person_facts_correct(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.memory.person_facts import correct_person_fact

        item = correct_person_fact(str(body.get("fact_id") or ""), str(body.get("content") or ""))
        if item is None:
            raise HTTPException(status_code=404, detail="fact not found")
        return JSONResponse({"ok": True, "data": item.model_dump()})

    @router.get(f"{x}/llm/agent-platform/consent", include_in_schema=True)
    async def consent_get(user_id: int = Query(..., ge=1), platform: str = Query(default="qq")) -> JSONResponse:
        from pallas.product.llm.memory.consent import get_consent

        item = get_consent(user_id, platform=platform)
        return JSONResponse({"ok": True, "data": item.model_dump()})

    @router.post(f"{x}/llm/agent-platform/consent", include_in_schema=True)
    async def consent_set(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.memory.consent import set_consent

        user_id = int(body.get("user_id") or 0)
        if user_id <= 0:
            raise HTTPException(status_code=400, detail="user_id required")
        item = set_consent(
            user_id,
            platform=str(body.get("platform") or "qq"),
            granted=bool(body.get("granted")),
            scopes=list(body.get("scopes") or ["stable_preferences"]),
        )
        return JSONResponse({"ok": True, "data": item.model_dump()})

    @router.get(f"{x}/llm/agent-platform/observations", include_in_schema=True)
    async def observations_list(
        bot_id: int | None = Query(default=None, ge=1),
        group_id: int | None = Query(default=None, ge=0),
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.memory.observation import list_observations, observation_queue_size

        status_filter = None if status in (None, "", "all") else status
        items = list_observations(
            bot_id=bot_id,
            group_id=group_id,
            status=status_filter,  # type: ignore[arg-type]
            limit=limit,
        )
        return JSONResponse({
            "ok": True,
            "data": {
                "items": [item.model_dump() for item in items],
                "count": len(items),
                "queue_size": observation_queue_size(),
            },
        })

    @router.get(f"{x}/llm/agent-platform/tasks", include_in_schema=True)
    async def tasks_list(
        group_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.orchestration.task_store import list_tasks

        items = [
            item.model_dump() for item in list_tasks() if group_id is None or item.group_id in (None, int(group_id))
        ][:limit]
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.post(f"{x}/llm/agent-platform/tasks/cancel", include_in_schema=True)
    async def tasks_cancel(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.orchestration.task_store import cancel_task

        item = cancel_task(str(body.get("task_id") or ""))
        if item is None:
            raise HTTPException(status_code=404, detail="task not found")
        return JSONResponse({"ok": True, "data": item.model_dump()})

    @router.get(f"{x}/llm/agent-platform/catchphrases", include_in_schema=True)
    async def catchphrases_list(
        bot_id: int | None = Query(default=None, ge=1),
        status: str | None = Query(default=None),
    ) -> JSONResponse:
        from pallas.product.persona.catchphrase_bank import list_catchphrases

        items = list_catchphrases(bot_id, status=status)
        return JSONResponse({"ok": True, "data": {"items": [item.model_dump() for item in items], "count": len(items)}})

    @router.post(f"{x}/llm/agent-platform/catchphrases/resolve", include_in_schema=True)
    async def catchphrases_resolve(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.persona.catchphrase_bank import promote_catchphrase, reject_catchphrase

        action = str(body.get("action") or "").strip().lower()
        entry_id = str(body.get("entry_id") or "").strip()
        if action == "approve":
            item = promote_catchphrase(entry_id, force=True)
        elif action == "reject":
            item = reject_catchphrase(entry_id)
        else:
            raise HTTPException(status_code=400, detail="action must be approve or reject")
        if item is None:
            raise HTTPException(status_code=404, detail="catchphrase not found or not eligible")
        return JSONResponse({"ok": True, "data": item.model_dump()})

    @router.get(f"{x}/llm/agent-platform/tools", include_in_schema=True)
    async def tools_catalog() -> JSONResponse:
        from pallas.product.llm.tools.registry import build_tools_catalog_ui, ensure_tools_loaded

        ensure_tools_loaded()
        return JSONResponse({"ok": True, "data": build_tools_catalog_ui()})
