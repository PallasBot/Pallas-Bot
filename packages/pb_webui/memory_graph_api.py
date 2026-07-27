"""记忆图谱运营 API（Episode / Entity / Edge / Graph）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from packages.pb_webui.config import Config


def register_memory_graph_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    check_write_token,
) -> None:
    base = f"{x}/llm/conversation-kernel/memory/graph"

    @router.get(f"{base}/stats", include_in_schema=True)
    async def _memory_graph_stats(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        scope_key: str | None = Query(default=None),
        materialize: bool = Query(default=True),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import build_graph_stats

        try:
            data = await build_graph_stats(
                bot_id=bot_id,
                group_id=group_id,
                scope_key=scope_key,
                materialize=materialize,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{base}/scopes", include_in_schema=True)
    async def _memory_graph_scopes(
        bot_id: int = Query(..., ge=1),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_scopes

        try:
            items = await list_scopes(bot_id=bot_id, limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "count": len(items)}})

    @router.get(f"{base}", include_in_schema=True)
    async def _memory_graph_payload(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        scope_key: str | None = Query(default=None),
        materialize: bool = Query(default=True),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import build_graph_payload

        try:
            data = await build_graph_payload(
                bot_id=bot_id,
                group_id=group_id,
                scope_key=scope_key,
                materialize=materialize,
                limit=limit,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{base}/episodes", include_in_schema=True)
    async def _memory_graph_episodes(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        query: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_episodes

        try:
            items = await list_episodes(bot_id=bot_id, group_id=group_id, query=str(query or ""), limit=limit)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "total": len(items), "page": 1, "page_size": limit}})

    @router.get(f"{base}/entities", include_in_schema=True)
    async def _memory_graph_entities_list(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        query: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        materialize: bool = Query(default=True),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import (
            list_entities,
            materialize_keyword_entities,
            materialize_relationship_notes,
        )

        try:
            if materialize:
                await materialize_relationship_notes(bot_id=bot_id, group_id=group_id)
                await materialize_keyword_entities(bot_id=bot_id, group_id=group_id, limit=40)
            items = await list_entities(
                bot_id=bot_id, group_id=group_id, query=str(query or ""), kind=kind, limit=limit
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "total": len(items), "page": 1, "page_size": limit}})

    @router.post(f"{base}/entities", include_in_schema=True)
    async def _memory_graph_entities_upsert(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import upsert_entity

        bot_id = int(body.get("bot_id") or 0)
        name = str(body.get("name") or "").strip()
        if bot_id <= 0 or not name:
            raise HTTPException(status_code=400, detail="bot_id and name required")
        group_id = body.get("group_id")
        try:
            item = await upsert_entity(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else None,
                scope_key=str(body.get("scope_key") or "") or None,
                name=name,
                summary=str(body.get("summary") or ""),
                tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
                kind=str(body.get("kind") or "concept"),
                user_id=int(body["user_id"]) if body.get("user_id") is not None else None,
                source=str(body.get("source") or "manual"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not item:
            raise HTTPException(status_code=400, detail="entity upsert failed")
        return JSONResponse({"ok": True, "data": item})

    @router.post(f"{base}/entities/delete", include_in_schema=True)
    async def _memory_graph_entities_delete(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import delete_entity

        entity_id = int(body.get("id") or body.get("entity_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if entity_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await delete_entity(entity_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="entity not found")
        return JSONResponse({"ok": True, "data": {"deleted": True, "id": str(entity_id)}})

    @router.get(f"{base}/edges", include_in_schema=True)
    async def _memory_graph_edges_list(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        include_invalid: bool = Query(default=False),
        materialize: bool = Query(default=True),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_edges, materialize_relationship_notes

        try:
            if materialize:
                await materialize_relationship_notes(bot_id=bot_id, group_id=group_id)
            items = await list_edges(bot_id=bot_id, group_id=group_id, include_invalid=include_invalid, limit=limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "total": len(items), "page": 1, "page_size": limit}})

    @router.post(f"{base}/edges", include_in_schema=True)
    async def _memory_graph_edges_upsert(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import upsert_edge

        bot_id = int(body.get("bot_id") or 0)
        fact = str(body.get("fact") or "").strip()
        source_entity_id = int(body.get("source_entity_id") or 0)
        target_entity_id = int(body.get("target_entity_id") or 0)
        if bot_id <= 0 or not fact or source_entity_id <= 0 or target_entity_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id, fact, source_entity_id, target_entity_id required")
        group_id = body.get("group_id")
        try:
            item = await upsert_edge(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else None,
                scope_key=str(body.get("scope_key") or "") or None,
                fact=fact,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relation_type=str(body.get("relation_type") or "related_to"),
                weight=float(body.get("weight") or 1.0),
                episode_ids=body.get("episode_ids") if isinstance(body.get("episode_ids"), list) else None,
                source=str(body.get("source") or "manual"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not item:
            raise HTTPException(status_code=400, detail="edge upsert failed")
        return JSONResponse({"ok": True, "data": item})

    @router.post(f"{base}/edges/delete", include_in_schema=True)
    async def _memory_graph_edges_delete(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import soft_delete_edge

        edge_id = int(body.get("id") or body.get("edge_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if edge_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await soft_delete_edge(edge_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="edge not found")
        return JSONResponse({"ok": True, "data": {"deleted": True, "id": str(edge_id)}})

    @router.post(f"{base}/edges/restore", include_in_schema=True)
    async def _memory_graph_edges_restore(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import restore_edge

        edge_id = int(body.get("id") or body.get("edge_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if edge_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await restore_edge(edge_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="edge not found")
        return JSONResponse({"ok": True, "data": {"restored": True, "id": str(edge_id)}})

    @router.post(f"{base}/entities/restore", include_in_schema=True)
    async def _memory_graph_entities_restore(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import restore_entity

        entity_id = int(body.get("id") or body.get("entity_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if entity_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await restore_entity(entity_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="entity not found")
        return JSONResponse({"ok": True, "data": {"restored": True, "id": str(entity_id)}})

    @router.post(f"{base}/entities/purge", include_in_schema=True)
    async def _memory_graph_entities_purge(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import purge_entity

        entity_id = int(body.get("id") or body.get("entity_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if entity_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await purge_entity(entity_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="entity not found")
        return JSONResponse({"ok": True, "data": {"purged": True, "id": str(entity_id)}})

    @router.get(f"{base}/categories", include_in_schema=True)
    async def _memory_graph_categories_list(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        include_deleted: bool = Query(default=False),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_categories

        try:
            items = await list_categories(
                bot_id=bot_id, group_id=group_id, include_deleted=include_deleted, limit=limit
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"items": items, "total": len(items)}})

    @router.post(f"{base}/categories", include_in_schema=True)
    async def _memory_graph_categories_upsert(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import upsert_category

        bot_id = int(body.get("bot_id") or 0)
        name = str(body.get("name") or "").strip()
        if bot_id <= 0 or not name:
            raise HTTPException(status_code=400, detail="bot_id and name required")
        group_id = body.get("group_id")
        try:
            item = await upsert_category(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else None,
                scope_key=str(body.get("scope_key") or "") or None,
                name=name,
                summary=str(body.get("summary") or ""),
                tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
                layer=int(body.get("layer") or 1),
                parent_id=int(body["parent_id"]) if body.get("parent_id") is not None else None,
                member_entity_ids=body.get("member_entity_ids")
                if isinstance(body.get("member_entity_ids"), list)
                else None,
                source=str(body.get("source") or "manual"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not item:
            raise HTTPException(status_code=400, detail="category upsert failed")
        return JSONResponse({"ok": True, "data": item})

    @router.post(f"{base}/categories/delete", include_in_schema=True)
    async def _memory_graph_categories_delete(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import soft_delete_category

        category_id = int(body.get("id") or body.get("category_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if category_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await soft_delete_category(category_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="category not found")
        return JSONResponse({"ok": True, "data": {"deleted": True, "id": str(category_id)}})

    @router.post(f"{base}/categories/restore", include_in_schema=True)
    async def _memory_graph_categories_restore(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import restore_category

        category_id = int(body.get("id") or body.get("category_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if category_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await restore_category(category_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="category not found")
        return JSONResponse({"ok": True, "data": {"restored": True, "id": str(category_id)}})

    @router.post(f"{base}/categories/purge", include_in_schema=True)
    async def _memory_graph_categories_purge(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import purge_category

        category_id = int(body.get("id") or body.get("category_id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if category_id <= 0:
            raise HTTPException(status_code=400, detail="id required")
        try:
            ok = await purge_category(category_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="category not found")
        return JSONResponse({"ok": True, "data": {"purged": True, "id": str(category_id)}})

    @router.get(f"{base}/hiergraph/status", include_in_schema=True)
    async def _memory_graph_hiergraph_status(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        scope_key: str | None = Query(default=None),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import get_hiergraph_status

        try:
            data = await get_hiergraph_status(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data or {}})

    @router.post(f"{base}/hiergraph/rebuild", include_in_schema=True)
    async def _memory_graph_hiergraph_rebuild(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import rebuild_hiergraph

        bot_id = int(body.get("bot_id") or 0)
        if bot_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id required")
        group_id = body.get("group_id")
        max_layers = body.get("max_layers")
        try:
            data = await rebuild_hiergraph(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else None,
                scope_key=str(body.get("scope_key") or "") or None,
                max_layers=int(max_layers) if max_layers is not None else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{base}/extract", include_in_schema=True)
    async def _memory_graph_extract(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import extract_from_episodes, extract_from_text

        bot_id = int(body.get("bot_id") or 0)
        if bot_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id required")
        group_id = body.get("group_id")
        gid = int(group_id) if group_id is not None else None
        text = str(body.get("text") or "").strip()
        try:
            if text:
                data = await extract_from_text(
                    bot_id=bot_id,
                    group_id=gid,
                    text=text,
                    episode_id=str(body.get("episode_id") or "") or None,
                )
            else:
                data = await extract_from_episodes(
                    bot_id=bot_id,
                    group_id=gid,
                    limit=int(body.get("limit") or 20),
                )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if data.get("error"):
            raise HTTPException(status_code=400, detail=str(data["error"]))
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{base}/trash", include_in_schema=True)
    async def _memory_graph_trash(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import list_trash

        try:
            data = await list_trash(bot_id=bot_id, group_id=group_id, limit=limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{base}/trash/restore", include_in_schema=True)
    async def _memory_graph_trash_restore(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import (
            restore_category,
            restore_edge,
            restore_entity,
        )

        kind = str(body.get("kind") or "").strip().lower()
        item_id = int(body.get("id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if item_id <= 0 or kind not in {"entity", "edge", "category"}:
            raise HTTPException(status_code=400, detail="kind and id required")
        try:
            if kind == "entity":
                ok = await restore_entity(item_id, bot_id=bot_id)
            elif kind == "edge":
                ok = await restore_edge(item_id, bot_id=bot_id)
            else:
                ok = await restore_category(item_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="item not found")
        return JSONResponse({"ok": True, "data": {"restored": True, "kind": kind, "id": str(item_id)}})

    @router.post(f"{base}/trash/purge", include_in_schema=True)
    async def _memory_graph_trash_purge(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import purge_category, purge_entity

        kind = str(body.get("kind") or "").strip().lower()
        item_id = int(body.get("id") or 0)
        bot_id = int(body.get("bot_id") or 0) or None
        if item_id <= 0 or kind not in {"entity", "category"}:
            raise HTTPException(status_code=400, detail="kind(entity|category) and id required")
        try:
            if kind == "entity":
                ok = await purge_entity(item_id, bot_id=bot_id)
            else:
                ok = await purge_category(item_id, bot_id=bot_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=404, detail="item not found")
        return JSONResponse({"ok": True, "data": {"purged": True, "kind": kind, "id": str(item_id)}})

    @router.post(f"{base}/clear", include_in_schema=True)
    async def _memory_graph_clear(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import clear_scope_graph

        bot_id = int(body.get("bot_id") or 0)
        if bot_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id required")
        group_id = body.get("group_id")
        hard = bool(body.get("hard"))
        try:
            data = await clear_scope_graph(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else None,
                scope_key=str(body.get("scope_key") or "") or None,
                hard=hard,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{base}/export", include_in_schema=True)
    async def _memory_graph_export(
        bot_id: int = Query(..., ge=1),
        group_id: int | None = Query(default=None, ge=0),
        scope_key: str | None = Query(default=None),
    ) -> JSONResponse:
        from pallas.product.llm.ops_api import export_scope_graph

        try:
            data = await export_scope_graph(bot_id=bot_id, group_id=group_id, scope_key=scope_key)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{base}/import", include_in_schema=True)
    async def _memory_graph_import(
        body: dict[str, Any],
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.product.llm.ops_api import import_scope_graph

        bot_id = int(body.get("bot_id") or 0)
        if bot_id <= 0:
            raise HTTPException(status_code=400, detail="bot_id required")
        group_id = body.get("group_id")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
        try:
            data = await import_scope_graph(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else 0,
                payload=payload,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{base}/search", include_in_schema=True)
    async def _memory_graph_search(body: dict[str, Any]) -> JSONResponse:
        from pallas.product.llm.ops_api import search_memory_graph

        bot_id = int(body.get("bot_id") or 0)
        query = str(body.get("query") or "").strip()
        if bot_id <= 0 or not query:
            raise HTTPException(status_code=400, detail="bot_id and query required")
        group_id = body.get("group_id")
        limit = int(body.get("limit") or 30)
        try:
            data = await search_memory_graph(
                bot_id=bot_id,
                group_id=int(group_id) if group_id is not None else None,
                query=query,
                limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})
