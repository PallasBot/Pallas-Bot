"""WebUI「通用配置 → 联邦控制」：分组、三态选项与说明文案。"""

from __future__ import annotations

from typing import Any

from pydantic_core import PydanticUndefined

from src.console.webui.field_help import field_help, normalize_field_description
from src.features.control_plane.webui_config import (
    ControlPlaneWebuiConfig,
    get_control_plane_webui_config,
    repair_misplaced_federate_redis_env,
    setting_str,
)
from src.features.corpus.config import parse_tristate
from src.foundation.config.dotenv import env_value_to_str
from src.foundation.config.repo_settings import (
    remove_repo_settings_keys,
    repo_env_raw_value,
    upsert_repo_settings_items,
)

CONTROL_PLANE_SECTION_ID = "control_plane"
CONTROL_PLANE_TITLE = "联邦控制"

_TRI_CHOICES = ["auto", "true", "false"]

_FIELD_LABELS: dict[str, str] = {
    "enabled": "控制面总开关",
    "instance_secret": "入池密钥",
    "bootstrap_url": "中心配置地址",
    "federate_id": "联邦池编号",
    "federate_ingress_enabled": "重复消息去重",
    "ingress_bypass_unified": "单进程命令直通",
    "coord_redis_url": "去重服务器地址",
    "federate_redis_prefix": "去重键前缀",
    "claim_ttl_sec": "去重保留秒数",
}

_FIELD_TO_ENV: dict[str, str] = {
    "enabled": "PALLAS_CONTROL_PLANE_ENABLED",
    "bootstrap_url": "PALLAS_CONTROL_PLANE_BOOTSTRAP_URL",
    "instance_secret": "PALLAS_INSTANCE_SECRET",
    "federate_id": "PALLAS_FEDERATE_ID",
    "federate_ingress_enabled": "PALLAS_FEDERATE_INGRESS_ENABLED",
    "ingress_bypass_unified": "PALLAS_FEDERATE_INGRESS_BYPASS_UNIFIED",
    "federate_redis_prefix": "PALLAS_FEDERATE_REDIS_PREFIX",
    "coord_redis_url": "PALLAS_FEDERATE_COORD_REDIS_URL",
    "claim_ttl_sec": "PALLAS_FEDERATE_CLAIM_TTL_SEC",
}

_FIELD_ORDER: tuple[str, ...] = (
    "enabled",
    "instance_secret",
    "bootstrap_url",
    "federate_id",
    "federate_ingress_enabled",
    "ingress_bypass_unified",
    "coord_redis_url",
    "federate_redis_prefix",
    "claim_ttl_sec",
)


def _shard_redis_hint() -> str:
    try:
        shard = str(repo_env_raw_value("REDIS_URL") or "").strip()
    except Exception:
        shard = ""
    if shard:
        return f"当前分片用的 Redis 是 {shard}，不要填到本项。"
    return "分片模式下的 REDIS_URL 与本项无关，勿混填。"


def _enabled_raw() -> str:
    raw = setting_str("PALLAS_CONTROL_PLANE_ENABLED", "true").strip().lower()
    return raw if raw in _TRI_CHOICES else "true"


