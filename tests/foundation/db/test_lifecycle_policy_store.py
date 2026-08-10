import json
from pathlib import Path

import pytest

from pallas.core.foundation.db import lifecycle_policy_store
from pallas.core.foundation.db.lifecycle_models import LifecyclePolicy


@pytest.fixture
def settings_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data" / "pallas_config" / "webui.json"
    monkeypatch.setattr(lifecycle_policy_store, "repo_webui_settings_path", lambda: path)
    return path


def test_missing_settings_return_registry_defaults(settings_path: Path) -> None:
    policies = lifecycle_policy_store.load_lifecycle_policies()

    assert policies["message_history"] == LifecyclePolicy(False, 180, 40 * 1024**3)
    assert policies["llm_memory"] == LifecyclePolicy(False, None, None)


def test_save_preserves_unrelated_webui_settings(settings_path: Path) -> None:
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"env": {"LOG_LEVEL": "INFO"}, "plugin_config": {"x": 1}}),
        encoding="utf-8",
    )

    policies = lifecycle_policy_store.save_lifecycle_policies({
        "message_history": LifecyclePolicy(True, 60, 8 * 1024**3)
    })

    document = json.loads(settings_path.read_text(encoding="utf-8"))
    assert document["env"] == {"LOG_LEVEL": "INFO"}
    assert document["plugin_config"] == {"x": 1}
    assert document["database_lifecycle"]["policies"]["message_history"] == {
        "enabled": True,
        "retention_days": 60,
        "max_bytes": 8 * 1024**3,
    }
    assert policies["message_history"].retention_days == 60
    assert lifecycle_policy_store.load_lifecycle_policies()["message_history"].retention_days == 60


@pytest.mark.parametrize(
    ("dataset_id", "policy"),
    [
        ("unknown", LifecyclePolicy(True, 30, None)),
        ("message_history", LifecyclePolicy(True, 0, None)),
        ("message_history", LifecyclePolicy(True, 3651, None)),
        ("message_history", LifecyclePolicy(True, None, 1024)),
        ("message_history", LifecyclePolicy(True, None, 2 * 1024**4 + 1)),
        ("llm_memory", LifecyclePolicy(True, 30, None)),
        ("llm_memory", LifecyclePolicy(True, None, 16 * 1024**2)),
    ],
)
def test_invalid_policy_is_rejected(
    settings_path: Path,
    dataset_id: str,
    policy: LifecyclePolicy,
) -> None:
    with pytest.raises(ValueError, match="生命周期|retention_days|max_bytes|不支持"):
        lifecycle_policy_store.save_lifecycle_policies({dataset_id: policy})
