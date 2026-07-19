from pathlib import Path

import pytest

from pallas.core.platform.multi_bot import claim as claim_mod


@pytest.fixture
def claim_plugin_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "draw"
    monkeypatch.setattr(
        claim_mod, "plugin_data_dir", lambda name, create=True: root if name == "draw" else tmp_path / name
    )
    return root


def test_only_one_bot_claims_same_message(claim_plugin_data: Path) -> None:
    gid, mid = 12345, 999
    assert claim_mod.try_claim_message_sync("draw", gid, mid, 111) is True
    assert claim_mod.try_claim_message_sync("draw", gid, mid, 222) is False
    assert claim_mod.try_claim_message_sync("draw", gid, mid, 111) is True


def test_different_message_id_both_claim(claim_plugin_data: Path) -> None:
    gid = 12345
    assert claim_mod.try_claim_message_sync("draw", gid, 1, 111) is True
    assert claim_mod.try_claim_message_sync("draw", gid, 2, 222) is True


def test_same_cross_bot_key_only_one_bot_claims(claim_plugin_data: Path) -> None:
    from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key

    gid, uid, raw, t = 12345, 999, "牛牛画画 测试", 100
    key = cross_bot_group_message_key(gid, uid, raw, t, use_plaintext=True)
    assert claim_mod.try_claim_message_sync("draw", gid, key, 111) is True
    assert claim_mod.try_claim_message_sync("draw", gid, key, 222) is False
    assert claim_mod.try_claim_message_sync("draw", gid, key, 111) is True


def test_prune_tolerates_deleted_claim_file(claim_plugin_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claims = claim_plugin_data / "message_claims"
    claims.mkdir(parents=True)
    kept = claims / "1_1.claim"
    vanished = claims / "1_2.claim"
    kept.write_text("111", encoding="utf-8")
    vanished.write_text("222", encoding="utf-8")

    real_stat = Path.stat

    def stat(self: Path, *args, **kwargs):
        if self == vanished:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    claim_mod._prune_old_claims("draw", max_files=500)


def test_maybe_prune_old_claims_throttled(claim_plugin_data: Path) -> None:
    claim_mod._last_prune_at.clear()
    claim_mod._claim_file_estimate.clear()
    calls: list[str] = []

    def spy(plugin: str, *, max_files: int = 500) -> int:
        calls.append(plugin)
        return 0

    claim_mod._prune_old_claims = spy  # type: ignore[method-assign]
    claim_mod._maybe_prune_old_claims("draw")
    claim_mod._maybe_prune_old_claims("draw")
    assert calls == ["draw"]


def test_maybe_prune_old_claims_forced_when_estimate_high(claim_plugin_data: Path) -> None:
    import time

    claim_mod._last_prune_at["draw"] = time.monotonic()
    claim_mod._claim_file_estimate["draw"] = claim_mod._PRUNE_FORCE_ENTRY_COUNT
    calls: list[str] = []

    def spy(plugin: str, *, max_files: int = 500) -> int:
        calls.append(plugin)
        return 100

    claim_mod._prune_old_claims = spy  # type: ignore[method-assign]
    claim_mod._maybe_prune_old_claims("draw")
    assert calls == ["draw"]
