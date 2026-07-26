"""插件配置：LLM Provider 主线/备线网关 UI 声明。"""

from __future__ import annotations

from typing import Any, Literal


def ui_provider_gateway(
    *,
    mode: Literal["unified", "split"] = "unified",
    allow_manual: bool = False,
    capability: str | None = None,
    field: str | None = None,
    primary: dict[str, str] | None = None,
    backends: str | None = None,
    currency_field: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    label: str | None = None,
    group: str | None = None,
    extras: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """写入 ``Field(json_schema_extra=…)``，供 WebUI 渲染通用主/备线面板。

    - ``unified``：单 JSON 数组字段（``field``，缺省为该 Field 自身名由前端用 anchor 名）。
    - ``split``：主线散字段 + ``backends`` 备线数组（画画现网形状）。
    - ``allow_manual``：是否允许手填 base_url/api_key；默认仅沿用 Provider。
    """
    gateway: dict[str, Any] = {
        "mode": mode,
        "allow_manual": bool(allow_manual),
    }
    if capability:
        gateway["capability"] = str(capability).strip()
    if field:
        gateway["field"] = str(field).strip()
    if primary:
        gateway["primary"] = {str(k): str(v) for k, v in primary.items() if str(v).strip()}
    if backends:
        gateway["backends"] = str(backends).strip()
    if currency_field:
        gateway["currency_field"] = str(currency_field).strip()
    if title:
        gateway["title"] = str(title).strip()
    if subtitle:
        gateway["subtitle"] = str(subtitle).strip()
    if extras:
        gateway["extras"] = list(extras)

    out: dict[str, Any] = {
        "ui_widget": "provider_gateway",
        "ui_gateway": gateway,
    }
    if label:
        out["label"] = label
    if group:
        out["ui_group"] = group
    return out


def provider_gateway_bound_field_names(ui_gateway: dict[str, Any], *, anchor: str) -> list[str]:
    """面板托管的配置键（应从普通表单中隐藏）。"""
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        key = (name or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        names.append(key)

    mode = str(ui_gateway.get("mode") or "unified").strip().lower()
    if mode == "split":
        primary = ui_gateway.get("primary")
        if isinstance(primary, dict):
            for value in primary.values():
                add(str(value))
        add(str(ui_gateway.get("backends") or ""))
    else:
        add(str(ui_gateway.get("field") or anchor))
    add(str(ui_gateway.get("currency_field") or ""))
    return names
