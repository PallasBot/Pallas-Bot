from packages.repeater.learn_runtime_config import (
    RepeaterLearnRuntimeConfig,
    get_repeater_learn_runtime_config,
)
from pallas.console.webui.env_sections import get_webui_env_section


def test_repeater_learn_common_config_section_removed():
    import pytest

    with pytest.raises(ValueError, match="未知 common-config"):
        get_webui_env_section("repeater_learn")


def test_repeater_learn_from_repeater_plugin_config(monkeypatch):
    from packages.repeater import config as repeater_cfg

    monkeypatch.setattr(
        repeater_cfg,
        "get_repeater_config",
        lambda: repeater_cfg.Config(learn_concurrency=8, learn_queue_max_size=512),
    )
    cfg = get_repeater_learn_runtime_config()
    assert cfg.learn_concurrency == 8
    assert cfg.learn_queue_max_size == 512
    assert RepeaterLearnRuntimeConfig.model_fields["learn_concurrency"].description
