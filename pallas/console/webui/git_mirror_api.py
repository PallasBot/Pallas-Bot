"""控制台 Git 镜像源 API。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from pallas.core.shared.utils.git_mirror import (
    GIT_MIRROR_SCOPES,
    apply_mirror_to_all_targets,
    apply_mirror_to_bot,
    apply_mirror_to_community_plugins,
    apply_mirror_to_official_extension,
    apply_mirror_to_plugin,
    build_git_mirror_info,
    load_git_mirror_config,
    mirror_by_id,
    probe_preferred_mirror,
    resolve_mirror_by_preferred_id,
    save_git_mirror_config,
    validate_custom_proxy_prefix,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class GitMirrorPreferredBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_id: str = Field(min_length=1, max_length=64)
    custom_proxy_prefix: str = Field(default="", max_length=512)
    scopes: dict[str, str] | None = None


class GitMirrorApplyPluginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_id: str | None = Field(default=None, max_length=64)


class GitMirrorApplyTargetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_id: str | None = Field(default=None, max_length=64)


class GitMirrorProbeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mirror_id: str | None = Field(default=None, max_length=64)


def _validate_mirror_id(preferred_id: str, custom_prefix: str) -> None:
    if preferred_id == "custom":
        if not custom_prefix:
            raise HTTPException(status_code=400, detail="自定义镜像须填写 custom_proxy_prefix")
        try:
            validate_custom_proxy_prefix(custom_prefix)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    elif mirror_by_id(preferred_id) is None:
        raise HTTPException(status_code=400, detail=f"未知镜像 id: {preferred_id}")


def _normalize_request_scopes(scopes: dict[str, str] | None) -> dict[str, str] | None:
    if scopes is None:
        return None
    out: dict[str, str] = {}
    for key, value in scopes.items():
        scope = str(key).strip()
        if scope not in GIT_MIRROR_SCOPES:
            raise HTTPException(status_code=400, detail=f"未知 scope: {scope}")
        mid = str(value or "").strip()
        if mid and mid != "custom" and mirror_by_id(mid) is None:
            raise HTTPException(status_code=400, detail=f"未知镜像 id: {mid}")
        out[scope] = mid
    return out


def git_mirror_info_payload() -> dict[str, Any]:
    return build_git_mirror_info()


def save_git_mirror_preferred(body: GitMirrorPreferredBody) -> dict[str, Any]:
    preferred_id = body.preferred_id.strip()
    custom_prefix = (body.custom_proxy_prefix or "").strip()
    _validate_mirror_id(preferred_id, custom_prefix)
    scopes = _normalize_request_scopes(body.scopes)
    if scopes:
        cfg = load_git_mirror_config()
        for mid in scopes.values():
            if mid == "custom":
                _validate_mirror_id("custom", custom_prefix or str(cfg.get("custom_proxy_prefix") or ""))
    save_git_mirror_config(
        preferred_id=preferred_id,
        custom_proxy_prefix=custom_prefix,
        scopes=scopes,
    )
    return git_mirror_info_payload()


def apply_git_mirror_to_community(body: GitMirrorApplyTargetBody | None = None) -> dict[str, Any]:
    mirror = None
    if body and (body.preferred_id or "").strip():
        cfg = load_git_mirror_config()
        mirror = resolve_mirror_by_preferred_id(
            body.preferred_id or "",
            custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
        )
    return apply_mirror_to_community_plugins(mirror=mirror)


def apply_git_mirror_to_plugin(plugin_id: str, body: GitMirrorApplyPluginBody) -> dict[str, Any]:
    mirror = None
    if (body.preferred_id or "").strip():
        cfg = load_git_mirror_config()
        mirror = resolve_mirror_by_preferred_id(
            body.preferred_id or "",
            custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
        )
    return apply_mirror_to_plugin(plugin_id, mirror=mirror)


def apply_git_mirror_to_official(package: str, body: GitMirrorApplyPluginBody) -> dict[str, Any]:
    mirror = None
    if (body.preferred_id or "").strip():
        cfg = load_git_mirror_config()
        mirror = resolve_mirror_by_preferred_id(
            body.preferred_id or "",
            custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
        )
    return apply_mirror_to_official_extension(package, mirror=mirror)


def apply_git_mirror_to_bot(body: GitMirrorApplyTargetBody | None = None) -> dict[str, Any]:
    mirror = None
    if body and (body.preferred_id or "").strip():
        cfg = load_git_mirror_config()
        mirror = resolve_mirror_by_preferred_id(
            body.preferred_id or "",
            custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
        )
    return apply_mirror_to_bot(mirror=mirror)


def apply_git_mirror_to_all(body: GitMirrorApplyTargetBody | None = None) -> dict[str, Any]:
    mirror = None
    if body and (body.preferred_id or "").strip():
        cfg = load_git_mirror_config()
        mirror = resolve_mirror_by_preferred_id(
            body.preferred_id or "",
            custom_proxy_prefix=str(cfg.get("custom_proxy_prefix") or ""),
        )
    return apply_mirror_to_all_targets(mirror=mirror)


async def probe_git_mirror(body: GitMirrorProbeBody | None = None) -> dict[str, Any]:
    mirror_id = (body.mirror_id if body else None) or None
    return await probe_preferred_mirror(mirror_id=mirror_id)


def register_git_mirror_router(
    router: APIRouter,
    *,
    x: str,
    check_write_token: Callable[..., None],
) -> None:
    @router.get(f"{x}/git-mirror/info", include_in_schema=True)
    async def _git_mirror_info() -> JSONResponse:
        return JSONResponse({"ok": True, "data": git_mirror_info_payload()})

    @router.put(f"{x}/git-mirror/preferred", include_in_schema=True)
    async def _git_mirror_preferred(
        body: GitMirrorPreferredBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(x_pallas_token=x_pallas_token, token=token)
        data = save_git_mirror_preferred(body)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/git-mirror/apply-community", include_in_schema=True)
    async def _git_mirror_apply_community(
        body: GitMirrorApplyTargetBody | None = None,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(x_pallas_token=x_pallas_token, token=token)
        data = apply_git_mirror_to_community(body)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/git-mirror/apply-bot", include_in_schema=True)
    async def _git_mirror_apply_bot(
        body: GitMirrorApplyTargetBody | None = None,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(x_pallas_token=x_pallas_token, token=token)
        data = apply_git_mirror_to_bot(body)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/git-mirror/apply-all", include_in_schema=True)
    async def _git_mirror_apply_all(
        body: GitMirrorApplyTargetBody | None = None,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(x_pallas_token=x_pallas_token, token=token)
        data = apply_git_mirror_to_all(body)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/git-mirror/apply-official/{{package}}", include_in_schema=True)
    async def _git_mirror_apply_official(
        package: str,
        body: GitMirrorApplyPluginBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(x_pallas_token=x_pallas_token, token=token)
        data = apply_git_mirror_to_official(package, body)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/git-mirror/apply-plugin/{{plugin_id}}", include_in_schema=True)
    async def _git_mirror_apply_plugin(
        plugin_id: str,
        body: GitMirrorApplyPluginBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_write_token(x_pallas_token=x_pallas_token, token=token)
        data = apply_git_mirror_to_plugin(plugin_id, body)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/git-mirror/probe", include_in_schema=True)
    async def _git_mirror_probe(
        body: GitMirrorProbeBody | None = None,
    ) -> JSONResponse:
        data = await probe_git_mirror(body)
        return JSONResponse({"ok": True, "data": data})
