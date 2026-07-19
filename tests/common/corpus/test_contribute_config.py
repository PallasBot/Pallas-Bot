def test_community_contribute_enabled_defaults_true(monkeypatch):
    from pallas.product.corpus.config import clear_corpus_config_cache, community_contribute_enabled

    monkeypatch.delenv("PALLAS_CORPUS_COMMUNITY_CONTRIBUTE", raising=False)
    monkeypatch.setattr(
        "pallas.product.corpus.config.setting_str",
        lambda name, default="": default if name == "PALLAS_CORPUS_COMMUNITY_CONTRIBUTE" else "",
    )
    monkeypatch.setattr("pallas.product.corpus.store.load_corpus_community_state", dict)
    clear_corpus_config_cache()
    assert community_contribute_enabled() is True


def test_community_contribute_respects_enroll_policy_false(monkeypatch):
    from pallas.product.corpus.config import clear_corpus_config_cache, community_contribute_enabled

    monkeypatch.delenv("PALLAS_CORPUS_COMMUNITY_CONTRIBUTE", raising=False)
    monkeypatch.setattr(
        "pallas.product.corpus.config.setting_str",
        lambda name, default="": default if name == "PALLAS_CORPUS_COMMUNITY_CONTRIBUTE" else "",
    )
    monkeypatch.setattr(
        "pallas.product.corpus.store.load_corpus_community_state",
        lambda: {"contribute": False, "corpus_token": "pc_x", "api_base": "https://x/v1/corpus"},
    )
    clear_corpus_config_cache()
    assert community_contribute_enabled() is False
