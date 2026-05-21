from pathlib import Path

import pytest

from src.common.multi_bot import claim as claim_mod


@pytest.fixture
def claim_plugin_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "pallas_image"
    monkeypatch.setattr(claim_mod, "plugin_data_dir", lambda name, create=True: root if name == "pallas_image" else tmp_path / name)
    return root


def test_only_one_bot_claims_same_message(claim_plugin_data: Path) -> None:
    gid, mid = 12345, 999
    assert claim_mod.try_claim_message_sync("pallas_image", gid, mid, 111) is True
    assert claim_mod.try_claim_message_sync("pallas_image", gid, mid, 222) is False
    assert claim_mod.try_claim_message_sync("pallas_image", gid, mid, 111) is True


def test_different_message_id_both_claim(claim_plugin_data: Path) -> None:
    gid = 12345
    assert claim_mod.try_claim_message_sync("pallas_image", gid, 1, 111) is True
    assert claim_mod.try_claim_message_sync("pallas_image", gid, 2, 222) is True


def test_same_cross_bot_key_only_one_bot_claims(claim_plugin_data: Path) -> None:
    from src.common.multi_bot.dedup import cross_bot_group_message_key

    gid, uid, raw, t = 12345, 999, "牛牛画画 测试", 100
    key = cross_bot_group_message_key(gid, uid, raw, t, use_plaintext=True)
    assert claim_mod.try_claim_message_sync("pallas_image", gid, key, 111) is True
    assert claim_mod.try_claim_message_sync("pallas_image", gid, key, 222) is False
    assert claim_mod.try_claim_message_sync("pallas_image", gid, key, 111) is True
