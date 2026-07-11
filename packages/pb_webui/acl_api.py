"""Pallas-Bot WebUI：ACL 与 admin_members 端点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from pallas.core.perm.acl import clear_acl_cache

ACL_ROLES = {"用户", "群", "管理员", "所有"}
ACL_SCOPES = {"全局", "插件", "指令"}
ACL_EFFECTS = {"allow", "deny"}


class _AclRuleBody(BaseModel):
    role: str = Field(...)
    subject: str | None = None
    action: str = Field(...)
    target_scope: str = Field(...)
    target: str = Field(...)
    effect: str = Field(...)
    priority: int = 100
    source: str = "user"


class _AdminMemberBody(BaseModel):
    user_id: int
    scope: str  # "bot" | "all"
    bot_id: int | None = None
    note: str | None = None


def register_acl_router(router: APIRouter, x: str = "/pallas/api") -> None:
    """把 ACL / admin_members 端点挂到内层 router（走 _pallas_token_dep 守门）。"""

    def _require_role(role: str) -> str:
        if role not in ACL_ROLES:
            raise HTTPException(status_code=400, detail=f"role 必须是 {sorted(ACL_ROLES)}")
        return role

    def _require_scope(scope: str) -> str:
        if scope not in ACL_SCOPES:
            raise HTTPException(status_code=400, detail=f"target_scope 必须是 {sorted(ACL_SCOPES)}")
        return scope

    def _require_effect(effect: str) -> str:
        if effect not in ACL_EFFECTS:
            raise HTTPException(status_code=400, detail=f"effect 必须是 {sorted(ACL_EFFECTS)}")
        return effect

    @router.get(f"{x}/acl/rules")
    async def _list_acl_rules(
        action: str | None = None,
        target: str | None = None,
        role: str | None = None,
        subject: str | None = None,
    ) -> dict[str, Any]:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
        rules = await repo.list_rules(action=action, target=target, role=role, subject=subject)
        # 兼容 Beanie Document 与 PG row_to_*
        return {
            "ok": True,
            "data": [
                {
                    "id": getattr(r, "id", None),
                    "role": r.role,
                    "subject": r.subject,
                    "action": r.action,
                    "target_scope": r.target_scope,
                    "target": r.target,
                    "effect": r.effect,
                    "priority": int(r.priority),
                    "source": r.source,
                }
                for r in rules
            ],
        }

    @router.post(f"{x}/acl/rules")
    async def _create_acl_rule(
        body: _AclRuleBody,
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
        token: str | None = Query(default=None),
    ) -> dict[str, Any]:
        from pallas.core.foundation.db import make_acl_repository

        _require_role(body.role)
        _require_scope(body.target_scope)
        _require_effect(body.effect)
        repo = make_acl_repository()
        rule = await repo.upsert_rule(
            role=body.role,
            subject=body.subject,
            action=body.action,
            target_scope=body.target_scope,
            target=body.target,
            effect=body.effect,
            priority=int(body.priority),
            source=body.source,
        )
        clear_acl_cache()
        return {
            "ok": True,
            "data": {
                "id": getattr(rule, "id", None),
                "role": rule.role,
                "subject": rule.subject,
                "action": rule.action,
                "target_scope": rule.target_scope,
                "target": rule.target,
                "effect": rule.effect,
                "priority": int(rule.priority),
                "source": rule.source,
            },
        }

    @router.delete(f"{x}/acl/rules/{{rule_id}}")
    async def _delete_acl_rule(rule_id: int) -> dict[str, Any]:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
        deleted = await repo.delete_rule(int(rule_id))
        clear_acl_cache()
        return {"ok": True, "data": {"deleted": deleted}}

    @router.get(f"{x}/acl/summary")
    async def _acl_summary() -> dict[str, Any]:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
        rules = await repo.list_all()
        summary: dict[str, dict[str, int]] = {}
        for r in rules:
            key = r.action
            summary.setdefault(key, {"allow": 0, "deny": 0})
            summary[key][r.effect] = summary[key].get(r.effect, 0) + 1
        return {"ok": True, "data": summary}

    @router.get(f"{x}/admin_members")
    async def _list_admin_members(
        scope: str | None = None,
        bot_id: int | None = None,
    ) -> dict[str, Any]:
        from pallas.core.foundation.db import make_admin_repository

        repo = make_admin_repository()
        members = await repo.list_members(scope=scope, bot_id=bot_id)
        return {
            "ok": True,
            "data": [
                {
                    "id": getattr(m, "id", None),
                    "scope": m.scope,
                    "bot_id": getattr(m, "bot_id", None),
                    "user_id": m.user_id,
                    "note": getattr(m, "note", None),
                }
                for m in members
            ],
        }

    @router.post(f"{x}/admin_members")
    async def _create_admin_member(body: _AdminMemberBody) -> dict[str, Any]:
        from pallas.core.foundation.db import make_admin_repository

        if body.scope not in ("bot", "all"):
            raise HTTPException(status_code=400, detail="scope 必须是 bot|all")
        if body.scope == "bot" and body.bot_id is None:
            raise HTTPException(status_code=400, detail="scope=bot 必须传 bot_id")
        repo = make_admin_repository()
        m = await repo.upsert_member(
            user_id=int(body.user_id),
            scope=body.scope,
            bot_id=int(body.bot_id) if body.bot_id is not None else None,
            note=body.note,
        )
        clear_acl_cache()
        return {
            "ok": True,
            "data": {
                "id": getattr(m, "id", None),
                "scope": m.scope,
                "bot_id": getattr(m, "bot_id", None),
                "user_id": m.user_id,
            },
        }

    @router.delete(f"{x}/admin_members/{{member_id}}")
    async def _delete_admin_member(member_id: int) -> dict[str, Any]:
        from pallas.core.foundation.db import make_admin_repository

        repo = make_admin_repository()
        # member_id 来自 GET 列表；解析 scope/bot_id 再删除最简实现：先 list 再精确删除
        members = await repo.list_members()
        target = next((m for m in members if getattr(m, "id", None) == int(member_id)), None)
        deleted = 0
        if target is not None:
            deleted = await repo.remove_member(
                user_id=int(target.user_id),
                scope=target.scope,
                bot_id=getattr(target, "bot_id", None),
            )
        clear_acl_cache()
        return {"ok": True, "data": {"deleted": deleted}}
