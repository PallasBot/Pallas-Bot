from src.common.service_probe import ServiceProbeResult
from src.plugins.pallas_image.config import Config, ImageApiBackend, ImageGenSettings
from src.plugins.pallas_image.gateway_probe import (
    IMAGE_PROBE_CATEGORY,
    backend_display_site,
    backend_site_name,
    format_gateway_status_lines,
    format_gateway_status_text,
    models_probe_urls,
)


def test_backend_site_name() -> None:
    assert backend_site_name(1) == "备线1"
    assert backend_site_name(2) == "备线2"


def test_backend_display_site_uses_custom_name() -> None:
    backend = ImageApiBackend(
        base_url="https://a/",
        api_key="k",
        model="m",
        label="primary",
        name="我的主站",
    )
    assert backend_display_site(backend, 1) == "我的主站"


def test_models_probe_urls() -> None:
    backend = ImageApiBackend(
        base_url="https://api.example.com/v1",
        api_key="sk",
        model="m",
        label="primary",
    )
    urls = models_probe_urls(backend)
    assert urls == ["https://api.example.com/v1/models"]


def test_format_gateway_status_lines() -> None:
    results = [
        ServiceProbeResult(IMAGE_PROBE_CATEGORY, "主站", True, 120, 200, None),
        ServiceProbeResult(IMAGE_PROBE_CATEGORY, "备线1", False, None, 401, None),
        ServiceProbeResult(IMAGE_PROBE_CATEGORY, "备线2", False, None, None, "超时"),
    ]
    lines = format_gateway_status_lines(results)
    assert lines[0] == "牛牛画画 主站：120ms"
    assert lines[1] == "     备线1：HTTP 401"
    assert lines[2] == "     备线2：超时"
    assert format_gateway_status_text(results) == "\n".join(lines)


def test_api_backends_includes_primary_and_fallback() -> None:
    cfg = Config(
        pallas_image_base_url="https://a.example/v1",
        pallas_image_api_key="sk-a",
        pallas_image_model="m1",
        pallas_image_api_backends=[{"base_url": "https://b.example/v1", "api_key": "sk-b"}],
    )
    backends = ImageGenSettings(cfg).api_backends()
    assert len(backends) == 2
    assert backends[0].label == "primary"
    assert backends[1].label == "fallback-0"