def _field_row(key: str, cur: Any) -> dict[str, Any]:
    f = ControlPlaneWebuiConfig.model_fields[key]
    default_value = None if f.default is PydanticUndefined else f.default
    row: dict[str, Any] = {
        "name": key,
        "label": _FIELD_LABELS.get(key, key),
        "kind": "string",
        "required": bool(f.is_required()),
        "description": normalize_field_description(str(f.description or "")),
        "env_key": _FIELD_TO_ENV[key],
        "default": default_value,
        "current": cur,
    }
    if key == "enabled":
        row["kind"] = "enum"
        row["choices"] = _TRI_CHOICES
        row["current"] = _enabled_raw()
        row["description"] = field_help(
            "是否向社区中心自动领取联邦配置",
            "一般选「自动」或「开启」；关闭后不再向中心拉取配置",
            "默认已开启；仍需填写下方的入池密钥",
        )
    elif key == "instance_secret":
        row["description"] = field_help(
            "加入社区联邦池的密钥",
            "打开控制台「统计与语料」，在「社区联邦」面板复制后粘贴到此处",
            "与共享语料口令、在线统计无关；请勿泄露",
        )
    elif key == "bootstrap_url":
        row["description"] = field_help(
            "向中心拉取联邦配置的网址",
            "留空即可，程序会按统计主站与备站自动选择",
            "仅自建中心或特殊网络时再填写完整地址",
        )
    elif key == "federate_id":
        row["description"] = field_help(
            "所属联邦池编号",
            "可留空，填写密钥并由中心下发后会自动写入",
            "多套牛牛要共用同一编号，跨机去重才会生效",
        )
    elif key == "federate_ingress_enabled":
        row["kind"] = "enum"
        row["choices"] = _TRI_CHOICES
        raw = str(cur or "auto").strip().lower()
        row["current"] = raw if raw in _TRI_CHOICES else "auto"
        row["description"] = field_help(
            "避免多套牛牛对同一条群消息各回复一遍",
            "选「自动」：已入池且去重服务可用时开启",
            "单进程与分片模式都会经过此去重",
        )
    elif key == "ingress_bypass_unified":
        row["kind"] = "bool"
        row["current"] = bool(cur)
        row["description"] = field_help(
            "单进程模式下命令是否跳过去重门控",
            "开启后命令响应更快，但不再参与跨机去重",
            "默认关闭；仅本地排障或你明确不需要去重时再开",
        )
    elif key == "coord_redis_url":
        row["description"] = field_help(
            "各套牛牛共用的去重服务器地址",
            "一般留空，由中心自动下发；调试时可手填",
            _shard_redis_hint(),
        )
    elif key == "federate_redis_prefix":
        row["description"] = field_help(
            "去重记录在服务器里的键名前缀",
            "一般留空，由中心或池编号自动生成",
            "与分片协调用的键前缀不是一回事",
        )
    elif key == "claim_ttl_sec":
        row["kind"] = "number"
        row["current"] = int(cur or 86400)
        row["description"] = field_help(
            "去重标记在服务器上保留多少秒",
            "越长越能避免重复抢答；越短则旧记录释放更快",
            "未手填时跟随中心下发；常见为 7200 或 86400 秒",
        )
    return row


