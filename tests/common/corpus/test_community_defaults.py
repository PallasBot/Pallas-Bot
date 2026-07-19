from pallas.product.corpus.config import (
    auto_enroll_enabled,
    clear_corpus_config_cache,
    is_community_corpus_wanted,
)


def test_community_corpus_default_off(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.corpus.config.repo_env_raw_value",
        lambda _key: None,
    )
    clear_corpus_config_cache()
    assert is_community_corpus_wanted() is False
    clear_corpus_config_cache()


def test_corpus_auto_enroll_default_off(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.corpus.config.repo_env_raw_value",
        lambda _key: None,
    )
    clear_corpus_config_cache()
    assert auto_enroll_enabled() is False
    clear_corpus_config_cache()


def test_auto_enroll_auto_follows_community_enabled(monkeypatch):
    def fake_raw(key: str):
        if key == "PALLAS_CORPUS_AUTO_ENROLL":
            return "auto"
        if key == "PALLAS_CORPUS_COMMUNITY_ENABLED":
            return "true"
        return None

    monkeypatch.setattr("pallas.product.corpus.config.repo_env_raw_value", fake_raw)
    monkeypatch.setattr("pallas.product.corpus.config.community_manual_configured", lambda: False)
    monkeypatch.setattr("pallas.product.corpus.config.persisted_community_configured", lambda: False)
    clear_corpus_config_cache()
    assert auto_enroll_enabled() is True
    from pallas.product.corpus.config import corpus_composite_enabled

    assert corpus_composite_enabled() is True
    clear_corpus_config_cache()


def test_auto_enroll_auto_stays_off_when_community_off(monkeypatch):
    def fake_raw(key: str):
        if key == "PALLAS_CORPUS_AUTO_ENROLL":
            return "auto"
        if key == "PALLAS_CORPUS_COMMUNITY_ENABLED":
            return "false"
        return None

    monkeypatch.setattr("pallas.product.corpus.config.repo_env_raw_value", fake_raw)
    monkeypatch.setattr("pallas.product.corpus.config.community_manual_configured", lambda: False)
    clear_corpus_config_cache()
    assert auto_enroll_enabled() is False
    clear_corpus_config_cache()


def test_community_auto_mode_does_not_enable_from_persisted_enrollment(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.corpus.config.repo_env_raw_value",
        lambda key: "auto" if key == "PALLAS_CORPUS_COMMUNITY_ENABLED" else None,
    )
    monkeypatch.setattr("pallas.product.corpus.config.community_manual_configured", lambda: False)
    monkeypatch.setattr("pallas.product.corpus.config.persisted_community_configured", lambda: True)
    clear_corpus_config_cache()
    assert is_community_corpus_wanted() is False
    clear_corpus_config_cache()


def test_remote_corpus_find_true_maps_to_prefetch(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.corpus.webui_config.repo_env_raw_value",
        lambda key: "true" if key == "PALLAS_CORPUS_REMOTE_FIND_ENABLED" else None,
    )
    from pallas.product.corpus.webui_config import get_corpus_federation_webui_config

    try:
        assert get_corpus_federation_webui_config().remote_find_enabled == "prefetch"
    finally:
        clear_corpus_config_cache()


def test_corpus_federation_payload_community_default_false(monkeypatch):
    from pallas.console.webui.corpus_federation_section import corpus_federation_payload

    monkeypatch.setattr("pallas.product.corpus.webui_config.repo_env_raw_value", lambda _key: None)
    data = corpus_federation_payload()
    row = next(f for f in data["fields"] if f["name"] == "community_enabled")
    assert row["kind"] == "bool"
    assert row["current"] is False
