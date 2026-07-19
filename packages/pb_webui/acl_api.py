"""Pallas-Bot WebUI：ACL 与 admin_members 端点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from pallas.core.perm.acl import clear_acl_cache, invalidate_acl_rules_cache

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


class _AclRuleDeleteBody(BaseModel):
    """按自然键 (role, subject, action, target_scope, target) 删除，
    比主键删除跨后端一致（Mongo ObjectId / PG int）；同时支持按主键。"""

    by: str = Field(default="signature")  # "signature" 或 "id"
    id: str | None = None
    role: str | None = None
    subject: str | None = None
    action: str | None = None
    target_scope: str | None = None
    target: str | None = None


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

    def _validate_subject(role: str, subject: str | None) -> None:
        """role=管理员 的 subject 必须是 "*" 或 "id:<uid>"；其他 role 自由。"""
        if role != "管理员":
            return
        ok = subject == "*" or (subject is not None and subject.startswith("id:"))
        if not ok:
            raise HTTPException(
                status_code=400,
                detail="role=管理员 时 subject 必须是 '*' 或 'id:<user_id>'",
            )
        if subject is not None and subject.startswith("id:"):
            try:
                int(subject[3:])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="id: 后必须是数字") from exc

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
        _validate_subject(body.role, body.subject)
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

    @router.delete(f"{x}/acl/rules")
    async def _delete_acl_rule(body: _AclRuleDeleteBody) -> dict[str, Any]:
        """按自然键或主键删除；推荐 ``by=signature`` 以保证跨后端一致。"""
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
        deleted = 0
        if body.by == "id" and body.id is not None:
            deleted = await repo.delete_rule(body.id)
        elif body.by == "signature":
            for key in (body.role, body.action, body.target_scope, body.target):
                if not key:
                    raise HTTPException(
                        status_code=400,
                        detail="by=signature 时必须提供 role / action / target_scope / target 四元组",
                    )
            deleted = await repo.delete_by_signature(
                role=body.role,
                subject=body.subject,
                action=body.action,
                target_scope=body.target_scope,
                target=body.target,
            )
        else:
            raise HTTPException(status_code=400, detail="by 必须是 'signature' 或 'id'")
        invalidate_acl_rules_cache()
        clear_acl_cache()
        return {"ok": True, "data": {"deleted": deleted}}

    # 旧路径：直接按 path param 删除（保留兼容，但默认走 signature 时建议走 body 版本）
    @router.delete(f"{x}/acl/rules/{{rule_id}}")
    async def _delete_acl_rule_by_id(rule_id: str) -> dict[str, Any]:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
        deleted = await repo.delete_rule(rule_id)  # 接受 str（Mongo ObjectId）或 int（PG）
        invalidate_acl_rules_cache()
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
    async def _delete_admin_member(member_id: str) -> dict[str, Any]:
        """按主键直删，避免 list 后再按 scope/bot_id 删除的竞态。"""
        from pallas.core.foundation.db import make_admin_repository

        repo = make_admin_repository()
        deleted = await repo.delete_member(member_id)
        clear_acl_cache()
        return {"ok": True, "data": {"deleted": deleted}}
