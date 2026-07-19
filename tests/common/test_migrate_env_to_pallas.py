from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pallas.core.foundation.config import migrate_env_to_pallas as mig

if TYPE_CHECKING:
    from pathlib import Path


def test_inspect_no_legacy_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mig, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mig, "repo_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(mig, "repo_config_path", lambda: tmp_path / "config" / "pallas.toml")
    monkeypatch.setattr(mig, "repo_webui_settings_path", lambda: tmp_path / "data" / "pallas_config" / "webui.json")
    monkeypatch.setattr(mig, "nonebot_repo_dotenv_environment", lambda: "prod")

    data = mig.inspect_env_to_pallas_migration()
    assert data["show"] is False
    assert data["can_migrate"] is False


def test_apply_migrate_writes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mig, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mig, "repo_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(mig, "repo_config_path", lambda: tmp_path / "config" / "pallas.toml")
    monkeypatch.setattr(mig, "repo_webui_settings_path", lambda: tmp_path / "data" / "pallas_config" / "webui.json")
    monkeypatch.setattr(mig, "nonebot_repo_dotenv_environment", lambda: "prod")

    (tmp_path / ".env").write_text(
        "HOST=127.0.0.1\nPORT=8088\nSUPERUSERS=123\nFOO=bar\n",
        encoding="utf-8",
    )

    inspect = mig.inspect_env_to_pallas_migration()
    assert inspect["show"] is True
    assert inspect["can_migrate"] is True

    result = mig.apply_env_to_pallas_migration(force=False)
    assert result.webui_env_key_count == 1
    assert (tmp_path / "config" / "pallas.toml").is_file()
    assert (tmp_path / "data" / "pallas_config" / "webui.json").is_file()

    webui = (tmp_path / "data" / "pallas_config" / "webui.json").read_text(encoding="utf-8")
    assert "FOO" in webui


def test_apply_requires_force_when_targets_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mig, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mig, "repo_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(mig, "repo_config_path", lambda: tmp_path / "config" / "pallas.toml")
    monkeypatch.setattr(mig, "repo_webui_settings_path", lambda: tmp_path / "data" / "pallas_config" / "webui.json")
    monkeypatch.setattr(mig, "nonebot_repo_dotenv_environment", lambda: "prod")

    (tmp_path / ".env").write_text("HOST=1\n", encoding="utf-8")
    cfg = tmp_path / "config" / "pallas.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[bootstrap]\nhost = "old"\n', encoding="utf-8")

    with pytest.raises(mig.EnvToPallasMigrationError) as exc:
        mig.apply_env_to_pallas_migration(force=False)
    assert exc.value.status_code == 409

    mig.apply_env_to_pallas_migration(force=True)
    assert 'host = "1"' in cfg.read_text(encoding="utf-8")
