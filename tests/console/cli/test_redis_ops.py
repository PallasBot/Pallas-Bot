from __future__ import annotations


def test_start_redis_reuses_reachable_configured_url(monkeypatch) -> None:
    from pallas.console.cli import redis_ops

    monkeypatch.setattr(redis_ops, "configured_redis_url", lambda: "redis://existing:6379/0")
    monkeypatch.setattr(redis_ops, "redis_url_reachable", lambda _url: True)
    monkeypatch.setattr(redis_ops, "docker_ready", lambda: (_ for _ in ()).throw(AssertionError("no docker")))

    assert redis_ops.start_redis() == 0


def test_start_redis_creates_loopback_docker_container_and_persists_url(monkeypatch) -> None:
    from pallas.console.cli import redis_ops

    monkeypatch.setattr(redis_ops, "configured_redis_url", lambda: "")
    monkeypatch.setattr(redis_ops, "docker_ready", lambda: True)
    monkeypatch.setattr(redis_ops, "ensure_docker_redis", lambda: 43879)
    monkeypatch.setattr(redis_ops, "redis_url_reachable", lambda _url: True)
    persisted: list[str] = []
    monkeypatch.setattr(redis_ops, "persist_redis_url", persisted.append)

    assert redis_ops.start_redis() == 0
    assert persisted == ["redis://127.0.0.1:43879/0"]


def test_start_redis_keeps_database_outbox_available_without_docker(monkeypatch) -> None:
    from pallas.console.cli import redis_ops

    monkeypatch.setattr(redis_ops, "configured_redis_url", lambda: "")
    monkeypatch.setattr(redis_ops, "docker_ready", lambda: False)

    assert redis_ops.start_redis() == 1
