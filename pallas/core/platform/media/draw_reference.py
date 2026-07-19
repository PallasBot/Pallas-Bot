"""draw 参考图下载选项（由插件 config 构造，避免 import 插件包 __init__）。"""

from __future__ import annotations

from typing import Any

from pallas.core.platform.media.reference_resolve import ReferenceDownloadOptions


def draw_reference_download_options(cfg: Any) -> ReferenceDownloadOptions:
    return ReferenceDownloadOptions(
        user_agent=cfg.http_user_agent,
        http_transport=cfg.http_transport,
        tls_impersonate=cfg.tls_impersonate,
        ref_download_timeout=cfg.ref_download_timeout,
        tls_verify=getattr(cfg, "tls_verify", True),
        http_ca_bundle=getattr(cfg, "http_ca_bundle", ""),
    )
