"""服务网关通用配置段所涉环境变量字段名。"""

from __future__ import annotations

PALLAS_IMAGE_GATEWAY_FIELDS: frozenset[str] = frozenset({
    "pallas_image_primary_name",
    "pallas_image_base_url",
    "pallas_image_api_key",
    "pallas_image_model",
    "pallas_image_api_backends",
})

MAA_GATEWAY_FIELDS: frozenset[str] = frozenset({
    "maa_public_base_url",
    "maa_get_task_endpoint",
    "maa_report_status_endpoint",
    "maa_get_task_path",
    "maa_report_status_path",
})

SING_GATEWAY_FIELDS: frozenset[str] = frozenset({
    "sing_enable",
    "ai_server_host",
    "ai_server_port",
    "request_endpoint",
})

ALL_GATEWAY_FIELDS: frozenset[str] = PALLAS_IMAGE_GATEWAY_FIELDS | MAA_GATEWAY_FIELDS | SING_GATEWAY_FIELDS
