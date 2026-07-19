import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.store import (
    ShardRegistry,
    assign_bot_to_shard,
    clear_shard_registry_cache,
    save_shard_registry,
)
from pallas.core.platform.shard.worker_scale import (
    auto_scale_workers_enabled,
    list_running_production_worker_shard_ids,
    production_worker_count_required,
    run_worker_scale_restart,
    schedule_worker_scale_restart,
    workers_need_scale_up,
)


@pytest.fixture(autouse=True)
def shard_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    monkeypatch.setenv("PALLAS_SHARD_BOTS_PER", "5")
    monkeypatch.setenv("PALLAS_SHARD_WORKER_BASE_PORT", "8090")
    monkeypatch.setenv("PALLAS_SHARD_AUTO_SCALE_WORKERS", "false")
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()
    reg_dir = tmp_path / "pallas_shard"
    reg_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.store._registry_path",
        lambda: reg_dir / "registry.json",
    )
    run_dir = reg_dir / "run"
    run_dir.mkdir()
    monkeypatch.setattr("pallas.core.platform.shard.worker_scale.shard_run_dir", lambda: run_dir)
    # 隔离协议端 accounts.json：避免读到仓库真实 data/pallas_protocol/accounts.json
    accounts_path = tmp_path / "pallas_protocol" / "accounts.json"
    accounts_path.parent.mkdir(parents=True, exist_ok=True)
    accounts_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.platform.protocol_paths.protocol_accounts_path",
        lambda *, create=False: accounts_path,
    )
    yield run_dir
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()


def _write_worker_pid(run_dir: Path, shard_id: int) -> None:
    pid_file = run_dir / f"worker-{shard_id}.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def test_production_worker_count_follows_registry(monkeypatch, tmp_path):
    proto = tmp_path / "data" / "pallas_protocol"
    proto.mkdir(parents=True)
    accounts_path = proto / "accounts.json"
    accounts_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "pallas.core.platform.protocol_paths.protocol_accounts_path",
        lambda *, create=False: accounts_path,
    )
    reg = ShardRegistry(bots_per_shard=2, worker_base_port=8090, ws_host="127.0.0.1")
    save_shard_registry(reg)
    clear_shard_registry_cache()
    assign_bot_to_shard("111", registry=reg)
    assign_bot_to_shard("222", registry=reg)
    assign_bot_to_shard("333", registry=reg)
    assert production_worker_count_required(reg) == 2


def test_workers_need_scale_when_shard_missing(shard_env):
    run_dir = shard_env
    reg = ShardRegistry(bots_per_shard=5, worker_base_port=7970, ws_host="127.0.0.1")
    for sid in range(7):
        _write_worker_pid(run_dir, sid)
    reg.assignments = {f"bot{i}": 6 for i in range(5)}
    reg.assignments["newbot"] = 7
    need, required, running = workers_need_scale_up(reg)
    assert need is True
    assert required == 8
    assert running == 7


def test_workers_skip_scale_when_none_running(shard_env):
    reg = ShardRegistry(bots_per_shard=5, worker_base_port=7970, ws_host="127.0.0.1")
    reg.assignments = {"bot1": 7}
    need, _, running = workers_need_scale_up(reg)
    assert need is False
    assert running == 0


def test_schedule_skips_on_worker_role(monkeypatch, shard_env):
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    get_shard_registry_settings.cache_clear()
    reg = ShardRegistry(bots_per_shard=5, worker_base_port=7970, ws_host="127.0.0.1")
    _write_worker_pid(shard_env, 0)
    reg.assignments = {"bot1": 1}
    assert schedule_worker_scale_restart(reason="test") is False


def test_run_worker_scale_restart_spawns_script(shard_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PALLAS_SHARD_AUTO_SCALE_WORKERS", "true")
    get_shard_registry_settings.cache_clear()
    run_dir = shard_env
    _write_worker_pid(run_dir, 0)
    reg = ShardRegistry(bots_per_shard=5, worker_base_port=7970, ws_host="127.0.0.1")
    reg.assignments = {"bot1": 1}
    save_shard_registry(reg)
    clear_shard_registry_cache()
    fake_repo = tmp_path / "repo"
    script = fake_repo / "scripts" / "run_sharded_bot.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr("pallas.core.platform.shard.worker_scale.repo_root", lambda: fake_repo)

    popen = MagicMock()
    proc = MagicMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    popen.return_value = proc
    with (
        patch("pallas.core.platform.shard.worker_scale.subprocess.Popen", popen),
        patch(
            "pallas.core.platform.shard.worker_scale.threading.Thread",
            side_effect=lambda *a, **k: MagicMock(start=MagicMock()),
        ),
    ):
        assert run_worker_scale_restart(reason="unit") is True
    popen.assert_called_once()
    args = popen.call_args[0][0]
    assert args[-3:] == ["start", "--workers-only", "--scale-only"]


def test_auto_scale_disabled(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_AUTO_SCALE_WORKERS", "false")
    assert auto_scale_workers_enabled() is False


def test_list_running_worker_ids(shard_env):
    _write_worker_pid(shard_env, 0)
    _write_worker_pid(shard_env, 3)
    assert list_running_production_worker_shard_ids() == {0, 3}
