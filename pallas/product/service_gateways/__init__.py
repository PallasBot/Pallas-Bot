"""扩展服务连通探测注册表。"""

from pallas.product.service_gateways.collect import probe_all_connectivity, probe_all_connectivity_from_draft
from pallas.product.service_gateways.draft import draw_draft_from_values, maa_cfg_from_draft, sing_cfg_from_draft
from pallas.product.service_gateways.llm_probe import LLM_CATEGORY, probe_llm_service
from pallas.product.service_gateways.media_probe import (
    IMAGE_CATEGORY,
    MAA_CATEGORY,
    SING_CATEGORY,
    maa_hub_probe_note,
    probe_image_gateways,
    probe_maa_endpoints,
    probe_sing_server,
    sing_probe_urls,
)
from pallas.product.service_gateways.registry import (
    register_service_probe_provider,
    registered_service_probe_names,
    run_service_probes,
)

__all__ = [
    "IMAGE_CATEGORY",
    "LLM_CATEGORY",
    "MAA_CATEGORY",
    "SING_CATEGORY",
    "draw_draft_from_values",
    "maa_cfg_from_draft",
    "maa_hub_probe_note",
    "probe_all_connectivity",
    "probe_all_connectivity_from_draft",
    "probe_image_gateways",
    "probe_llm_service",
    "probe_maa_endpoints",
    "probe_sing_server",
    "register_service_probe_provider",
    "registered_service_probe_names",
    "run_service_probes",
    "sing_cfg_from_draft",
    "sing_probe_urls",
]
