from tools import auto_pr_loop as tool


def test_collect_failures_runs_checks(monkeypatch):
    def fake_run(script, python=__import__("sys").executable):
        if "doc_links" in script:
            return 1, "✗ 死链 /x\n"
        return 0, ""

    monkeypatch.setattr(tool, "_run_check", fake_run)
    failures = tool.collect_failures()
    assert "doc_links" in failures
    assert "fixture_health" not in failures


def test_build_pr_body_lists_failures():
    failures = {"doc_links": ["✗ 死链 /x", "✗ 死链 /y"]}
    body = tool.build_pr_body(failures)
    assert "doc_links" in body
    assert "死链 /x" in body
    assert "未自动合并" in body


def test_is_safe_path():
    assert tool._is_safe_path("docs/developer/harness/index.md")
    assert not tool._is_safe_path("config/pallas.toml")
    assert not tool._is_safe_path("data/pallas_config/webui.json")
    assert not tool._is_safe_path(".env")


def test_create_pr_dry_run():
    result = tool.create_pr(
        token="t",
        repo="PallasBot/Pallas-Bot",
        head="feat/x",
        base="dev",
        title="t",
        body="b",
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["head"] == "feat/x"
