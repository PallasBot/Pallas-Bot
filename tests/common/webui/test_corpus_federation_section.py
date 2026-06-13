from src.console.webui.corpus_federation_section import (
    CORPUS_FEDERATION_SECTION_ID,
    apply_corpus_federation_patch,
    corpus_federation_payload,
)


def test_corpus_federation_payload_phase1(monkeypatch):
    monkeypatch.setattr("src.features.corpus.webui_config.repo_env_raw_value", lambda _key: None)
    data = corpus_federation_payload()
    assert data["plugin"] == CORPUS_FEDERATION_SECTION_ID
    assert data.get("hot_reload") is True
    names = {f["name"] for f in data["fields"]}
    assert "merge_order" in names
    assert "community_enabled" in names
    assert "remote_find_enabled" in names
    assert "fed_enabled" not in names
    assert "on_remote_failure" not in names
    assert "reply_messages_cap" in names
    assert "reply_answers_cap" in names
    assert "find_cache_ttl_sec" in names
    assert "reply_snapshot_ttl_sec" in names
    assert "reply_snapshot_max" in names
    assert "corpus_backfill_enabled" in names
    assert len(data["field_groups"]) == 4
    backfill_group = next(g for g in data["field_groups"] if g["id"] == "backfill")
    assert backfill_group["title"] == "历史语料同步"
    reply_perf_group = next(g for g in data["field_groups"] if g["id"] == "reply_perf")
    assert reply_perf_group["title"] == "接话性能（一般无需改）"
    community = next(f for f in data["fields"] if f["name"] == "community_enabled")
    assert community["kind"] == "bool"
    assert isinstance(community["current"], bool)
    merge_order = next(f for f in data["fields"] if f["name"] == "merge_order")
    assert merge_order["kind"] == "enum"
    assert merge_order["choices"] == ["local,community", "local"]
    assert merge_order["current"] == "local"
    auto_enroll = next(f for f in data["fields"] if f["name"] == "auto_enroll")
    assert auto_enroll["kind"] == "enum"
    assert auto_enroll["current"] == "false"
    remote_find = next(f for f in data["fields"] if f["name"] == "remote_find_enabled")
    assert remote_find["kind"] == "enum"
    assert remote_find["choices"] == ["auto", "false", "prefetch", "sync"]


def test_apply_corpus_federation_patch_writes_env(monkeypatch, tmp_path):
    from src.foundation.config import repo_settings as rs

    webui = tmp_path / "data" / "pallas_config" / "webui.json"
    webui.parent.mkdir(parents=True, exist_ok=True)
    webui.write_text('{"env": {}}', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)

    out = apply_corpus_federation_patch({"community_contribute": "false", "community_enabled": False})
    assert out["fields"]
    raw = webui.read_text(encoding="utf-8")
    assert "PALLAS_CORPUS_COMMUNITY_CONTRIBUTE" in raw
    assert "PALLAS_CORPUS_COMMUNITY_ENABLED" in raw


def test_apply_corpus_federation_patch_accepts_prefetch(monkeypatch, tmp_path):
    from src.foundation.config import repo_settings as rs

    webui = tmp_path / "data" / "pallas_config" / "webui.json"
    webui.parent.mkdir(parents=True, exist_ok=True)
    webui.write_text('{"env": {}}', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)

    out = apply_corpus_federation_patch({"remote_find_enabled": "prefetch"})
    remote_find = next(f for f in out["fields"] if f["name"] == "remote_find_enabled")

    assert remote_find["current"] == "prefetch"
    raw = webui.read_text(encoding="utf-8")
    assert '"PALLAS_CORPUS_REMOTE_FIND_ENABLED": "prefetch"' in raw


def test_apply_corpus_federation_patch_backfill(monkeypatch, tmp_path):
    from src.foundation.config import repo_settings as rs

    webui = tmp_path / "data" / "pallas_config" / "webui.json"
    webui.parent.mkdir(parents=True, exist_ok=True)
    webui.write_text('{"env": {}}', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)

    out = apply_corpus_federation_patch({
        "corpus_backfill_enabled": True,
        "corpus_backfill_batch_size": 20,
        "corpus_backfill_interval_sec": 1200,
        "corpus_backfill_max_per_minute": 30,
    })
    enabled = next(f for f in out["fields"] if f["name"] == "corpus_backfill_enabled")
    assert enabled["current"] is True
    raw = webui.read_text(encoding="utf-8")
    assert "PALLAS_CORPUS_BACKFILL_ENABLED" in raw
    assert "PALLAS_CORPUS_BACKFILL_BATCH_SIZE" in raw


def test_apply_corpus_federation_patch_reply_perf(monkeypatch, tmp_path):
    from src.foundation.config import repo_settings as rs

    webui = tmp_path / "data" / "pallas_config" / "webui.json"
    webui.parent.mkdir(parents=True, exist_ok=True)
    webui.write_text('{"env": {}}', encoding="utf-8")
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: webui)
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)

    out = apply_corpus_federation_patch({
        "reply_messages_cap": 32,
        "find_cache_ttl_sec": 60,
        "reply_snapshot_ttl_sec": 10,
        "reply_snapshot_max": 30000,
    })
    cap_field = next(f for f in out["fields"] if f["name"] == "reply_messages_cap")
    assert cap_field["current"] == 32
    raw = webui.read_text(encoding="utf-8")
    assert "PALLAS_CORPUS_REPLY_MESSAGES_CAP" in raw
    assert "PALLAS_CORPUS_FIND_CACHE_SEC" in raw
    assert "PALLAS_CORPUS_REPLY_SNAPSHOT_SEC" in raw
    assert "PALLAS_CORPUS_REPLY_SNAPSHOT_MAX" in raw


def test_apply_corpus_federation_patch_rejects_unknown():
    import pytest

    with pytest.raises(ValueError, match="未知配置项"):
        apply_corpus_federation_patch({"fed_enabled": "true"})


def test_corpus_reply_perf_default_answers_cap_is_128(monkeypatch):
    from src.features.corpus.reply_perf_config import (
        clear_corpus_reply_perf_config_cache,
        get_corpus_reply_perf_config,
    )

    monkeypatch.setattr(
        "src.features.corpus.reply_perf_config.repo_env_raw_value",
        lambda _key: None,
    )
    clear_corpus_reply_perf_config_cache()
    try:
        cfg = get_corpus_reply_perf_config()
        assert cfg.reply_answers_cap == 128
        assert cfg.reply_messages_cap == 16
    finally:
        clear_corpus_reply_perf_config_cache()
