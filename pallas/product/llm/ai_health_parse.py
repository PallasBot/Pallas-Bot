from __future__ import annotations

from typing import Any


def health_section(body: object, key: str) -> dict[str, Any] | None:
    if not isinstance(body, dict):
        return None
    section = body.get(key)
    return section if isinstance(section, dict) else None


def llm_health_runtime_detail(body: object) -> str | None:
    llm = health_section(body, "llm")
    if not llm:
        return None
    parts: list[str] = []
    mode = str(llm.get("provider_mode") or "").strip()
    if mode:
        parts.append(f"模式 {mode}")
    cfg_err = str(llm.get("configuration_error") or "").strip()
    if cfg_err:
        parts.append(f"配置 {cfg_err}")
    elif llm.get("configuration_ok") is False:
        parts.append("配置异常")
    local_ok = llm.get("local_reachable")
    remote_ok = llm.get("remote_reachable")
    if local_ok is not None or remote_ok is not None:
        local_text = "可达" if local_ok else "不可达" if local_ok is False else "未知"
        remote_text = "可达" if remote_ok else "不可达" if remote_ok is False else "未知"
        parts.append(f"local {local_text} / remote {remote_text}")
    return " · ".join(parts) if parts else None


def llm_health_configuration_ok(body: object) -> bool | None:
    llm = health_section(body, "llm")
    if not llm or "configuration_ok" not in llm:
        return None
    return bool(llm.get("configuration_ok"))


def llm_health_circuit(body: object) -> dict[str, Any] | None:
    llm = health_section(body, "llm")
    if not llm:
        return None
    circuit_state = str(llm.get("circuit_state") or "").strip().lower() or None
    recent = llm.get("recent_failure_class")
    return {
        "circuit_state": circuit_state,
        "consecutive_failures": int(llm.get("consecutive_failures") or 0),
        "recent_failure_class": str(recent).strip() if recent else None,
        "health_state": str(llm.get("health_state") or "").strip().lower() or None,
        "degraded_state": str(llm.get("degraded_state") or "").strip().lower() or None,
    }


def image_health_circuit(body: object) -> dict[str, Any] | None:
    image = health_section(body, "image")
    if not image:
        return None
    backends = image.get("backends")
    backend: dict[str, Any] = {}
    if isinstance(backends, list) and backends and isinstance(backends[0], dict):
        backend = backends[0]
    circuit_state = str(backend.get("circuit_state") or "").strip().lower() or None
    recent = backend.get("recent_failure_class")
    return {
        "circuit_state": circuit_state,
        "consecutive_failures": int(backend.get("consecutive_failures") or 0),
        "recent_failure_class": str(recent).strip() if recent else None,
        "health_state": str(image.get("health_state") or "").strip().lower() or None,
        "degraded_state": str(image.get("degraded_state") or "").strip().lower() or None,
    }


def capability_health_circuit(body: object, capability_id: str) -> dict[str, Any] | None:
    section = health_section(body, "media_tasks")
    if not section:
        return None
    target = str(capability_id or "").strip()
    if not target:
        return None
    raw_caps = section.get("capabilities")
    if isinstance(raw_caps, list):
        for item in raw_caps:
            if not isinstance(item, dict):
                continue
            if str(item.get("capability") or "").strip() != target:
                continue
            circuit_state = str(item.get("circuit_state") or "").strip().lower() or None
            recent = item.get("recent_failure_class")
            return {
                "capability": target,
                "circuit_state": circuit_state,
                "consecutive_failures": int(item.get("consecutive_failures") or 0),
                "recent_failure_class": str(recent).strip() if recent else None,
                "health_state": str(item.get("health_state") or "").strip().lower() or None,
            }
    if str(section.get("capability") or "").strip() == target:
        circuit_state = str(section.get("circuit_state") or "").strip().lower() or None
        recent = section.get("recent_failure_class")
        return {
            "capability": target,
            "circuit_state": circuit_state,
            "consecutive_failures": int(section.get("consecutive_failures") or 0),
            "recent_failure_class": str(recent).strip() if recent else None,
            "health_state": str(section.get("health_state") or "").strip().lower() or None,
        }
    return None


def parse_media_tasks(body: object) -> dict[str, Any] | None:
    section = health_section(body, "media_tasks")
    if not section:
        return None
    parsed: dict[str, Any] = {
        "queue_depth": int(section.get("queue_depth") or 0),
        "active_tasks": int(section.get("active_tasks") or 0),
        "total_tasks": int(section.get("total_tasks") or 0),
    }
    for key in ("health_state", "degraded_state", "circuit_state", "recent_failure_class"):
        raw = section.get(key)
        if raw is not None and str(raw).strip():
            parsed[key] = str(raw).strip()
    raw_caps = section.get("capabilities")
    if isinstance(raw_caps, list):
        capabilities: list[dict[str, int | str]] = []
        for item in raw_caps:
            if not isinstance(item, dict):
                continue
            capability = str(item.get("capability") or "").strip()
            if not capability:
                continue
            cap_row: dict[str, int | str] = {
                "capability": capability,
                "queue_depth": int(item.get("queue_depth") or 0),
                "active_tasks": int(item.get("active_tasks") or 0),
            }
            cap_health = item.get("health_state")
            if cap_health is not None and str(cap_health).strip():
                cap_row["health_state"] = str(cap_health).strip()
            capabilities.append(cap_row)
        if capabilities:
            parsed["capabilities"] = capabilities
    return parsed


def llm_health_summary(body: object) -> dict[str, Any] | None:
    llm = health_section(body, "llm")
    if not llm:
        return None
    summary: dict[str, Any] = {}
    circuit = llm_health_circuit(body)
    if circuit:
        if circuit.get("consecutive_failures"):
            summary["consecutive_failures"] = int(circuit["consecutive_failures"])
    for key in ("health_state", "degraded_state", "circuit_state", "recent_failure_class"):
        raw = llm.get(key)
        if raw is not None and str(raw).strip():
            summary[key] = str(raw).strip()
    provider_status = llm.get("provider_status")
    if isinstance(provider_status, list):
        rows: list[dict[str, Any]] = []
        for item in provider_status:
            if not isinstance(item, dict):
                continue
            row = {
                "id": str(item.get("id") or "").strip(),
                "kind": str(item.get("kind") or "").strip(),
                "enabled": bool(item.get("enabled")),
                "configured": bool(item.get("configured")),
                "reachable": item.get("reachable"),
                "health_state": str(item.get("health_state") or "").strip() or None,
                "circuit_state": str(item.get("circuit_state") or "").strip() or None,
            }
            if row["id"]:
                rows.append(row)
        if rows:
            summary["provider_status"] = rows
    return summary or None


def tts_health_summary(body: object) -> dict[str, Any] | None:
    tts = health_section(body, "tts")
    if not tts:
        return None
    summary: dict[str, Any] = {}
    for key in ("capability", "health_state", "degraded_state", "circuit_state", "celery_enabled"):
        if key in tts:
            summary[key] = tts.get(key)
    return summary or None
