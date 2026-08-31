from tools import observe_runtime as tool


def test_redact_masks_sensitive_keys():
    data = {
        "system_prompt": "secret",
        "messages": [{"role": "user", "content": "hi"}],
        "ok": {"nested": "keep", "reply": "mask"},
        "plain": "value",
    }
    out = tool._redact(data)
    assert out["system_prompt"] == tool.REDACTION_MASK
    assert out["messages"] == tool.REDACTION_MASK
    assert out["ok"]["nested"] == "keep"
    assert out["ok"]["reply"] == tool.REDACTION_MASK
    assert out["plain"] == "value"


def test_redact_depth_limit():
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "x"}}}}}}}
    out = tool._redact(deep)
    assert out["a"]["b"]["c"]["d"]["e"]["f"]["g"] == tool.REDACTION_MASK


def test_failure_classification_extracts_fields():
    bundle = {
        "request_id": "r1",
        "snapshot": {"created_at": 123, "task": "t"},
        "trace": {
            "stages": [{"name": "ingress", "status": "ok"}],
            "error": {"class": "TimeoutError"},
        },
    }
    out = tool._failure_classification(bundle)
    assert out["request_id"] == "r1"
    assert out["error_class"] == "TimeoutError"
    assert out["stages"] == [{"name": "ingress", "status": "ok"}]
    assert out["created_at"] == 123
    assert out["task"] == "t"


def test_failure_classification_handles_missing():
    out = tool._failure_classification({})
    assert out["stages"] == []
    assert out["error_class"] is None


def test_list_request_ids_parses_jsonl(tmp_path, monkeypatch):
    path = tmp_path / "request_snapshots.jsonl"
    path.write_text(
        '{"request_id": "a"}\n{"request_id": "b"}\n{"request_id": "a"}\nnot-json\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.product.llm.runtime_debug.request_snapshot_path", lambda: path)
    assert tool._list_request_ids() == ["a", "b"]


def test_prune_jsonl_removes_stale(tmp_path):
    path = tmp_path / "x.jsonl"
    now = 1_000_000
    fresh = {"created_at": now - 10}
    stale = {"created_at": now - 10_000_000}
    path.write_text(
        f"{__import__('json').dumps(fresh)}\n{__import__('json').dumps(stale)}\n",
        encoding="utf-8",
    )
    removed = tool._prune_jsonl(path, cutoff=now - 100)
    assert removed == 1
    remaining = [__import__("json").loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert remaining == [fresh]


def test_build_observation_snapshot_shape(monkeypatch):
    monkeypatch.setattr(tool, "_startup_report_snapshot", lambda: {"facts": {}})
    monkeypatch.setattr(tool, "_ingress_metrics", lambda **kw: {"points": []})
    monkeypatch.setattr(tool, "_route_candidate_history", list)
    monkeypatch.setattr(tool, "_list_request_ids", lambda: ["a", "b"])
    snap = tool.build_observation_snapshot()
    assert snap["startup_report"] == {"facts": {}}
    assert snap["ingress_metrics"] == {"points": []}
    assert snap["request_ids"] == ["a", "b"]
    assert "generated_at" in snap
