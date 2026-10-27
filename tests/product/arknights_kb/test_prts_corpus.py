from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import sys
import threading
from operator import itemgetter

import pytest

from pallas.product.arknights_kb import prts_corpus


def _write_gzip_jsonl(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _installed_fixture(tmp_path):
    data_dir = tmp_path / "prts_corpus"
    release_dir = data_dir / "releases" / "r1" / "references"
    doc = {
        "document_id": "client:references:timeline",
        "display_title": "泰拉年表",
        "document_type": "reference",
        "document_kind": "reference",
        "source_ref_prefix": "client_data:references:timeline",
    }
    _write_gzip_jsonl(
        release_dir / "shards/00000.jsonl.gz",
        [{"document": doc, "lines": [{"line_number": 1, "speaker_raw": "", "text": "孤星事件"}]}],
    )
    _write_gzip_jsonl(
        release_dir / "catalog/documents.jsonl.gz",
        [{"document": doc, "shard_path": "shards/00000.jsonl.gz", "record_index": 0}],
    )
    (release_dir / "pack-manifest.json").write_text(
        json.dumps({
            "pack_id": "references",
            "document_catalog": {"path": "catalog/documents.jsonl.gz"},
            "shards": [{"path": "shards/00000.jsonl.gz"}],
        }),
        encoding="utf-8",
    )
    (data_dir / "releases/current.json").write_text(
        json.dumps({"release_id": "r1", "data_version": "a" * 64, "packs": ["references"]}),
        encoding="utf-8",
    )
    return data_dir


def test_store_search_read_and_source_refs(tmp_path) -> None:
    store = prts_corpus.CorpusStore(_installed_fixture(tmp_path))

    found = store.search("孤星", pack_ids=["references"])
    assert found["count"] == 1
    assert found["items"][0]["title"] == "泰拉年表"
    read = store.read(document_uid=found["items"][0]["document_uid"])
    assert read["lines"][0]["text"] == "孤星事件"
    assert read["lines"][0]["source_ref"] == "client_data:references:timeline:L1"


def test_read_rejects_documents_outside_allowed_pack_scope(tmp_path) -> None:
    store = prts_corpus.CorpusStore(_installed_fixture(tmp_path))

    with pytest.raises(prts_corpus.CorpusNotFoundError):
        store.read(document_uid=prts_corpus._document_uid("client:references:timeline"), pack_ids=[])


@pytest.mark.parametrize("release_id", ["../escape", "/tmp/escape", "a/b", "..", ""])
def test_release_id_path_traversal_rejected(tmp_path, release_id: str) -> None:
    with pytest.raises(prts_corpus.CorpusError):
        prts_corpus._safe_release_dir(tmp_path, release_id)


def test_asset_symlink_rejected(tmp_path) -> None:
    base = tmp_path / "pack"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(prts_corpus.CorpusError):
        prts_corpus._safe_asset_path(base, "linked/file.gz")


def test_manifest_mirror_must_use_fixed_https_host() -> None:
    urls = prts_corpus._mirror_urls(
        {"data": {"mirrors": [{"base_url": "http://127.0.0.1:8080", "pack_ids": ["references"]}]}},
        "references",
        "r1",
        "catalog/file.gz",
    )

    assert all(url.startswith("https://") for url in urls)
    assert all("127.0.0.1" not in url for url in urls)


def test_gzip_reader_enforces_decompressed_size_limit(tmp_path, monkeypatch) -> None:
    path = tmp_path / "large.jsonl.gz"
    path.write_bytes(gzip.compress(b"x" * 1024))
    monkeypatch.setattr(prts_corpus, "MAX_GZIP_UNCOMPRESSED_BYTES", 128)

    with pytest.raises(prts_corpus.CorpusError):
        list(prts_corpus._iter_gzip_lines(path))


def test_query_has_a_cumulative_decompression_budget(tmp_path, monkeypatch) -> None:
    data_dir = _installed_fixture(tmp_path)
    release_dir = data_dir / "releases" / "r1" / "references"
    catalog_size = len(gzip.decompress((release_dir / "catalog/documents.jsonl.gz").read_bytes()))
    shard_size = len(gzip.decompress((release_dir / "shards/00000.jsonl.gz").read_bytes()))
    monkeypatch.setattr(prts_corpus, "MAX_QUERY_GZIP_UNCOMPRESSED_BYTES", max(catalog_size, shard_size))

    with pytest.raises(prts_corpus.CorpusError, match="累计解压"):
        prts_corpus.CorpusStore(data_dir).search("孤星", pack_ids=["references"])


def test_query_uses_instance_cumulative_decompression_budget(tmp_path) -> None:
    data_dir = _installed_fixture(tmp_path)
    release_dir = data_dir / "releases" / "r1" / "references"
    catalog_size = len(gzip.decompress((release_dir / "catalog/documents.jsonl.gz").read_bytes()))
    shard_size = len(gzip.decompress((release_dir / "shards/00000.jsonl.gz").read_bytes()))
    budget = max(catalog_size, shard_size)
    assert budget < catalog_size + shard_size

    with pytest.raises(prts_corpus.CorpusError, match="累计解压"):
        prts_corpus.CorpusStore(data_dir, query_max_bytes=budget).search("孤星", pack_ids=["references"])


def test_raw_cache_stays_within_instance_budget(tmp_path) -> None:
    data_dir = _installed_fixture(tmp_path)
    catalog = data_dir / "releases" / "r1" / "references/catalog/documents.jsonl.gz"
    budget = len(gzip.decompress(catalog.read_bytes()))
    store = prts_corpus.CorpusStore(data_dir, cache_max_bytes=budget)

    result = store.search("孤星", pack_ids=["references"])

    assert result["count"] == 1
    assert store._cache_bytes <= budget
    assert store._shard_cache == {}


def test_query_keeps_a_pinned_snapshot_while_current_pointer_moves(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    state = {"version": "a" * 64, "text": "旧内容"}
    _install_fake_release(monkeypatch, state)
    first = prts_corpus.sync_packs_locked(data_dir, ["references"])
    store = prts_corpus.CorpusStore(data_dir)
    entered = threading.Event()
    resume = threading.Event()
    original = store._load_shard
    results: dict[str, dict] = {}

    def paused(location, **kwargs):
        entered.set()
        assert resume.wait(5)
        return original(location, **kwargs)

    monkeypatch.setattr(store, "_load_shard", paused)
    worker = threading.Thread(target=lambda: results.setdefault("old", store.search("旧内容", pack_ids=["references"])))
    worker.start()
    assert entered.wait(5)

    state.update(version="b" * 64, text="新内容")
    second = prts_corpus.sync_packs_locked(data_dir, ["references"])
    resume.set()
    worker.join(5)

    assert not worker.is_alive()
    assert first["generation"] != second["generation"]
    assert results["old"]["data_version"] == "a" * 64
    monkeypatch.setattr(store, "_load_shard", original)
    fresh = store.search("新内容", pack_ids=["references"])
    assert fresh["data_version"] == "b" * 64


def test_failed_generation_keeps_existing_pointer_and_data(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    state = {"version": "a" * 64, "text": "旧内容"}
    _install_fake_release(monkeypatch, state)
    first = prts_corpus.sync_packs_locked(data_dir, ["references"])
    before = json.loads((data_dir / "releases/current.json").read_text(encoding="utf-8"))
    state.update(version="b" * 64, text="新内容")

    def fail_download(*_args, **_kwargs):
        raise prts_corpus.CorpusError("synthetic transfer failure")

    monkeypatch.setattr(prts_corpus, "_download_verified", fail_download)
    with pytest.raises(prts_corpus.CorpusError):
        prts_corpus.sync_packs_locked(data_dir, ["references"])

    after = json.loads((data_dir / "releases/current.json").read_text(encoding="utf-8"))
    assert after == before
    assert (data_dir / "releases" / first["generation"]).is_dir()


def test_manifest_asset_traversal_fails_before_publish(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    state = {"version": "a" * 64, "text": "旧内容"}
    _install_fake_release(monkeypatch, state)
    first = prts_corpus.sync_packs_locked(data_dir, ["references"])
    before = json.loads((data_dir / "releases/current.json").read_text(encoding="utf-8"))
    original_request = prts_corpus._request_json

    def malicious_manifest(url: str, *, timeout: int) -> dict:
        payload = original_request(url, timeout=timeout)
        if url.endswith("/references/pack-manifest.json"):
            payload["document_catalog"]["path"] = "../escape.gz"
        return payload

    monkeypatch.setattr(prts_corpus, "_request_json", malicious_manifest)
    with pytest.raises(prts_corpus.CorpusError):
        prts_corpus.sync_packs_locked(data_dir, ["references"])

    assert json.loads((data_dir / "releases/current.json").read_text(encoding="utf-8")) == before
    assert (data_dir / "releases" / first["generation"]).is_dir()
    assert not (data_dir / "releases" / "escape.gz").exists()


def test_asset_size_rejects_boolean_and_malformed_hash(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    state = {"version": "a" * 64, "text": "内容"}
    _install_fake_release(monkeypatch, state)
    original_request = prts_corpus._request_json

    def malformed_manifest(url: str, *, timeout: int) -> dict:
        payload = original_request(url, timeout=timeout)
        if url.endswith("/references/pack-manifest.json"):
            payload["document_catalog"]["compressed_size"] = True
            payload["shards"][0]["sha256"] = "z" * 64
        return payload

    monkeypatch.setattr(prts_corpus, "_request_json", malformed_manifest)
    with pytest.raises(prts_corpus.CorpusError):
        prts_corpus.sync_packs_locked(data_dir, ["references"])
    assert not (data_dir / "releases/current.json").exists()


@pytest.mark.parametrize(
    "licenses",
    [
        [],
        [{"pack_id": "references", "public_distribution_approved": False}],
        [{"pack_id": "references", "public_distribution_approved": "false"}],
    ],
)
def test_missing_or_unapproved_license_fails_closed(tmp_path, monkeypatch, licenses: list[dict]) -> None:
    data_dir = tmp_path / "prts_corpus"
    _install_fake_release(monkeypatch, {"version": "a" * 64, "text": "内容"})
    original_request = prts_corpus._request_json

    def unapproved_manifest(url: str, *, timeout: int) -> dict:
        payload = original_request(url, timeout=timeout)
        if url.endswith("/release-manifest.json"):
            payload["licenses"] = licenses
        return payload

    monkeypatch.setattr(prts_corpus, "_request_json", unapproved_manifest)

    with pytest.raises(prts_corpus.CorpusError, match="未批准公开下载"):
        prts_corpus.sync_packs_locked(data_dir, ["references"])

    assert not (data_dir / "releases/current.json").exists()


def test_verified_download_checks_size_and_sha_without_network(tmp_path, monkeypatch) -> None:
    content = b"synthetic asset"
    destination = tmp_path / "assets" / "payload.bin"
    monkeypatch.setattr(prts_corpus, "_open_url", lambda *_args, **_kwargs: io.BytesIO(content))

    with pytest.raises(prts_corpus.CorpusError):
        prts_corpus._download_verified(
            ["https://prts.chat/payload.bin"],
            destination,
            size=len(content),
            sha256="0" * 64,
            timeout=1,
        )

    assert not destination.exists()


def test_update_publishes_immutable_generation_and_keeps_old_snapshot(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    state = {"version": "a" * 64, "text": "旧内容"}
    _install_fake_release(monkeypatch, state)
    first = prts_corpus.sync_packs_locked(data_dir, ["references"])
    store = prts_corpus.CorpusStore(data_dir)
    assert store.search("旧内容", pack_ids=["references"])["count"] == 1
    old_generation = data_dir / "releases" / first["generation"]
    old_files = {
        path.relative_to(old_generation): path.read_bytes() for path in old_generation.rglob("*") if path.is_file()
    }
    assert old_generation.is_dir()

    state.update(version="b" * 64, text="新内容")
    second = prts_corpus.sync_packs_locked(data_dir, ["references"])

    assert second["generation"] != first["generation"]
    assert old_generation.is_dir()
    assert {
        path.relative_to(old_generation): path.read_bytes() for path in old_generation.rglob("*") if path.is_file()
    } == old_files
    assert store.search("新内容", pack_ids=["references"])["count"] == 1
    assert store.search("旧内容", pack_ids=["references"])["count"] == 0


@pytest.mark.parametrize("tool_name", ["prts.search", "prts.read"])
def test_query_uses_one_pinned_generation_for_data_and_coverage(tmp_path, monkeypatch, tool_name: str) -> None:
    from pallas.product.arknights_kb import prts_runtime, service
    from pallas.product.arknights_kb.config import ArknightsKbConfig

    data_dir = tmp_path / "prts_corpus"
    state = {"version": "a" * 64, "text": "旧内容"}
    _install_fake_release(monkeypatch, state)
    prts_corpus.sync_packs_locked(data_dir, ["references"])
    store = prts_corpus.CorpusStore(data_dir)
    original_status = store.status
    updated = False

    def update_after_status(*, pointer=None, pack_ids=None, require_search_index=False) -> dict:
        nonlocal updated
        status = original_status(
            pointer=pointer,
            pack_ids=pack_ids,
            require_search_index=require_search_index,
        )
        if not updated:
            updated = True
            state.update(version="b" * 64, text="新内容")
            prts_corpus.sync_packs_locked(data_dir, ["references"])
        return status

    monkeypatch.setattr(store, "status", update_after_status)
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: store)
    monkeypatch.setattr(
        service,
        "get_arknights_kb_config",
        lambda: ArknightsKbConfig(prts_corpus_packs="references"),
    )
    arguments = (
        {"query": "旧内容"}
        if tool_name == "prts.search"
        else {"document_uid": prts_corpus._document_uid("client:references:timeline")}
    )

    result = service.execute_query(tool_name, arguments)

    assert result["ok"] is True
    assert result["result"]["coverage"]["data_version"] == "a" * 64
    assert result["result"]["data_version"] == "a" * 64
    if tool_name == "prts.search":
        assert result["result"]["count"] == 1
    else:
        assert result["result"]["lines"][0]["text"] == "旧内容"


def test_failed_generation_load_does_not_poison_a_cached_snapshot(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    state = {"version": "a" * 64, "text": "旧内容"}
    _install_fake_release(monkeypatch, state)
    prts_corpus.sync_packs_locked(data_dir, ["references"])
    store = prts_corpus.CorpusStore(data_dir)
    pointer_a = store.snapshot()
    first = store.search("旧内容", pack_ids=["references"], pointer=pointer_a)
    assert first["count"] == 1

    state.update(version="b" * 64, text="新内容")
    pointer_b = prts_corpus.sync_packs_locked(data_dir, ["references"])
    catalog_b = data_dir / "releases" / pointer_b["generation"] / "references" / "catalog/documents.jsonl.gz"
    catalog_b.write_bytes(b"\x1f\x8bcorrupt")
    with pytest.raises(prts_corpus.CorpusError):
        store.search("新内容", pack_ids=["references"], pointer=pointer_b)

    restored = store.search("旧内容", pack_ids=["references"], pointer=pointer_a)

    assert restored["data_version"] == "a" * 64
    assert restored["count"] == 1


@pytest.mark.parametrize(
    ("tool_name", "missing_asset"),
    [
        ("prts.search", "catalog"),
        ("prts.search", "shard"),
        ("prts.search", "index"),
        ("prts.read", "catalog"),
        ("prts.read", "shard"),
    ],
)
def test_query_with_missing_required_asset_is_source_unavailable(
    tmp_path,
    monkeypatch,
    tool_name: str,
    missing_asset: str,
) -> None:
    from pallas.product.arknights_kb import prts_runtime, service
    from pallas.product.arknights_kb.config import ArknightsKbConfig

    data_dir = _installed_fixture(tmp_path)
    pack_dir = data_dir / "releases" / "r1" / "references"
    manifest_path = pack_dir / "pack-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if missing_asset == "catalog":
        (pack_dir / "catalog/documents.jsonl.gz").unlink()
    elif missing_asset == "shard":
        (pack_dir / "shards/00000.jsonl.gz").unlink()
    else:
        manifest["search_index"] = {"shards": [{"path": "index/00000.bin.gz"}]}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(
        service,
        "get_arknights_kb_config",
        lambda: ArknightsKbConfig(prts_corpus_packs="references"),
    )
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: prts_corpus.CorpusStore(data_dir))

    arguments = (
        {"query": "孤星"}
        if tool_name == "prts.search"
        else {"document_uid": prts_corpus._document_uid("client:references:timeline")}
    )
    result = service.execute_query(tool_name, arguments)

    assert result == {"ok": False, "error": "source_unavailable", "result": None}


def test_search_revalidates_index_after_read_loaded_same_generation(tmp_path) -> None:
    data_dir = _installed_fixture(tmp_path)
    manifest_path = data_dir / "releases/r1/references/pack-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["search_index"] = {"shards": [{"path": "index/00000.bin.gz"}]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    store = prts_corpus.CorpusStore(data_dir)
    pointer = store.snapshot()

    read = store.read(
        document_uid=prts_corpus._document_uid("client:references:timeline"),
        pack_ids=["references"],
        pointer=pointer,
    )
    assert read["lines"]

    with pytest.raises(prts_corpus.CorpusUnavailableError):
        store.search("泰拉", pack_ids=["references"], pointer=pointer)


@pytest.mark.parametrize(
    ("configured_packs", "complete"),
    [("references", True), ("references,official_game", False)],
)
def test_broken_pack_does_not_block_other_pack_queries(
    tmp_path,
    monkeypatch,
    configured_packs: str,
    complete: bool,
) -> None:
    from pallas.product.arknights_kb import prts_runtime, service
    from pallas.product.arknights_kb.config import ArknightsKbConfig

    data_dir = _installed_fixture(tmp_path)
    pointer_path = data_dir / "releases" / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["packs"].append("official_game")
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    bad_pack_dir = data_dir / "releases" / "r1" / "official_game"
    bad_pack_dir.mkdir()
    (bad_pack_dir / "pack-manifest.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(
        service,
        "get_arknights_kb_config",
        lambda: ArknightsKbConfig(prts_corpus_packs=configured_packs),
    )
    monkeypatch.setattr(prts_runtime, "corpus_store", lambda: prts_corpus.CorpusStore(data_dir))

    result = service.execute_query("prts.search", {"query": "孤星"})

    assert result["ok"] is True
    assert result["result"]["count"] == 1
    assert result["result"]["coverage"]["complete"] is complete


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl lock probe is Unix-only")
def test_update_lock_excludes_another_process(tmp_path) -> None:
    lock_path = prts_corpus.corpus_root(tmp_path) / ".update.lock"
    script = """
import fcntl
import sys

with open(sys.argv[1], "a+b") as stream:
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(0)
    raise SystemExit(1)
"""

    with prts_corpus._update_lock(tmp_path):
        result = subprocess.run(
            [sys.executable, "-c", script, str(lock_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    assert result.returncode == 0, result.stderr


def test_corrupt_gzip_asset_fails_before_publish(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    _install_fake_release(monkeypatch, {"version": "a" * 64, "text": "内容"})
    corrupt_asset = bytearray(gzip.compress(b"valid gzip payload"))
    corrupt_asset[-8] ^= 0xFF
    original_request = prts_corpus._request_json
    original_download = prts_corpus._download_verified

    def corrupt_manifest_asset(url: str, *, timeout: int) -> dict:
        payload = original_request(url, timeout=timeout)
        if url.endswith("/references/pack-manifest.json"):
            payload["shards"][0]["compressed_size"] = len(corrupt_asset)
            payload["shards"][0]["sha256"] = hashlib.sha256(corrupt_asset).hexdigest()
        return payload

    def write_corrupt_asset(_urls, destination, *, size, sha256, timeout) -> None:
        if not destination.as_posix().endswith("shards/00000.jsonl.gz"):
            original_download(_urls, destination, size=size, sha256=sha256, timeout=timeout)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(corrupt_asset)

    monkeypatch.setattr(prts_corpus, "_request_json", corrupt_manifest_asset)
    monkeypatch.setattr(prts_corpus, "_download_verified", write_corrupt_asset)

    with pytest.raises(prts_corpus.CorpusError, match="gzip"):
        prts_corpus.sync_packs_locked(data_dir, ["references"])

    assert not (data_dir / "releases/current.json").exists()


def test_release_manifest_pack_path_traversal_fails_before_fetch(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "prts_corpus"
    _install_fake_release(monkeypatch, {"version": "a" * 64, "text": "内容"})
    original_request = prts_corpus._request_json
    requested: list[str] = []

    def malicious_manifest(url: str, *, timeout: int) -> dict:
        requested.append(url)
        payload = original_request(url, timeout=timeout)
        if url.endswith("/release-manifest.json"):
            payload["packs"][0]["manifest_path"] = "../outside.json"
        return payload

    monkeypatch.setattr(prts_corpus, "_request_json", malicious_manifest)

    with pytest.raises(prts_corpus.CorpusError, match="越界"):
        prts_corpus.sync_packs_locked(data_dir, ["references"])

    assert len(requested) == 2
    assert not (data_dir / "releases/current.json").exists()


def _install_fake_release(monkeypatch, state: dict) -> None:
    """Provide small, synthetic upstream payloads without network access."""
    doc = {
        "document_id": "client:references:timeline",
        "display_title": "泰拉年表",
        "document_type": "reference",
        "document_kind": "reference",
        "source_ref_prefix": "client_data:references:timeline",
    }
    shard_path = "shards/00000.jsonl.gz"
    catalog_path = "catalog/documents.jsonl.gz"
    assets: dict[str, bytes] = {}

    def make_assets() -> None:
        assets[shard_path] = gzip.compress(
            (
                json.dumps({"document": doc, "lines": [{"line_number": 1, "speaker_raw": "", "text": state["text"]}]})
                + "\n"
            ).encode()
        )
        assets[catalog_path] = gzip.compress(
            (json.dumps({"document": doc, "shard_path": shard_path, "record_index": 0}) + "\n").encode()
        )

    make_assets()
    pack_manifest = {
        "pack_id": "references",
        "document_count": 1,
        "line_count": 1,
        "document_catalog": {
            "path": catalog_path,
            "compressed_size": len(assets[catalog_path]),
            "sha256": hashlib.sha256(assets[catalog_path]).hexdigest(),
        },
        "shards": [
            {
                "path": shard_path,
                "compressed_size": len(assets[shard_path]),
                "sha256": hashlib.sha256(assets[shard_path]).hexdigest(),
            }
        ],
    }

    def request_json(url: str, *, timeout: int) -> dict:
        if url == prts_corpus.CURRENT_URL:
            return {
                "code": 200,
                "data": {"release_id": "r1", "data_version": state["version"], "mirrors": []},
            }
        if url.endswith("/release-manifest.json"):
            return {
                "release_id": "r1",
                "data_version": state["version"],
                "packs": [{"pack_id": "references", "manifest_path": "references/pack-manifest.json"}],
                "licenses": [{"pack_id": "references", "public_distribution_approved": True}],
            }
        if url.endswith("/references/pack-manifest.json"):
            make_assets()
            pack_manifest["document_catalog"]["compressed_size"] = len(assets[catalog_path])
            pack_manifest["document_catalog"]["sha256"] = hashlib.sha256(assets[catalog_path]).hexdigest()
            pack_manifest["shards"][0]["compressed_size"] = len(assets[shard_path])
            pack_manifest["shards"][0]["sha256"] = hashlib.sha256(assets[shard_path]).hexdigest()
            return pack_manifest
        raise AssertionError(f"unexpected manifest URL: {url}")

    def download_verified(urls, destination, *, size, sha256, timeout):
        path = catalog_path if destination.as_posix().endswith(catalog_path) else shard_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(assets[path])

    monkeypatch.setattr(prts_corpus, "_request_json", request_json)
    monkeypatch.setattr(prts_corpus, "_download_verified", download_verified)


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def _build_index_bytes(entries: list[tuple[str, list[int]]]) -> bytes:
    payload = bytearray()
    offsets = [0]
    for gram, postings in entries:
        encoded = gram.encode("utf-8")
        payload += _encode_varint(len(encoded)) + encoded
        payload += _encode_varint(len(postings))
        current = 0
        for value in postings:
            payload += _encode_varint(value - current)
            current = value
        offsets.append(len(payload))
    header = b"PRTSNG2\0" + len(entries).to_bytes(4, "little")
    table = b"".join(offset.to_bytes(4, "little") for offset in offsets)
    return bytes(header + table + payload)


def _corrupt_index_bytes() -> bytes:
    """gram `abc` valid; gram `xyz` has an unterminated posting-count varint."""
    payload = bytearray()
    offsets = [0]
    payload += _encode_varint(3) + b"abc" + _encode_varint(1) + _encode_varint(0)
    offsets.append(len(payload))
    payload += _encode_varint(3) + b"xyz" + b"\x80"
    offsets.append(len(payload))
    header = b"PRTSNG2\0" + (2).to_bytes(4, "little")
    table = b"".join(offset.to_bytes(4, "little") for offset in offsets)
    return bytes(header + table + payload)


def _line(text: str, speaker: str = "", number: int = 1) -> dict:
    return {"line_number": number, "speaker_raw": speaker, "text": text}


def _doc(document_id, display_title, shard_path, record_index, lines, *, search_index_id=None, **summary):
    doc = {
        "document_id": document_id,
        "display_title": display_title,
        "shard_path": shard_path,
        "record_index": record_index,
        "lines": lines,
    }
    if search_index_id is not None:
        doc["search_index_id"] = search_index_id
    if summary:
        doc["summary"] = summary
    return doc


def _build_corpus(tmp_path, packs: list[dict]):
    """Synthetic single-generation corpus. Each pack: pack_id, docs, optional index."""
    data_dir = tmp_path / "prts_corpus"
    release_dir = data_dir / "releases" / "r1"
    pointer_packs = []
    for pack in packs:
        pack_id = pack["pack_id"]
        pointer_packs.append(pack_id)
        pack_dir = release_dir / pack_id
        catalog_rows = []
        shards: dict[str, list[tuple[int, dict]]] = {}
        for doc in pack["docs"]:
            summary = {"document_id": doc["document_id"], "display_title": doc["display_title"]}
            summary.update(doc.get("summary", {}))
            shards.setdefault(doc["shard_path"], []).append((
                doc["record_index"],
                {"document": summary, "lines": doc["lines"]},
            ))
            catalog_rows.append({
                "document": summary,
                "shard_path": doc["shard_path"],
                "record_index": doc["record_index"],
                "search_index_id": doc.get("search_index_id"),
            })
        manifest: dict = {
            "pack_id": pack_id,
            "document_catalog": {"path": "catalog/documents.jsonl.gz"},
            "shards": [],
        }
        for shard_path, entries in shards.items():
            entries.sort(key=itemgetter(0))
            _write_gzip_jsonl(pack_dir / shard_path, [record for _, record in entries])
            manifest["shards"].append({"path": shard_path})
        _write_gzip_jsonl(pack_dir / "catalog/documents.jsonl.gz", catalog_rows)
        if pack.get("index") is not None:
            index_path = "index/00000.bin.gz"
            (pack_dir / "index").mkdir(parents=True, exist_ok=True)
            (pack_dir / index_path).write_bytes(gzip.compress(_build_index_bytes(pack["index"])))
            manifest["search_index"] = {
                "shards": [{"path": index_path, "first_ngram": "a", "last_ngram": "z"}],
            }
        (pack_dir / "pack-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (data_dir / "releases/current.json").write_text(
        json.dumps({"release_id": "r1", "data_version": "a" * 64, "packs": pointer_packs}),
        encoding="utf-8",
    )
    return data_dir


def _reference_titles(store, query: str, pack_ids, limit: int, **filters) -> list[str]:
    """Full-scan reference replicating the pre-existing ranking (no K / break)."""
    normalized = prts_corpus._normalize(query)
    results = []
    for location in store._locations.values():
        if pack_ids is not None and location.pack_id not in set(pack_ids):
            continue
        if not prts_corpus._summary_matches_filters(location.summary, filters):
            continue
        records = store._load_shard(location, use_cache=True)
        if location.record_index >= len(records):
            continue
        record = records[location.record_index]
        if not isinstance(record, dict) or not store._matches_filters(location.summary, record, filters):
            continue
        matches = prts_corpus._record_matches(record, normalized)
        title_hit = normalized and normalized in prts_corpus._normalize(location.summary.get("display_title"))
        if normalized and not matches and not title_hit:
            continue
        results.append(store._search_item(location, matches))
    results.sort(key=lambda item: (0 if item["matches"] else 1, item["title"]))
    return [item["title"] for item in results[: max(1, limit)]]


def _pack(docs: list[dict], index=None) -> dict:
    return {"pack_id": "references", "docs": docs, "index": index}


def _ordering_fixture(tmp_path):
    return _build_corpus(
        tmp_path,
        [
            _pack([
                _doc("client:references:a", "A-星", "shards/a.jsonl.gz", 0, [_line("no hit")]),
                _doc("client:references:b", "B", "shards/b.jsonl.gz", 0, [_line("星 in body")]),
                _doc("client:references:c", "C", "shards/b.jsonl.gz", 1, [_line("星 also")]),
                _doc("client:references:d", "D-星", "shards/a.jsonl.gz", 1, [_line("none")]),
                _doc("client:references:e", "E", "shards/a.jsonl.gz", 2, [_line("nothing")]),
            ]),
        ],
    )


def test_metadata_filter_short_circuits_before_index_and_body(tmp_path, monkeypatch) -> None:
    data_dir = _build_corpus(
        tmp_path,
        [
            _pack(
                [_doc("client:references:a", "A", "shards/00000.jsonl.gz", 0, [_line("star")], search_index_id=0)],
                index=[("sta", [0])],
            ),
        ],
    )
    store = prts_corpus.CorpusStore(data_dir)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("excluded metadata must not load index or body")

    monkeypatch.setattr(store, "_load_index", forbidden)
    monkeypatch.setattr(store, "_load_shard", forbidden)
    result = store.search("star", pack_ids=["references"], games=["endfield"])

    assert result["count"] == 0
    assert result["items"] == []


def test_metadata_filter_excludes_shard_before_loading_body(tmp_path, monkeypatch) -> None:
    data_dir = _build_corpus(
        tmp_path,
        [
            _pack([
                _doc(
                    "client:references:ark", "Arknights", "shards/ark.jsonl.gz", 0, [_line("needle")], game="arknights"
                ),
                _doc("client:references:end", "Endfield", "shards/end.jsonl.gz", 0, [_line("needle")], game="endfield"),
            ]),
        ],
    )
    store = prts_corpus.CorpusStore(data_dir)
    loaded = []
    original = store._load_shard

    def guard(location, **kwargs):
        loaded.append(location.shard_path)
        if location.shard_path == "shards/end.jsonl.gz":
            raise AssertionError("metadata-excluded shard must not load")
        return original(location, **kwargs)

    monkeypatch.setattr(store, "_load_shard", guard)
    result = store.search("needle", pack_ids=["references"], games=["arknights"])

    assert result["count"] == 1
    assert result["items"][0]["title"] == "Arknights"
    assert loaded == ["shards/ark.jsonl.gz"]


def test_speaker_filter_keeps_record_level_semantics(tmp_path) -> None:
    data_dir = _build_corpus(
        tmp_path,
        [
            _pack([
                _doc(
                    "client:references:s1",
                    "Has",
                    "shards/00000.jsonl.gz",
                    0,
                    [_line("unrelated", "凯尔希", 1), _line("needle", "阿米娅", 2)],
                ),
                _doc("client:references:s2", "Missing", "shards/00000.jsonl.gz", 1, [_line("needle", "阿米娅")]),
            ]),
        ],
    )
    store = prts_corpus.CorpusStore(data_dir)
    result = store.search("needle", pack_ids=["references"], speakers=["凯尔希"])

    assert result["count"] == 1
    assert result["items"][0]["title"] == "Has"


@pytest.mark.parametrize("limit", [1, 2, 4])
def test_search_ranking_matches_full_scan_reference(tmp_path, limit: int) -> None:
    store = prts_corpus.CorpusStore(_ordering_fixture(tmp_path))
    got = store.search("星", pack_ids=["references"], limit=limit)
    expected = _reference_titles(store, "星", ["references"], limit)

    assert [item["title"] for item in got["items"]] == expected


def test_search_stops_after_best_k_body_matches_before_later_shard(tmp_path, monkeypatch) -> None:
    data_dir = _build_corpus(
        tmp_path,
        [
            _pack([
                _doc("client:references:b", "B", "shards/b.jsonl.gz", 0, [_line("星 in body")]),
                _doc("client:references:z", "Z", "shards/z.jsonl.gz", 0, [_line("星 in body too")]),
            ]),
        ],
    )
    store = prts_corpus.CorpusStore(data_dir)
    loaded = []
    original = store._load_shard

    def guard(location, **kwargs):
        loaded.append(location.shard_path)
        if location.shard_path == "shards/z.jsonl.gz":
            raise AssertionError("later shard must not load after K body matches")
        return original(location, **kwargs)

    monkeypatch.setattr(store, "_load_shard", guard)
    result = store.search("星", pack_ids=["references"], limit=1)

    assert result["items"][0]["title"] == "B"
    assert loaded == ["shards/b.jsonl.gz"]


def test_title_only_candidate_is_replaced_by_later_body_match(tmp_path) -> None:
    data_dir = _build_corpus(
        tmp_path,
        [
            _pack([
                _doc("client:references:a", "A-星", "shards/a.jsonl.gz", 0, [_line("no hit")]),
                _doc("client:references:z", "Z", "shards/z.jsonl.gz", 0, [_line("星 in body")]),
            ]),
        ],
    )
    store = prts_corpus.CorpusStore(data_dir)
    result = store.search("星", pack_ids=["references"], limit=1)

    assert result["items"][0]["title"] == "Z"


def test_index_false_positive_is_filtered_by_body_check(tmp_path) -> None:
    shard = "shards/00000.jsonl.gz"
    data_dir = _build_corpus(
        tmp_path,
        [
            _pack(
                [
                    _doc("client:references:real", "Real", shard, 0, [_line("abc here")], search_index_id=0),
                    _doc("client:references:false", "False", shard, 1, [_line("nothing")], search_index_id=1),
                    _doc("client:references:unindexed", "Unindexed", shard, 2, [_line("abc too")], search_index_id=2),
                ],
                index=[("abc", [0, 1])],
            ),
        ],
    )
    store = prts_corpus.CorpusStore(data_dir)
    result = store.search("abc", pack_ids=["references"])

    assert result["count"] == 1
    assert result["items"][0]["title"] == "Real"


def test_search_loads_each_shard_once_without_long_term_shard_cache(tmp_path, monkeypatch) -> None:
    data_dir = _build_corpus(
        tmp_path,
        [
            _pack([
                _doc("client:references:a", "A", "shards/00000.jsonl.gz", 0, [_line("needle one")]),
                _doc("client:references:b", "B", "shards/00000.jsonl.gz", 1, [_line("needle two")]),
            ]),
        ],
    )
    pack_dir = data_dir / "releases/r1/references"
    catalog_size = len(gzip.decompress((pack_dir / "catalog/documents.jsonl.gz").read_bytes()))
    shard_size = len(gzip.decompress((pack_dir / "shards/00000.jsonl.gz").read_bytes()))
    store = prts_corpus.CorpusStore(
        data_dir,
        cache_max_bytes=catalog_size,
        query_max_bytes=catalog_size + shard_size,
    )
    calls = []
    original = store._load_shard

    def counting(location, **kwargs):
        calls.append(location.shard_path)
        return original(location, **kwargs)

    monkeypatch.setattr(store, "_load_shard", counting)
    result = store.search("needle", pack_ids=["references"], limit=5)

    assert result["count"] == 2
    assert calls == ["shards/00000.jsonl.gz"]
    assert store._shard_cache == {}


def _index_fixture(tmp_path):
    return _build_corpus(
        tmp_path,
        [
            _pack(
                [_doc("client:references:a", "A", "shards/00000.jsonl.gz", 0, [_line("abc")], search_index_id=0)],
                index=[("abc", [0]), ("xyz", [0])],
            ),
        ],
    )


def test_index_cache_stores_raw_bytes(tmp_path) -> None:
    store = prts_corpus.CorpusStore(_index_fixture(tmp_path))
    store.search("abc", pack_ids=["references"])

    assert store._index_cache
    assert all(isinstance(value, bytes) for value in store._index_cache.values())


def test_index_cache_hit_does_not_redecompress(tmp_path, monkeypatch) -> None:
    store = prts_corpus.CorpusStore(_index_fixture(tmp_path))
    store._load(pack_ids=["references"], require_search_index=True)
    calls = []
    original = prts_corpus._read_gzip_bytes

    def counting(path, **kwargs):
        calls.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(prts_corpus, "_read_gzip_bytes", counting)
    first = store._load_index("references", "index/00000.bin.gz", {"abc"})
    second = store._load_index("references", "index/00000.bin.gz", {"abc"})

    assert len(calls) == 1
    assert first == {"abc": [0]}
    assert first == second


def test_index_load_retains_only_requested_grams(tmp_path) -> None:
    store = prts_corpus.CorpusStore(_index_fixture(tmp_path))
    store._load(pack_ids=["references"], require_search_index=True)
    path = "index/00000.bin.gz"

    assert set(store._load_index("references", path, {"abc"})) == {"abc"}
    assert set(store._load_index("references", path)) == {"abc", "xyz"}


def test_index_validation_checks_entries_outside_requested_grams(tmp_path) -> None:
    data_dir = _index_fixture(tmp_path)
    (data_dir / "releases/r1/references/index/00000.bin.gz").write_bytes(gzip.compress(_corrupt_index_bytes()))
    store = prts_corpus.CorpusStore(data_dir)
    store._load(pack_ids=["references"], require_search_index=True)

    with pytest.raises(prts_corpus.CorpusError):
        store._load_index("references", "index/00000.bin.gz", {"abc"})
    with pytest.raises(prts_corpus.CorpusError):
        store._load_index("references", "index/00000.bin.gz")


def test_index_rejects_unknown_magic(tmp_path) -> None:
    data_dir = _index_fixture(tmp_path)
    (data_dir / "releases/r1/references/index/00000.bin.gz").write_bytes(gzip.compress(b"BADMAGIC" + b"\x00" * 16))
    store = prts_corpus.CorpusStore(data_dir)
    store._load(pack_ids=["references"], require_search_index=True)

    with pytest.raises(prts_corpus.CorpusError, match="格式未知"):
        store._load_index("references", "index/00000.bin.gz", {"abc"})


def test_index_cache_is_reused_across_different_gram_requests(tmp_path, monkeypatch) -> None:
    store = prts_corpus.CorpusStore(_index_fixture(tmp_path))
    store._load(pack_ids=["references"], require_search_index=True)
    calls = []
    original = prts_corpus._read_gzip_bytes

    def counting(path, **kwargs):
        calls.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(prts_corpus, "_read_gzip_bytes", counting)
    first = store._load_index("references", "index/00000.bin.gz", {"abc"})
    second = store._load_index("references", "index/00000.bin.gz", {"xyz"})

    assert len(calls) == 1
    assert first == {"abc": [0]}
    assert second == {"xyz": [0]}
    assert all(isinstance(value, bytes) for value in store._index_cache.values())


def test_index_none_and_empty_requests_never_cache_parsed(tmp_path) -> None:
    store = prts_corpus.CorpusStore(_index_fixture(tmp_path))
    store._load(pack_ids=["references"], require_search_index=True)
    path = "index/00000.bin.gz"

    assert set(store._load_index("references", path)) == {"abc", "xyz"}
    assert store._load_index("references", path, set()) == {}
    assert all(isinstance(value, bytes) for value in store._index_cache.values())


def test_index_failed_validation_is_not_cached(tmp_path, monkeypatch) -> None:
    data_dir = _index_fixture(tmp_path)
    (data_dir / "releases/r1/references/index/00000.bin.gz").write_bytes(gzip.compress(_corrupt_index_bytes()))
    store = prts_corpus.CorpusStore(data_dir)
    store._load(pack_ids=["references"], require_search_index=True)
    calls = []
    original = prts_corpus._read_gzip_bytes

    def counting(path, **kwargs):
        calls.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(prts_corpus, "_read_gzip_bytes", counting)
    with pytest.raises(prts_corpus.CorpusError):
        store._load_index("references", "index/00000.bin.gz", {"abc"})
    assert store._index_cache == {}

    # a later call must re-read from disk instead of reusing a poisoned cache
    with pytest.raises(prts_corpus.CorpusError):
        store._load_index("references", "index/00000.bin.gz", {"abc"})
    assert len(calls) == 2
