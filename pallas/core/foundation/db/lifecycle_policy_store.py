"""Persistence and validation for database lifecycle policies."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from typing import Any

from pallas.core.foundation.config.repo_settings import (
    _atomic_write_text,
    repo_webui_settings_path,
)

from .lifecycle_models import LifecyclePolicy
from .lifecycle_registry import DATASETS

MIN_MAX_BYTES = 16 * 1024**2
MAX_MAX_BYTES = 2 * 1024**4
_write_lock = threading.Lock()


def validate_lifecycle_policy(dataset_id: str, policy: LifecyclePolicy) -> None:
    definition = DATASETS.get(dataset_id)
    if definition is None:
        raise ValueError(f"未知生命周期数据集: {dataset_id}")
    if policy.retention_days is not None and not 1 <= policy.retention_days <= 3650:
        raise ValueError("retention_days 必须在 1..3650 之间")
    if policy.max_bytes is not None and not MIN_MAX_BYTES <= policy.max_bytes <= MAX_MAX_BYTES:
        raise ValueError("max_bytes 必须在 16 MiB..2 TiB 之间")
    if policy.retention_days is not None and not definition.supports_retention:
        raise ValueError(f"{definition.label} 不支持按天数清理")
    if policy.max_bytes is not None and not definition.supports_max_bytes:
        raise ValueError(f"{definition.label} 不支持存储上限")


def load_lifecycle_policies() -> dict[str, LifecyclePolicy]:
    document = read_document()
    section = document.get("database_lifecycle")
    raw_policies = section.get("policies") if isinstance(section, dict) else None
    policies = {dataset_id: definition.default_policy for dataset_id, definition in DATASETS.items()}
    if not isinstance(raw_policies, dict):
        return policies
    for dataset_id, raw in raw_policies.items():
        if dataset_id not in DATASETS or not isinstance(raw, dict):
            continue
        try:
            policy = LifecyclePolicy(
                enabled=bool(raw["enabled"]),
                retention_days=optional_int(raw.get("retention_days")),
                max_bytes=optional_int(raw.get("max_bytes")),
            )
            validate_lifecycle_policy(dataset_id, policy)
        except (KeyError, TypeError, ValueError):
            continue
        policies[dataset_id] = policy
    return policies


def save_lifecycle_policies(updates: dict[str, LifecyclePolicy]) -> dict[str, LifecyclePolicy]:
    for dataset_id, policy in updates.items():
        validate_lifecycle_policy(dataset_id, policy)

    with _write_lock:
        policies = load_lifecycle_policies()
        policies.update(updates)
        document = read_document(strict=True)
        section = document.get("database_lifecycle")
        if not isinstance(section, dict):
            section = {}
            document["database_lifecycle"] = section
        section["policies"] = {dataset_id: asdict(policy) for dataset_id, policy in policies.items()}
        _atomic_write_text(
            repo_webui_settings_path(),
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        )
    return policies


def read_document(*, strict: bool = False) -> dict[str, Any]:
    path = repo_webui_settings_path()
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if strict:
            raise ValueError("webui.json 无法读取或格式无效") from None
        return {}
    if not isinstance(document, dict):
        if strict:
            raise ValueError("webui.json 顶层必须是对象")
        return {}
    return document


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError
    return int(value)
