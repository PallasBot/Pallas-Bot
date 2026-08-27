from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
DIST_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "build_webui_dist.sh"


def release_workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_release_builds_clean_sparse_deployment_bundle() -> None:
    text = release_workflow_text()

    assert ".github/release-runtime-sparse-checkout" in text
    assert "git clone --filter=blob:none --no-checkout --depth 1" in text
    assert "status --porcelain" in text
    assert "data/pb_webui" in text
    assert 'PYTHONPYCACHEPREFIX="${RUNNER_TEMP}/pallas-release-pyc"' in text
    assert "pallas-bot-${VERSION}.tar.gz" in text
    assert "pallas-bot-${{ steps.get_version.outputs.version }}.tar.gz" in text
    assert "resource/webui/dist.zip" in text


def test_release_docker_image_reuses_webui_artifact() -> None:
    docker_job = release_workflow_text().split("  build-tagged-image:", maxsplit=1)[1]

    assert "needs: build-webui-dist" in docker_job
    assert "uses: actions/download-artifact@" in docker_job
    assert "name: webui-dist-zip" in docker_job
    assert "path: resource/webui" in docker_job


def test_release_webui_artifact_contains_compatibility_manifest() -> None:
    text = release_workflow_text()
    script = DIST_SCRIPT.read_text(encoding="utf-8")

    assert "release-manifest.json" in text
    assert "release-manifest.json" in script


def test_release_resolves_only_formal_webui_tags() -> None:
    text = release_workflow_text()

    assert "git tag -l 'v[0-9]*'" in text
    assert "=~ ^v[0-9]+" in text
