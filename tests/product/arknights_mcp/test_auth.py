from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from pallas.product.arknights_mcp.auth import CredentialStore, CredentialStoreError


def _issue_key(data_root: str) -> str:
    return CredentialStore(Path(data_root)).issue(label="parallel")[1]


def test_credentials_are_scoped_private_and_revocable(tmp_path: Path):
    store = CredentialStore(tmp_path)
    secret, key_id = store.issue(label="reader")

    assert secret.startswith("pmcp_")
    assert store.authenticate(secret).scopes == frozenset({"arknights:read", "prts:read"})
    assert store.authenticate("pls_" + secret.removeprefix("pmcp_")) is None
    listed = store.list()
    assert listed[0]["id"] == key_id
    assert listed[0]["label"] == "reader"
    assert listed[0]["scopes"] == ["arknights:read", "prts:read"]
    assert listed[0]["created_at"]

    stored = store.file_path.read_text(encoding="utf-8")
    assert secret not in stored
    assert "hash" in stored
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert store.file_path.stat().st_mode & 0o777 == 0o600

    restricted, restricted_id = store.issue(label="arknights only", scopes={"arknights:read"})
    assert store.authenticate(restricted).scopes == frozenset({"arknights:read"})
    assert store.revoke(restricted_id)
    assert store.authenticate(restricted) is None
    assert not store.revoke(restricted_id)


def test_corrupt_store_fails_closed_without_replacing_existing_bytes(tmp_path: Path):
    store = CredentialStore(tmp_path)
    store.file_path.parent.mkdir(parents=True)
    original = b"{invalid json"
    store.file_path.write_bytes(original)

    assert store.authenticate("pmcp_" + "A" * 43) is None
    with pytest.raises(CredentialStoreError):
        store.issue()
    assert store.file_path.read_bytes() == original


def test_store_with_unexpected_fields_fails_closed(tmp_path: Path):
    store = CredentialStore(tmp_path)
    secret, _ = store.issue()
    payload = json.loads(store.file_path.read_text(encoding="utf-8"))
    payload["keys"][0]["plaintext"] = secret
    store.file_path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.authenticate(secret) is None
    with pytest.raises(CredentialStoreError):
        store.issue()


def test_parallel_process_issuance_does_not_lose_keys(tmp_path: Path):
    with ProcessPoolExecutor(max_workers=6) as pool:
        key_ids = list(pool.map(_issue_key, [str(tmp_path)] * 24))

    assert len(set(key_ids)) == 24
    assert len(CredentialStore(tmp_path).list()) == 24
