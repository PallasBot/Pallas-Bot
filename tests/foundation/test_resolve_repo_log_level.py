from pallas.core.foundation.logging import resolve_repo_log_level


def test_resolve_repo_log_level_default(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda _name: None,
    )
    assert resolve_repo_log_level() == "INFO"


def test_resolve_repo_log_level_from_env(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda name: "debug" if name == "LOG_LEVEL" else None,
    )
    assert resolve_repo_log_level() == "DEBUG"
