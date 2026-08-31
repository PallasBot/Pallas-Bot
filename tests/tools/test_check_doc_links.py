from pathlib import Path

from tools.check_doc_links import _collect_anchors, _resolve_target, check_doc_links


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolve_root_relative_virtual_path(tmp_path: Path) -> None:
    _write(tmp_path / "developer" / "architecture" / "overview.md", "# 概览\n")
    resolved, anchor = _resolve_target(
        "/developer/architecture/overview",
        docs_root=tmp_path,
        current_dir=tmp_path / "guide",
    )
    assert resolved == (tmp_path / "developer" / "architecture" / "overview.md").resolve()
    assert anchor is None


def test_resolve_directory_falls_back_to_readme(tmp_path: Path) -> None:
    _write(tmp_path / "plugins" / "help" / "README.md", "# 帮助\n")
    resolved, _ = _resolve_target(
        "/plugins/help/",
        docs_root=tmp_path,
        current_dir=tmp_path,
    )
    assert resolved == (tmp_path / "plugins" / "help" / "README.md").resolve()


def test_resolve_relative_path(tmp_path: Path) -> None:
    _write(tmp_path / "a" / "b.md", "# B\n")
    resolved, _ = _resolve_target(
        "../a/b.md",
        docs_root=tmp_path,
        current_dir=tmp_path / "x",
    )
    assert resolved == (tmp_path / "a" / "b.md").resolve()


def test_resolve_external_skipped(tmp_path: Path) -> None:
    for link in ("https://example.com", "http://x.dev", "mailto:a@b.c", "#anchor"):
        resolved, _ = _resolve_target(link, docs_root=tmp_path, current_dir=tmp_path)
        assert resolved is None


def test_resolve_outside_docs_returns_path(tmp_path: Path) -> None:
    resolved, _ = _resolve_target(
        "../../../packages/blacklist/",
        docs_root=tmp_path,
        current_dir=tmp_path / "plugins" / "blacklist",
    )
    assert resolved is not None


def test_collect_anchors_slugs_headings(tmp_path: Path) -> None:
    _write(tmp_path / "doc.md", "# 标题 一\n## 二 三\n")
    anchors = _collect_anchors(tmp_path / "doc.md")
    assert "标题-一" in anchors
    assert "二-三" in anchors


def test_check_doc_links_reports_dead_and_broken_anchor(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "# A\n\n[去 B](/missing)\n\n[去 C](/b#不存在)\n")
    _write(tmp_path / "b.md", "# B\n")
    errors = check_doc_links(tmp_path)
    assert any("死链" in e and "/missing" in e for e in errors)
    assert any("失效锚点" in e and "不存在" in e for e in errors)


def test_check_doc_links_clean(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "# A\n\n[去 B](/b)\n")
    _write(tmp_path / "b.md", "# B\n")
    assert check_doc_links(tmp_path) == []
