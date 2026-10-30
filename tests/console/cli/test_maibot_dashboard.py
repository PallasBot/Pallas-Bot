from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pallas.console.cli import maibot_assets, maibot_dashboard, maibot_install

PIN = maibot_dashboard.PIN
BASE = maibot_dashboard.BASE_PATH
_OLD = {"dashboard/src/alpha.ts": b"old alpha\n", "dashboard/src/beta.ts": b"old beta\n"}
_NEW = {"dashboard/src/alpha.ts": b"new alpha\n", "dashboard/src/beta.ts": b"new beta\n"}
_ADDED = "dashboard/src/__tests__/router.test.ts"
_ADDED_CONTENT = b"synthetic route test\n"
_PATCH = b"""--- a/dashboard/src/alpha.ts
+++ b/dashboard/src/alpha.ts
@@ -1 +1 @@
-old alpha
+new alpha
--- a/dashboard/src/beta.ts
+++ b/dashboard/src/beta.ts
@@ -1 +1 @@
-old beta
+new beta
--- /dev/null
+++ b/dashboard/src/__tests__/router.test.ts
@@ -0,0 +1 @@
+synthetic route test
"""


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _synthetic_source(root: Path, monkeypatch) -> tuple[dict, list[str]]:
    dashboard = root / "dashboard"
    dashboard.mkdir(parents=True)
    (root / ".git").mkdir()
    package = b'{"name":"synthetic-dashboard"}\n'
    lock = b'{"lockfileVersion":3}\n'
    (dashboard / "package.json").write_bytes(package)
    (dashboard / "package-lock.json").write_bytes(lock)
    for name, content in _OLD.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    manifest = {
        "source": {"commit": PIN},
        "build": {"maibot_subpath": BASE},
        "files": [{"path": name, "sha256_before": _sha(_OLD[name]), "sha256_after": _sha(_NEW[name])} for name in _OLD]
        + [{"path": _ADDED, "sha256_before": None, "sha256_after": _sha(_ADDED_CONTENT)}],
        "proxy_contract": {"font_files": ["synthetic.woff2"]},
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    resources = {"front-end.patch": _PATCH, "manifest.json": manifest_bytes}
    monkeypatch.setattr(maibot_dashboard, "PATCH_SHA256", _sha(_PATCH))
    monkeypatch.setattr(maibot_dashboard, "MANIFEST_SHA256", _sha(manifest_bytes))
    monkeypatch.setattr(maibot_dashboard, "PACKAGE_JSON_SHA256", _sha(package))
    monkeypatch.setattr(maibot_dashboard, "PACKAGE_LOCK_SHA256", _sha(lock))
    monkeypatch.setattr(maibot_dashboard, "_resource", lambda name: resources[name])
    monkeypatch.setattr(maibot_dashboard, "_manifest", lambda: manifest)
    return manifest, sorted(["dashboard/package.json", "dashboard/package-lock.json", *_OLD])


def _make_managed(root: Path) -> None:
    (root / maibot_dashboard.INSTALL_MARKER_NAME).write_text(
        json.dumps({"pin": PIN, "state": "incomplete", "dependency_hash": "a" * 64}), encoding="utf-8"
    )


def _fake_build_tools(monkeypatch, tracked: list[str], manifest: dict, build_envs: list[dict[str, str]] | None = None):
    real_run = subprocess.run
    changed = [item["path"] for item in manifest["files"] if item["sha256_before"] is not None]
    added = [item["path"] for item in manifest["files"] if item["sha256_before"] is None]

    def run(command, *, cwd, **kwargs):
        if command[:2] == ["git", "apply"]:
            return real_run(command, cwd=cwd, **kwargs)
        if command[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(command, 0, stdout=PIN + "\n", stderr="")
        if command[:3] == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="\0".join(changed) + "\0", stderr="")
        if command[:3] == ["git", "ls-files", "-z"]:
            return subprocess.CompletedProcess(command, 0, stdout="\0".join(tracked) + "\0", stderr="")
        if command[:4] == ["git", "ls-files", "--others", "--exclude-standard"]:
            return subprocess.CompletedProcess(command, 0, stdout="\0".join(added) + "\0", stderr="")
        if command[0].endswith("/node") and command[-1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="v22.22.3\n", stderr="")
        if command[:2] == ["npm", "ci"]:
            if build_envs is not None:
                build_envs.append(dict(kwargs["env"]))
            assert command == ["npm", "ci", "--no-audit", "--no-fund"]
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["npm", "run", "build"]:
            if build_envs is not None:
                build_envs.append(dict(kwargs["env"]))
            assert command[:5] == ["npm", "run", "build", "--", "--outDir"]
            out = Path(command[-1])
            (out / "assets").mkdir(parents=True)
            (out / "index.html").write_text(f'<script src="{BASE}assets/app.js"></script>', encoding="utf-8")
            (out / "assets" / "app.js").write_text("document.body.dataset.ready = 'true'", encoding="utf-8")
            (out / "assets" / "app.css").write_text("body { display: block }", encoding="utf-8")
            (out / "maimai.ico").write_bytes(b"synthetic ico")
            font = out / "fonts" / "synthetic.woff2"
            font.parent.mkdir(parents=True)
            font.write_bytes(b"synthetic font")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(maibot_dashboard.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(maibot_dashboard.subprocess, "run", run)
    return run


def test_synthetic_fixed_patch_uses_git_apply_and_is_idempotent(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, _ = _synthetic_source(root, monkeypatch)
    assert maibot_dashboard.dashboard_state(root) == "original"

    assert maibot_dashboard.apply_dashboard_compat(root, PIN) == "patched"
    assert maibot_dashboard.dashboard_state(root) == "patched"
    for item in manifest["files"]:
        path = root / item["path"]
        assert path.is_file()
        assert _sha(path.read_bytes()) == item["sha256_after"]
    inodes = {item["path"]: (root / item["path"]).stat().st_ino for item in manifest["files"]}

    assert maibot_dashboard.apply_dashboard_compat(root, PIN) == "patched"
    assert {item["path"]: (root / item["path"]).stat().st_ino for item in manifest["files"]} == inodes


@pytest.mark.parametrize("mutation", ["mixed", "unknown", "symlink"])
def test_unknown_mixed_and_symlink_sources_fail_closed(tmp_path: Path, monkeypatch, mutation: str):
    root = tmp_path / "runtime"
    root.mkdir()
    _synthetic_source(root, monkeypatch)
    path = root / "dashboard/src/alpha.ts"
    if mutation == "mixed":
        path.write_bytes(_NEW["dashboard/src/alpha.ts"])
    elif mutation == "unknown":
        path.write_bytes(b"unknown user source")
    else:
        outside = tmp_path / "outside.ts"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)

    with pytest.raises(maibot_dashboard.DashboardCompatError):
        maibot_dashboard.dashboard_state(root)


def _source_snapshot(root: Path, manifest: dict) -> dict[str, bytes | None]:
    return {
        item["path"]: (root / item["path"]).read_bytes() if (root / item["path"]).is_file() else None
        for item in manifest["files"]
    }


def test_keyboard_interrupt_during_publish_rolls_back_and_propagates(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, _ = _synthetic_source(root, monkeypatch)
    before = _source_snapshot(root, manifest)
    second = root / "dashboard/src/beta.ts"
    real_replace = Path.replace
    interrupted = False

    def interrupt_second(path, destination):
        nonlocal interrupted
        if Path(destination) == second and path.name.startswith(".pallas-dashboard-compat-stage-") and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return real_replace(path, destination)

    monkeypatch.setattr(Path, "replace", interrupt_second)
    with pytest.raises(KeyboardInterrupt):
        maibot_dashboard.apply_dashboard_compat(root, PIN)

    assert _source_snapshot(root, manifest) == before
    assert not (root / _ADDED).exists()
    assert not (root / "dashboard/src/__tests__").exists()


def test_patch_write_failure_rolls_back_sources(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, _ = _synthetic_source(root, monkeypatch)
    before = _source_snapshot(root, manifest)
    second = root / "dashboard/src/beta.ts"
    real_replace = Path.replace
    failed = False

    def fail_second_publish(path, destination):
        nonlocal failed
        if Path(destination) == second and path.name.startswith(".pallas-dashboard-compat-stage-") and not failed:
            failed = True
            raise OSError("injected publish failure")
        return real_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_second_publish)
    with pytest.raises(maibot_dashboard.DashboardCompatError, match="应用补丁"):
        maibot_dashboard.apply_dashboard_compat(root, PIN)
    assert _source_snapshot(root, manifest) == before
    assert maibot_dashboard.dashboard_state(root) == "original"


def test_patch_rollback_failure_preserves_backup(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, _ = _synthetic_source(root, monkeypatch)
    first = root / "dashboard/src/alpha.ts"
    second = root / "dashboard/src/beta.ts"
    original = first.read_bytes()
    real_replace = Path.replace
    failed_publish = False

    def fail_publish_and_rollback(path, destination):
        nonlocal failed_publish
        destination = Path(destination)
        if destination == second and path.name.startswith(".pallas-dashboard-compat-stage-") and not failed_publish:
            failed_publish = True
            raise OSError("injected publish failure")
        if (
            destination == first
            and path.name.startswith(".pallas-dashboard-compat-backup-")
            and path.read_bytes() == original
        ):
            raise OSError("injected rollback failure")
        return real_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_publish_and_rollback)
    with pytest.raises(maibot_dashboard.DashboardCompatError, match="回滚不完整") as error:
        maibot_dashboard.apply_dashboard_compat(root, PIN)
    backups = list(root.rglob(".pallas-dashboard-compat-backup-*"))
    assert backups
    assert str(backups[0]) in str(error.value)
    with pytest.raises(maibot_dashboard.DashboardCompatError):
        maibot_dashboard.dashboard_state(root)


@pytest.mark.parametrize("name", ["front-end.patch", "manifest.json"])
def test_tampered_bundled_resource_fails_before_source_writes(tmp_path: Path, monkeypatch, name: str):
    bundle = tmp_path / "resources"
    bundle.mkdir()
    for resource_name in ("front-end.patch", "manifest.json"):
        content = maibot_dashboard._DASHBOARD_ASSETS.joinpath(resource_name).read_bytes()
        (bundle / resource_name).write_bytes(content)
    resource = bundle / name
    resource.write_bytes(resource.read_bytes() + b"tampered")
    monkeypatch.setattr(maibot_dashboard, "_DASHBOARD_ASSETS", bundle)

    root = tmp_path / "runtime"
    root.mkdir()
    sentinel = root / "dashboard" / "sentinel.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("untouched", encoding="utf-8")
    before = sentinel.read_bytes()
    with pytest.raises(maibot_dashboard.DashboardCompatError):
        maibot_dashboard.dashboard_state(root)
    with pytest.raises(maibot_dashboard.DashboardCompatError):
        maibot_dashboard.apply_dashboard_compat(root, PIN)
    if name == "front-end.patch":
        with pytest.raises(maibot_dashboard.DashboardCompatError):
            maibot_dashboard.build_dashboard(root)
    assert sentinel.read_bytes() == before
    assert not list(root.glob(".pallas-dashboard-compat-*"))


def test_unknown_dashboard_dist_is_never_overwritten(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    _synthetic_source(root, monkeypatch)
    extra = root / "dashboard/dist/user.html"
    extra.parent.mkdir()
    extra.write_text("user build", encoding="utf-8")
    with pytest.raises(maibot_dashboard.DashboardCompatError, match="未知"):
        maibot_dashboard.dashboard_state(root)
    with pytest.raises(maibot_dashboard.DashboardCompatError, match="未知"):
        maibot_dashboard.apply_dashboard_compat(root, PIN)
    assert extra.read_text(encoding="utf-8") == "user build"


def test_dashboard_dist_symlink_is_rejected(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    _synthetic_source(root, monkeypatch)
    dist = root / "dashboard/dist"
    dist.mkdir()
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    (dist / "app.js").symlink_to(outside)
    with pytest.raises(maibot_dashboard.DashboardCompatError, match="符号链接"):
        maibot_dashboard.dashboard_state(root)


def test_install_status_names_missing_frontend_build_tool(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    _synthetic_source(root, monkeypatch)
    (root / "pyproject.toml").write_text("managed", encoding="utf-8")
    (root / "uv.lock").write_text("managed lock", encoding="utf-8")
    maibot_assets.deploy_assets(root)
    (root / maibot_install.INSTALL_MARKER_NAME).write_text(
        json.dumps({"pin": PIN, "state": "complete", "dependency_hash": maibot_install.dependency_hash(root)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(maibot_dashboard.shutil, "which", lambda name: None if name == "node" else "/usr/bin/npm")

    status = maibot_install.installation_status(root)
    assert "前端缺失或待构建" in status
    assert "缺少 Node.js" in status


def test_npm_build_uses_isolated_env_and_validates_built_output(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, tracked = _synthetic_source(root, monkeypatch)
    _make_managed(root)
    maibot_dashboard.apply_dashboard_compat(root, PIN)
    monkeypatch.setenv("PALLAS_MODEL_API_KEY", "must-not-reach-npm")
    build_envs: list[dict[str, str]] = []
    _fake_build_tools(monkeypatch, tracked, manifest, build_envs)

    maibot_dashboard.build_dashboard(root)

    assert maibot_dashboard.dashboard_state(root) == "built"
    assert maibot_dashboard.validate_dashboard_build(root)
    output = capsys.readouterr()
    assert "must-not-reach-npm" not in output.out + output.err
    assert len(build_envs) == 2
    for env in build_envs:
        assert env["MAIBOT_DASHBOARD_BASE"] == BASE
        assert env["ELECTRON_SKIP_BINARY_DOWNLOAD"] == "1"
        assert "PALLAS_MODEL_API_KEY" not in env
        assert "PALLAS_MAIBOT_PROVIDER_TOKEN" not in env


def test_build_timeout_is_safe_and_does_not_create_ready_marker(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, tracked = _synthetic_source(root, monkeypatch)
    _make_managed(root)
    maibot_dashboard.apply_dashboard_compat(root, PIN)
    fake_run = _fake_build_tools(monkeypatch, tracked, manifest)

    def timeout(command, *, cwd, **kwargs):
        if command[:2] == ["npm", "ci"]:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="must-not-be-shown")
        return fake_run(command, cwd=cwd, **kwargs)

    monkeypatch.setattr(maibot_dashboard.subprocess, "run", timeout)
    with pytest.raises(maibot_dashboard.DashboardCompatError, match="超时") as error:
        maibot_dashboard.build_dashboard(root)
    assert "must-not-be-shown" not in str(error.value)
    assert not (root / "dashboard/dist").exists()
    assert json.loads((root / maibot_dashboard.INSTALL_MARKER_NAME).read_text())["state"] == "incomplete"


def test_build_failure_does_not_publish_or_echo_tool_output(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, tracked = _synthetic_source(root, monkeypatch)
    _make_managed(root)
    maibot_dashboard.apply_dashboard_compat(root, PIN)
    fake_run = _fake_build_tools(monkeypatch, tracked, manifest)

    def fail_build(command, *, cwd, **kwargs):
        if command[:3] == ["npm", "run", "build"]:
            return subprocess.CompletedProcess(command, 1, stdout="private build output", stderr="")
        return fake_run(command, cwd=cwd, **kwargs)

    monkeypatch.setattr(maibot_dashboard.subprocess, "run", fail_build)
    with pytest.raises(maibot_dashboard.DashboardCompatError, match="失败") as error:
        maibot_dashboard.build_dashboard(root)
    assert "private build output" not in str(error.value)
    assert not (root / "dashboard/dist").exists()
    assert json.loads((root / maibot_dashboard.INSTALL_MARKER_NAME).read_text())["state"] == "incomplete"


def test_built_marker_and_artifacts_are_integrity_checked(tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime"
    root.mkdir()
    manifest, tracked = _synthetic_source(root, monkeypatch)
    _make_managed(root)
    maibot_dashboard.apply_dashboard_compat(root, PIN)
    _fake_build_tools(monkeypatch, tracked, manifest)
    maibot_dashboard.build_dashboard(root)

    artifact = root / "dashboard/dist/assets/app.js"
    artifact.write_text("changed", encoding="utf-8")
    assert not maibot_dashboard.validate_dashboard_build(root)
    with pytest.raises(maibot_dashboard.DashboardCompatError):
        maibot_dashboard.dashboard_state(root)

    artifact.write_text("document.body.dataset.ready = 'true'", encoding="utf-8")
    marker = root / "dashboard/dist" / maibot_dashboard.BUILD_MARKER_NAME
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["unexpected"] = True
    marker.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(maibot_dashboard.DashboardCompatError):
        maibot_dashboard.dashboard_state(root)
    data.pop("unexpected")
    data["source_hashes"]["dashboard/package-lock.json"] = "0" * 64
    marker.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(maibot_dashboard.DashboardCompatError):
        maibot_dashboard.dashboard_state(root)


def test_exact_pin_dashboard_replay_opt_in(tmp_path: Path):
    raw_source = os.environ.get("PALLAS_MAIBOT_PIN_SOURCE")
    if not raw_source:
        pytest.skip("set PALLAS_MAIBOT_PIN_SOURCE for the exact-pin MaiBot replay")
    source_root = Path(raw_source).expanduser()
    if not (source_root / "dashboard").is_dir():
        pytest.fail("PALLAS_MAIBOT_PIN_SOURCE must point to the pinned MaiBot source root")
    manifest = json.loads(maibot_dashboard._resource("manifest.json"))
    root = tmp_path / "runtime"
    root.mkdir()
    dashboard = root / "dashboard"
    dashboard.mkdir()
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(source_root / "dashboard" / name, dashboard / name)
    for item in manifest["files"]:
        if item["sha256_before"] is None:
            continue
        source = source_root / item["path"]
        target = root / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    assert maibot_dashboard.dashboard_state(root) == "original"
    maibot_dashboard.apply_dashboard_compat(root, PIN)
    for item in manifest["files"]:
        assert _sha((root / item["path"]).read_bytes()) == item["sha256_after"]
