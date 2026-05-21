import pytest
from fastapi import FastAPI

from src.plugins.maa import config as maa_cfg_mod
from src.plugins.maa import endpoints as ep_mod
from src.plugins.maa import http_api as http_api_mod
from src.plugins.maa import http_routes as routes_mod
from src.plugins.maa.config import Config


def patch_maa_config(monkeypatch: pytest.MonkeyPatch, cfg: Config) -> None:
    def getter() -> Config:
        return cfg

    for mod in (maa_cfg_mod, ep_mod, http_api_mod):
        monkeypatch.setattr(mod, "get_maa_config", getter)


def test_resolve_from_public_base(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(
        maa_public_base_url="https://nb.example.com",
        maa_get_task_path="/maa/getTask",
        maa_report_status_path="/maa/reportStatus",
    )
    patch_maa_config(monkeypatch, cfg)
    ep = ep_mod.resolve_maa_http_endpoints()
    assert ep.get_task_url == "https://nb.example.com/maa/getTask"
    assert ep.report_status_url == "https://nb.example.com/maa/reportStatus"
    assert ep.inferred_base is False


def test_resolve_full_endpoint_override(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(
        maa_get_task_endpoint="https://a.example/get",
        maa_report_status_endpoint="https://b.example/report",
    )
    patch_maa_config(monkeypatch, cfg)
    ep = ep_mod.resolve_maa_http_endpoints()
    assert ep.get_task_url == "https://a.example/get"
    assert ep.report_status_url == "https://b.example/report"
    assert ep.inferred_base is False


def test_format_help_contains_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(maa_public_base_url="https://nb.example.com")
    patch_maa_config(monkeypatch, cfg)
    text = ep_mod.format_maa_http_setup_help()
    assert "https://nb.example.com/maa/getTask" in text
    assert "https://nb.example.com/maa/reportStatus" in text


def test_resolve_probe_uses_process_base_on_sharded_worker_without_public_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = Config(
        maa_get_task_path="/maa/getTask",
        maa_report_status_path="/maa/reportStatus",
    )
    patch_maa_config(monkeypatch, cfg)
    monkeypatch.setattr("src.common.shard.registry.config.is_sharding_active", lambda: True)
    monkeypatch.setattr("src.common.bot_runtime.roles.is_sharded_worker", lambda: True)

    class _DConf:
        host = "0.0.0.0"
        port = 8092

    monkeypatch.setattr(ep_mod, "get_driver", lambda: type("D", (), {"config": _DConf()})())

    ep = ep_mod.resolve_maa_probe_http_endpoints()
    assert ep.get_task_url == "http://127.0.0.1:8092/maa/getTask"
    assert ep.report_status_url == "http://127.0.0.1:8092/maa/reportStatus"


def test_maa_public_http_base_uses_hub_when_sharded(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config()
    monkeypatch.setattr("src.common.shard.registry.config.is_sharding_active", lambda: True)

    class _S:
        ws_host = "127.0.0.1"
        hub_port = 8088

    monkeypatch.setattr("src.common.shard.registry.config.get_shard_registry_settings", lambda: _S())
    base, inferred = ep_mod.maa_public_http_base(cfg)
    assert base == "http://127.0.0.1:8088"
    assert inferred is True


def test_probe_uses_process_url_on_sharded_worker_even_with_public_base(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(maa_public_base_url="https://hub.example.com")
    patch_maa_config(monkeypatch, cfg)
    monkeypatch.setattr("src.common.shard.registry.config.is_sharding_active", lambda: True)
    monkeypatch.setattr("src.common.bot_runtime.roles.is_sharded_worker", lambda: True)

    class _DConf:
        host = "0.0.0.0"
        port = 8091

    monkeypatch.setattr(ep_mod, "get_driver", lambda: type("D", (), {"config": _DConf()})())
    ep = ep_mod.resolve_maa_probe_http_endpoints(cfg)
    assert ep.get_task_url == "http://127.0.0.1:8091/maa/getTask"


def test_resolve_probe_keeps_public_base_when_unified(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(maa_public_base_url="https://nb.example.com")
    patch_maa_config(monkeypatch, cfg)
    monkeypatch.setattr(
        "src.common.shard.registry.config.is_sharding_active",
        lambda: False,
    )
    ep = ep_mod.resolve_maa_probe_http_endpoints()
    assert ep.get_task_url == "https://nb.example.com/maa/getTask"


def test_remount_http_routes_on_path_change(monkeypatch: pytest.MonkeyPatch) -> None:
    routes_mod._mounted_paths = frozenset()  # noqa: SLF001
    app = FastAPI()
    cfg_a = Config(maa_get_task_path="/maa/getTask", maa_report_status_path="/maa/reportStatus")
    cfg_b = Config(maa_get_task_path="/custom/get", maa_report_status_path="/custom/report")

    patch_maa_config(monkeypatch, cfg_a)
    routes_mod.remount_maa_http_routes(app)
    paths_first = {getattr(r, "path", None) for r in app.router.routes}
    assert "/maa/getTask" in paths_first
    assert "/maa/reportStatus" in paths_first

    patch_maa_config(monkeypatch, cfg_b)
    routes_mod.remount_maa_http_routes(app)
    paths_second = {getattr(r, "path", None) for r in app.router.routes}
    assert "/custom/get" in paths_second
    assert "/custom/report" in paths_second
    assert "/maa/getTask" not in paths_second