def control_plane_payload(*, current_values: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = get_control_plane_webui_config()
    data = cfg.model_dump(mode="python")
    data["enabled"] = _enabled_raw()
    if current_values is not None:
        data = {**data, **current_values}
    fields = [_field_row(k, data.get(k)) for k in _FIELD_ORDER]
    return {
        "plugin": CONTROL_PLANE_SECTION_ID,
        "module": "src.features.control_plane",
        "hot_reload": True,
        "fields": fields,
        "field_groups": [
            {
                "id": "join",
                "title": "入池与中心配置",
                "field_names": ["enabled", "instance_secret", "bootstrap_url"],
            },
            {
                "id": "pool",
                "title": "联邦池与消息去重",
                "field_names": ["federate_id", "federate_ingress_enabled", "ingress_bypass_unified"],
            },
            {
                "id": "redis",
                "title": "去重服务器（进阶）",
                "field_names": ["coord_redis_url", "federate_redis_prefix", "claim_ttl_sec"],
            },
        ],
    }


def _coerce_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    raise ValueError(f"{field_name} 须为 true 或 false")


def _coerce_int(value: Any, *, field_name: str, min_v: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as e:
        raise ValueError(f"{field_name} 须为整数") from e
    if parsed < min_v:
        raise ValueError(f"{field_name} 须大于等于 {min_v}")
    return parsed


def apply_control_plane_patch(patch: dict[str, Any]) -> dict[str, Any]:
    allowed = set(_FIELD_ORDER)
    for k in patch:
        if k not in allowed:
            raise ValueError(f"未知配置项: {k}")
    cfg = get_control_plane_webui_config()
    merged = cfg.model_dump(mode="python")
    merged["enabled"] = _enabled_raw()
    merged.update(patch)
    if "enabled" in patch:
        en = str(patch["enabled"]).strip().lower()
        if en not in _TRI_CHOICES:
            raise ValueError("enabled 须为 auto、true 或 false")
        merged["enabled"] = en
    if "federate_ingress_enabled" in patch:
        ing = str(patch["federate_ingress_enabled"]).strip().lower()
        if ing not in _TRI_CHOICES:
            raise ValueError("federate_ingress_enabled 须为 auto、true 或 false")
        merged["federate_ingress_enabled"] = ing
    if "ingress_bypass_unified" in patch:
        merged["ingress_bypass_unified"] = _coerce_bool(
            patch["ingress_bypass_unified"],
            field_name="ingress_bypass_unified",
        )
    if "claim_ttl_sec" in patch:
        merged["claim_ttl_sec"] = _coerce_int(patch["claim_ttl_sec"], field_name="claim_ttl_sec", min_v=60)

    enabled_bool = parse_tristate(str(merged["enabled"]), default=True) is not False
    validated = ControlPlaneWebuiConfig(
        enabled=enabled_bool,
        bootstrap_url=str(merged.get("bootstrap_url") or ""),
        instance_secret=str(merged.get("instance_secret") or ""),
        federate_id=str(merged.get("federate_id") or ""),
        federate_ingress_enabled=str(merged.get("federate_ingress_enabled") or "auto"),
        ingress_bypass_unified=bool(merged.get("ingress_bypass_unified")),
        federate_redis_prefix=str(merged.get("federate_redis_prefix") or ""),
        coord_redis_url=str(merged.get("coord_redis_url") or ""),
        claim_ttl_sec=int(merged.get("claim_ttl_sec") or 86400),
    ).model_dump(mode="python")

    items: dict[str, str] = {}
    if "enabled" in patch:
        items["PALLAS_CONTROL_PLANE_ENABLED"] = str(merged["enabled"])
    for k in patch:
        if k == "enabled":
            continue
        env_key = _FIELD_TO_ENV[k]
        items[env_key] = env_value_to_str(validated[k])
    if "coord_redis_url" in patch and not str(validated.get("coord_redis_url") or "").strip():
        items["PALLAS_FEDERATE_COORD_REDIS_URL"] = ""

    upsert_repo_settings_items(items)
    if "coord_redis_url" in patch and not str(validated.get("coord_redis_url") or "").strip():
        remove_repo_settings_keys(["PALLAS_FEDERATE_COORD_REDIS_URL"])
    repair_misplaced_federate_redis_env()

    try:
        from nonebot import logger

        from src.features.control_plane.bootstrap_client import (
            clear_bootstrap_runtime_caches,
            refresh_control_plane_bootstrap,
        )
        from src.features.control_plane.config import clear_control_plane_config_cache
        from src.features.control_plane.webui_config import clear_control_plane_webui_config_cache
        from src.platform.federate.config import clear_federate_config_cache

        clear_control_plane_webui_config_cache()
        clear_control_plane_config_cache()
        clear_federate_config_cache()
        clear_bootstrap_runtime_caches()
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(refresh_control_plane_bootstrap(force=True))
        except RuntimeError:
            asyncio.run(refresh_control_plane_bootstrap(force=True))
        logger.info("control_plane: WebUI 已热重载并刷新 bootstrap")
    except Exception as e:
        from nonebot import logger

        logger.warning("control_plane hot reload failed: {}", e)

    out = validated.copy()
    out["enabled"] = str(merged.get("enabled") or _enabled_raw())
    return control_plane_payload(current_values=out)
