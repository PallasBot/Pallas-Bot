from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_official_image_installs_docker_cli_by_default_with_opt_out() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG INSTALL_DOCKER_CLI=1" in text
    assert 'if [ "$INSTALL_DOCKER_CLI" = "1" ]' in text
    assert "docker.io" in text
    assert 'CMD ["nb", "run"]' in text


def test_compose_keeps_host_docker_access_explicit_and_protocol_scoped() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "# - /var/run/docker.sock:/var/run/docker.sock" in text
    assert "NapCat / SnowLuma" in text
    assert "近似宿主机 root 权限" in text
    assert "不用于管理 AI、数据库或 Bot 自身容器" in text
