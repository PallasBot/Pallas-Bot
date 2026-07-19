"""AI 扩展日志路径解析。"""

from __future__ import annotations

from pathlib import Path

from pallas.console.web.ai_extension_logs import (
    ai_extension_base_url_is_local,
    ai_extension_log_missing_message,
    default_celery_log_path,
    default_celery_media_log_path,
    default_uvicorn_log_path,
    is_allowed_log_path,
    log_path_candidates,
    normalize_ai_extension_log_paths,
    normalize_log_path_field,
    pick_existing_log_path,
    resolve_log_path_for_kind,
)


def test_pick_existing_prefers_uvicorn_over_app(tmp_path) -> None:
    ai_root = tmp_path / "Pallas-Bot-AI"
    logs = ai_root / "logs"
    logs.mkdir(parents=True)
    (logs / "app.log").write_text("old\n", encoding="utf-8")
    (logs / "uvicorn.log").write_text("docker\n", encoding="utf-8")
    allowed = [tmp_path.resolve(), ai_root.resolve()]
    picked = pick_existing_log_path(log_path_candidates(ai_root, ("uvicorn.log", "api.log", "app.log")), allowed)
    assert picked.endswith("uvicorn.log")


def test_docker_mount_candidate_when_present(tmp_path) -> None:
    ai_root = tmp_path / "Pallas-Bot-AI"
    ai_root.mkdir()
    docker_logs = tmp_path / "ai-logs"
    docker_logs.mkdir()
    (docker_logs / "celery.log").write_text("worker\n", encoding="utf-8")

    allowed = [tmp_path.resolve(), ai_root.resolve(), docker_logs.resolve()]
    candidates = [docker_logs / "celery.log", ai_root / "logs" / "celery.log"]
    picked = pick_existing_log_path(candidates, allowed)
    assert picked == str((docker_logs / "celery.log").resolve())


def test_normalize_log_paths_auto_detect(tmp_path) -> None:
    bot_root = tmp_path / "Pallas-Bot"
    bot_root.mkdir()
    ai_root = tmp_path / "Pallas-Bot-AI"
    logs = ai_root / "logs"
    logs.mkdir(parents=True)
    (logs / "api.log").write_text("api\n", encoding="utf-8")
    (logs / "celery.log").write_text("celery\n", encoding="utf-8")
    (logs / "celery-media.log").write_text("media\n", encoding="utf-8")

    out = normalize_ai_extension_log_paths({}, bot_repo_root=bot_root)
    assert out["uvicorn_log_file"].endswith("api.log")
    assert out["celery_log_file"].endswith("celery.log")
    assert out["celery_media_log_file"].endswith("celery-media.log")


def test_resolve_log_path_for_kind() -> None:
    cfg = {
        "uvicorn_log_file": "/ai-logs/uvicorn.log",
        "celery_log_file": "/ai-logs/celery.log",
        "celery_media_log_file": "/ai-logs/celery-media.log",
    }
    assert resolve_log_path_for_kind(cfg, "uvicorn") == "/ai-logs/uvicorn.log"
    assert resolve_log_path_for_kind(cfg, "celery") == "/ai-logs/celery.log"
    assert resolve_log_path_for_kind(cfg, "celery-media") == "/ai-logs/celery-media.log"


def test_is_allowed_log_path_under_ai_root(tmp_path) -> None:
    bot_root = tmp_path / "Pallas-Bot"
    ai_root = tmp_path / "Pallas-Bot-AI"
    bot_root.mkdir()
    ai_root.mkdir()
    target = ai_root / "logs" / "uvicorn.log"
    allowed = [bot_root.resolve(), ai_root.resolve()]
    assert is_allowed_log_path(str(target), allowed)
    assert not is_allowed_log_path("/etc/passwd", allowed)


def test_explicit_missing_path_falls_back_to_existing(tmp_path) -> None:
    bot_root = tmp_path / "Pallas-Bot"
    bot_root.mkdir()
    ai_root = tmp_path / "Pallas-Bot-AI"
    logs = ai_root / "logs"
    logs.mkdir(parents=True)
    (logs / "uvicorn.log").write_text("live\n", encoding="utf-8")

    docker_mount = tmp_path / "ai-logs"
    docker_mount.mkdir()
    allowed = [bot_root.resolve(), ai_root.resolve(), docker_mount.resolve()]
    candidates = [docker_mount / "uvicorn.log", logs / "uvicorn.log"]
    explicit = str(docker_mount / "uvicorn.log")

    resolved = normalize_log_path_field(explicit, candidates, allowed)
    assert resolved.endswith("uvicorn.log")
    assert Path(resolved).is_file()
    assert "Pallas-Bot-AI" in resolved


def test_normalize_recovers_from_wrong_saved_path(tmp_path) -> None:
    bot_root = tmp_path / "Bots" / "Pallas-Bot"
    bot_root.mkdir(parents=True)
    ai_root = tmp_path / "Bots" / "Pallas-Bot-AI"
    logs = ai_root / "logs"
    logs.mkdir(parents=True)
    (logs / "uvicorn.log").write_text("ok\n", encoding="utf-8")

    wrong_saved = str(tmp_path / "Pallas-Bot-AI" / "logs" / "uvicorn.log")
    out = normalize_ai_extension_log_paths({"uvicorn_log_file": wrong_saved}, bot_repo_root=bot_root)
    assert Path(out["uvicorn_log_file"]).is_file()
    assert out["uvicorn_log_file"].endswith("Pallas-Bot-AI/logs/uvicorn.log")


def test_ai_extension_log_missing_message_remote() -> None:
    cfg = {"base_url": "http://192.168.1.10:9099"}
    msg = ai_extension_log_missing_message(cfg, path_s="/ai-logs/uvicorn.log")
    assert "HTTP" in msg
    assert ai_extension_base_url_is_local("http://127.0.0.1:9099")
    assert not ai_extension_base_url_is_local("http://ai.example.com:9099")

    failed = ai_extension_log_missing_message(cfg, path_s="/ai-logs/uvicorn.log", remote_tried=True)
    assert "远端" in failed


def test_default_paths_fallback_to_first_candidate(tmp_path) -> None:
    ai_root = tmp_path / "Pallas-Bot-AI"
    ai_root.mkdir()
    allowed = [tmp_path.resolve(), ai_root.resolve()]
    assert default_uvicorn_log_path(ai_root, allowed).endswith("uvicorn.log")
    assert default_celery_log_path(ai_root, allowed).endswith("celery.log")
    assert default_celery_media_log_path(ai_root, allowed).endswith("celery-media.log")
