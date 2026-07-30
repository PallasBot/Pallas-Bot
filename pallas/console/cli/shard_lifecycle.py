"""分片 hub + worker 启停（Python，跨平台；替代 run_sharded_bot.sh 生产路径）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003

from pallas.console.cli.process_util import (
    clear_pid_file,
    pid_alive,
    read_pid_file,
    spawn_detached,
    stop_pid,
    uv_run_python_cmd,
    write_pid_file,
)
from pallas.console.cli.shard_guard import kill_port_listeners, kill_script_orphans, tcp_listen_pids
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.shard.registry.port_alloc import is_tcp_port_in_use

RUN_DIR = PROJECT_ROOT / "data" / "pallas_shard" / "run"
LOG_DIR = PROJECT_ROOT / "data" / "pallas_shard" / "logs"
ACCOUNTS_JSON = PROJECT_ROOT / "data" / "pallas_protocol" / "accounts.json"
REGISTRY_JSON = PROJECT_ROOT / "data" / "pallas_shard" / "registry.json"
ENV_PATH = PROJECT_ROOT / ".env"
PID_HUB = RUN_DIR / "hub.pid"


@dataclass
class ShardOptions:
    workers: int | None = None
    bots_per_shard: int | None = None
    hub_port: int | None = None
    worker_base: int | None = None
    workers_only: bool = False
    hub_only: bool = False
    scale_only: bool = False
    skip_port_sync: bool = False
    skip_occupied_ports: bool = True
    force: bool = False
    no_force: bool = False
    dry_run: bool = False
    worker_ports: list[int] = field(default_factory=list)


def print_rule() -> None:
    print("────────────────────────────────────────────────────────")


def print_title(text: str) -> None:
    print()
    print(f"  {text}")
    print_rule()


def resolve_hub_port(opts: ShardOptions) -> int:
    if opts.hub_port is not None:
        return int(opts.hub_port)
    for key in ("PALLAS_SHARD_HUB_PORT", "PORT"):
        raw = os.environ.get(key, "").strip()
        if raw.isdigit():
            return int(raw)
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    return int(get_shard_registry_settings().hub_port)


def resolve_worker_base(opts: ShardOptions) -> int:
    if opts.worker_base is not None:
        return int(opts.worker_base)
    raw = os.environ.get("PALLAS_SHARD_WORKER_BASE_PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    return int(get_shard_registry_settings().worker_base_port)


def resolve_bots_per(opts: ShardOptions) -> int:
    if opts.bots_per_shard is not None:
        return int(opts.bots_per_shard)
    raw = os.environ.get("PALLAS_SHARD_BOTS_PER", "").strip()
    if raw.isdigit():
        return int(raw)
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    return int(get_shard_registry_settings().bots_per_shard)


def calc_worker_count(opts: ShardOptions) -> int:
    if opts.workers is not None and opts.workers > 0:
        return int(opts.workers)
    from pallas.core.platform.shard.registry.worker_count import calc_production_worker_count

    return int(
        calc_production_worker_count(
            bots_per_shard=resolve_bots_per(opts),
            worker_base_port=resolve_worker_base(opts),
            accounts_path=ACCOUNTS_JSON if ACCOUNTS_JSON.is_file() else None,
            registry_path=REGISTRY_JSON if REGISTRY_JSON.is_file() else None,
        )
    )


def shard_common_env(opts: ShardOptions) -> dict[str, str]:
    return {
        "PALLAS_SHARD_ENABLED": "true",
        "PALLAS_SHARD_BOTS_PER": str(resolve_bots_per(opts)),
        "PALLAS_SHARD_HUB_PORT": str(resolve_hub_port(opts)),
        "PALLAS_SHARD_WORKER_BASE_PORT": str(resolve_worker_base(opts)),
    }


def load_coord_redis_env() -> dict[str, str]:
    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
    from pallas.core.platform.coord.redis_settings import (
        clear_coord_redis_settings_cache,
        coord_redis_enabled,
        resolve_coord_redis_url,
    )

    apply_repo_settings_to_environ()
    clear_coord_redis_settings_cache()
    url = resolve_coord_redis_url() or ""
    if url and coord_redis_enabled():
        return {
            "PALLAS_COORD_REDIS_ENABLED": "true",
            "PALLAS_COORD_REDIS_URL": url,
        }
    return {}


def redis_status() -> dict[str, str]:
    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
    from pallas.core.platform.coord.redis_settings import (
        clear_coord_redis_settings_cache,
        coord_redis_enabled,
        coord_redis_mode,
        resolve_coord_redis_url,
    )

    apply_repo_settings_to_environ()
    clear_coord_redis_settings_cache()
    try:
        import redis  # noqa: F401

        pkg = "yes"
    except ImportError:
        pkg = "no"
    mode = coord_redis_mode()
    url = resolve_coord_redis_url() or ""
    reachable = "yes" if url and coord_redis_enabled() else "no"
    active = "yes" if reachable == "yes" else "no"
    backend = "redis" if active == "yes" else "unavailable"
    return {
        "policy": mode,
        "url": url,
        "package": pkg,
        "reachable": reachable,
        "active": active,
        "backend": backend,
    }


def require_coord_redis(*, dry_run: bool) -> int:
    if dry_run:
        return 0
    st = redis_status()
    if st["policy"] == "false":
        print(
            "  错误       分片模式依赖 Redis 协调 claim，不可禁用（PALLAS_COORD_REDIS_ENABLED=false）",
            file=sys.stderr,
        )
        return 1
    if not st["url"]:
        print(
            "  错误       分片模式需要 REDIS_URL（config/pallas.toml [env] 或 webui.json）",
            file=sys.stderr,
        )
        return 1
    if st["reachable"] != "yes":
        if st["package"] == "no":
            print("  错误       Redis 客户端未安装，请执行: uv sync --extra coord-redis", file=sys.stderr)
        else:
            print(f"  错误       Redis 不可达: {st['url']}", file=sys.stderr)
            print("  提示       请确认 Redis 服务已启动并可 ping 通", file=sys.stderr)
        return 1
    return 0


def coord_backend_hint() -> str:
    env = load_coord_redis_env()
    if env.get("PALLAS_COORD_REDIS_ENABLED") == "true" and env.get("PALLAS_COORD_REDIS_URL"):
        return "跨进程 claim：Redis"
    return "跨进程 claim：Redis 未就绪（分片 claim 不可用）"


def pidfile_running(path: Path) -> bool:
    pid = read_pid_file(path)
    return pid is not None and pid_alive(pid)


def production_worker_pid_files() -> list[Path]:
    if not RUN_DIR.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(RUN_DIR.glob("worker-*.pid")):
        name = path.stem
        if name in ("worker-test", "worker-test2"):
            continue
        out.append(path)
    return out


def count_running_production_workers() -> tuple[int, int]:
    files = production_worker_pid_files()
    running = sum(1 for p in files if pidfile_running(p))
    return running, len(files)


def count_running_production_worker_ids() -> int:
    return sum(1 for p in production_worker_pid_files() if pidfile_running(p))


def resolve_worker_start_mode(workers: int) -> str:
    running = count_running_production_worker_ids()
    if workers <= 0:
        return "cold"
    if running >= workers:
        return "skip"
    if running > 0:
        return "scale"
    return "cold"


def registry_port_for_shard(sid: int, opts: ShardOptions) -> int:
    if 0 <= sid < len(opts.worker_ports):
        return int(opts.worker_ports[sid])
    if REGISTRY_JSON.is_file():
        try:
            raw = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
            for row in raw.get("shards") or []:
                if int(row.get("id", -1)) == int(sid):
                    return int(row["port"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass
    return resolve_worker_base(opts) + int(sid)


def require_tcp_port_free(port: int, label: str) -> int:
    if not is_tcp_port_in_use(port):
        return 0
    print(f"  · {label}：端口 {port} 仍被占用，无法启动", file=sys.stderr)
    for pid in tcp_listen_pids(port):
        print(f"      pid {pid}", file=sys.stderr)
    return 1


def rotate_bootstrap_log(name: str) -> Path:
    bootstrap = LOG_DIR / f"{name}.bootstrap.log"
    if not bootstrap.is_file() or bootstrap.stat().st_size == 0:
        if bootstrap.is_file():
            bootstrap.unlink(missing_ok=True)
        return bootstrap
    archive = LOG_DIR / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    bootstrap.rename(archive / f"{name}.bootstrap-{ts}.log")
    return LOG_DIR / f"{name}.bootstrap.log"


def start_one(name: str, label: str, *, cmd: list[str], env: dict[str, str], opts: ShardOptions) -> int:
    pidfile = RUN_DIR / f"{name}.pid"
    if pidfile_running(pidfile):
        print(f"  · {label}：已在运行（无需重复启动）")
        return 0
    if opts.dry_run:
        print(f"  · {label}：将执行启动（预览）")
        return 0
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    bootstrap = rotate_bootstrap_log(name)
    try:
        pid = spawn_detached(cmd, cwd=PROJECT_ROOT, env=env, log_path=bootstrap)
    except OSError as err:
        print(f"  · {label}：启动失败 {err}", file=sys.stderr)
        return 1
    write_pid_file(pidfile, pid)
    logfile = LOG_DIR / f"{name}.log"
    print(f"  · {label}：已启动（日志 {logfile}，启动期 {bootstrap}）")
    return 0


def stop_one(name: str, label: str, *, opts: ShardOptions) -> None:
    pidfile = RUN_DIR / f"{name}.pid"
    if not pidfile_running(pidfile):
        clear_pid_file(pidfile)
        print(f"  · {label}：未在运行")
        return
    if opts.dry_run:
        print(f"  · {label}：将停止（预览）")
        return
    pid = read_pid_file(pidfile)
    if pid is not None:
        stop_pid(pid, timeout_s=15.0, force=opts.force)
    clear_pid_file(pidfile)
    print(f"  · {label}：{'已强制停止' if opts.force else '已停止'}")


def stop_orphan_hub(opts: ShardOptions) -> None:
    kill_script_orphans(PROJECT_ROOT, "bot_hub.py", force=opts.force)
    kill_port_listeners(resolve_hub_port(opts), force=opts.force)
    if not opts.force:
        time.sleep(1)
        kill_script_orphans(PROJECT_ROOT, "bot_hub.py", force=True)
        kill_port_listeners(resolve_hub_port(opts), force=True)


def stop_orphan_workers(opts: ShardOptions) -> None:
    kill_script_orphans(PROJECT_ROOT, "bot_worker.py", force=opts.force)
    workers = calc_worker_count(opts)
    for sid in range(workers):
        kill_port_listeners(registry_port_for_shard(sid, opts), force=opts.force)
    if not opts.force:
        time.sleep(1)
        kill_script_orphans(PROJECT_ROOT, "bot_worker.py", force=True)
        for sid in range(workers):
            kill_port_listeners(registry_port_for_shard(sid, opts), force=True)


def start_hub(opts: ShardOptions) -> int:
    hub_port = resolve_hub_port(opts)
    if require_tcp_port_free(hub_port, "hub  控制台") != 0:
        return 1
    env = {
        **shard_common_env(opts),
        **load_coord_redis_env(),
        "PALLAS_BOT_ROLE": "hub",
        "PORT": str(hub_port),
    }
    return start_one(
        "hub",
        f"hub  控制台 :{hub_port}",
        cmd=uv_run_python_cmd("bot_hub.py"),
        env=env,
        opts=opts,
    )


def start_workers(opts: ShardOptions, *, missing_only: bool) -> int:
    workers = calc_worker_count(opts)
    common = {**shard_common_env(opts), **load_coord_redis_env()}
    for sid in range(workers):
        wport = registry_port_for_shard(sid, opts)
        pidfile = RUN_DIR / f"worker-{sid}.pid"
        if missing_only and pidfile_running(pidfile):
            print(f"  · worker-{sid}  WS:{wport}：已在运行（无需重复启动）")
            continue
        if require_tcp_port_free(wport, f"worker-{sid}  WS:{wport}") != 0:
            return 1
        env = {
            **common,
            "PALLAS_BOT_ROLE": "worker",
            "PALLAS_SHARD_ID": str(sid),
            "PORT": str(wport),
        }
        rc = start_one(
            f"worker-{sid}",
            f"worker-{sid}  WS:{wport}",
            cmd=uv_run_python_cmd("bot_worker.py"),
            env=env,
            opts=opts,
        )
        if rc != 0:
            return rc
    return 0


def stop_production_workers(opts: ShardOptions) -> None:
    for path in production_worker_pid_files():
        sid = path.stem.removeprefix("worker-")
        stop_one(path.stem, f"worker-{sid}", opts=opts)
    if not opts.dry_run:
        stop_orphan_workers(opts)


def prepare_shard_ports(opts: ShardOptions, workers: int) -> int:
    if opts.dry_run:
        print("  · worker/协议端端口：将评估并按需更新（预览）")
        return 0
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings
    from pallas.core.platform.shard.registry.port_alloc import (
        sync_registry_worker_ports,
        worker_ports_from_registry,
    )
    from pallas.core.platform.shard.registry.startup_ports import (
        evaluate_protocol_port_sync,
        evaluate_registry_worker_ports,
    )
    from pallas.core.platform.shard.registry.store import clear_shard_registry_cache, get_shard_registry
    from pallas.core.platform.shard.registry.sync_protocol_ports import (
        apply_env_for_shard_sync,
        format_sync_user_message,
        read_dotenv,
        sync_accounts_ws_urls,
    )

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    env_path = ENV_PATH if ENV_PATH.is_file() else None
    accounts_path = ACCOUNTS_JSON if ACCOUNTS_JSON.is_file() else None
    if env_path is not None:
        apply_env_for_shard_sync(read_dotenv(env_path))
        get_shard_registry_settings.cache_clear()
        clear_shard_registry_cache()

    base = resolve_worker_base(opts)
    skip_occupied = opts.skip_occupied_ports
    reg_ev = evaluate_registry_worker_ports(
        workers,
        base,
        env_path=env_path,
        skip_occupied=skip_occupied,
    )
    for note in reg_ev.notes:
        print(f"    · {note}")

    worker_ports = list(reg_ev.worker_ports)
    if not reg_ev.skip_registry_alloc:
        result = sync_registry_worker_ports(
            workers,
            base,
            skip_occupied=skip_occupied,
            persist=True,
        )
        for _port, msg in result.skipped:
            print(f"    · {msg}")
        clear_shard_registry_cache()
        final = worker_ports_from_registry(get_shard_registry(), workers)
        worker_ports = final if final is not None else result.ports

    proto_ev = evaluate_protocol_port_sync(accounts_path=accounts_path, env_path=env_path)
    for note in proto_ev.notes:
        print(f"    · {note}")

    if not opts.skip_port_sync and accounts_path is not None and not proto_ev.skip_protocol_sync:
        backup = RUN_DIR / "accounts.json.pre_sync"
        sync_result = sync_accounts_ws_urls(
            accounts_path,
            env_path=env_path,
            backup_path=backup,
            dry_run=False,
        )
        if sync_result.changed_count or sync_result.onebot_synced_count:
            print(f"    {format_sync_user_message(sync_result, backup_path=backup)}")

    opts.worker_ports = [int(p) for p in worker_ports]
    print(f"    worker 端口 {','.join(str(p) for p in opts.worker_ports)}")
    return 0


def wait_worker_ports_released(opts: ShardOptions, workers: int) -> None:
    from pallas.core.platform.shard.registry.port_alloc import wait_tcp_ports_free

    if opts.force:
        print("  · worker 端口：强制模式，短等待 3s")
        time.sleep(3)
        return
    if opts.dry_run:
        print("  · worker 端口：将等待释放后再启动（预览）")
        return
    ports: list[int] = []
    if REGISTRY_JSON.is_file():
        try:
            raw = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
            by_id = {int(row["id"]): int(row["port"]) for row in (raw.get("shards") or []) if "id" in row}
            ports.extend(by_id[sid] for sid in range(max(0, workers)) if sid in by_id)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            ports = []
    if not ports:
        time.sleep(2)
        return
    timeout = float(os.environ.get("PALLAS_SHARD_PORT_RELEASE_TIMEOUT") or 60)
    print(f"  等待 worker 端口释放（登记见 registry.json，超时 {timeout:g}s）…")
    ok, busy = wait_tcp_ports_free(ports, timeout_sec=timeout, poll_interval_sec=0.5)
    if ok:
        print(f"    worker 端口已释放: {','.join(str(p) for p in ports)}")
    else:
        print(
            f"  · 部分端口仍未释放: {','.join(str(p) for p in busy)}；继续启动可能失败",
            file=sys.stderr,
        )


def print_config_summary(opts: ShardOptions, workers: int) -> None:
    print(f"  每片牛数   {resolve_bots_per(opts)}")
    print(f"  worker 数  {workers}")
    print(f"  hub 端口   {resolve_hub_port(opts)}")
    print(f"  worker 起点 {resolve_worker_base(opts)}")
    if opts.worker_ports:
        print(f"  worker 端口 {','.join(str(p) for p in opts.worker_ports)}")


def print_redis_status_block() -> None:
    print("  跨进程协调 (ingress claim)")
    st = redis_status()
    policy = st["policy"] or "auto"
    if policy == "false":
        print("    策略     已禁用 (PALLAS_COORD_REDIS_ENABLED=false)")
        print("    状态     分片 claim 不可用")
        return
    if not st["url"]:
        print(f"    策略     {policy}")
        print("    配置     未设置 REDIS_URL（pallas.toml [env] 或 webui.json）")
        print("    状态     分片 claim 不可用")
        return
    print(f"    策略     {policy}")
    print(f"    地址     {st['url']}")
    print("    客户端   已安装" if st["package"] == "yes" else "    客户端   未安装（uv sync --extra coord-redis）")
    if st["reachable"] == "yes":
        print("    连通     可达 → 启动 worker 时将使用 Redis")
    else:
        print("    连通     不可达 → 分片 claim 不可用")
    print("    当前     Redis 已启用" if st["active"] == "yes" else "    当前     Redis 未启用")


def print_observability_status_block(opts: ShardOptions) -> None:
    print("  分片可观测")
    try:
        from pallas.core.platform.shard.observability import aggregate_shard_observability
        from pallas.core.platform.shard.registry.config import is_sharding_active

        # 临时注入环境以便聚合
        saved = {k: os.environ.get(k) for k in ("PALLAS_SHARD_ENABLED", "PALLAS_BOT_ROLE", "PALLAS_SHARD_HUB_PORT")}
        os.environ.update(shard_common_env(opts))
        os.environ["PALLAS_BOT_ROLE"] = "hub"
        try:
            data = aggregate_shard_observability()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        workers = data.get("workers")
        if not (bool(data.get("sharded")) or is_sharding_active() or (isinstance(workers, list) and workers)):
            if not pidfile_running(PID_HUB) and count_running_production_worker_ids() == 0:
                print("    未启用分片（unified 模式）")
                return
        ing = data.get("ingress_cluster") or {}
        coord = data.get("coord_pending_live") or {}
        rate = ing.get("claim_hit_rate")
        rate_s = "—" if rate is None else f"{float(rate) * 100:.1f}%"
        print(f"    ingress 命中率(集群/今日)  {rate_s}  won={ing.get('claim_won', 0)} lost={ing.get('claim_lost', 0)}")
        print(
            f"    ingress 事件              {ing.get('events', 0)}  "
            f"fanout跳过={ing.get('fanout_bypass', 0)}  "
            f"早丢弃={int(ing.get('early_fleet', 0)) + int(ing.get('early_not_at_target', 0))}"
        )
        print(
            f"    coord Redis              keys={coord.get('keys', 0)}  "
            f"actionable={coord.get('actionable', 0)}  "
            f"historical={coord.get('historical', 0)}  "
            f"bot_action_open={coord.get('bot_action_open', 0)}  "
            f"stale_open={coord.get('stale_open', 0)}"
        )
    except Exception as err:
        print(f"    （读取失败：{err}）")


def cmd_status(opts: ShardOptions) -> int:
    workers = calc_worker_count(opts)
    hub_port = resolve_hub_port(opts)
    print_title("Pallas-Bot 分片模式 · 运行状态")
    print("  配置摘要")
    print_config_summary(opts, workers)
    print()
    print_redis_status_block()
    print()
    print_observability_status_block(opts)
    print()
    print("  进程")
    hub_state = "运行中" if pidfile_running(PID_HUB) else "未运行"
    print(f"    hub        {hub_state}  :{hub_port}")
    running = 0
    for path in production_worker_pid_files():
        sid = path.stem.removeprefix("worker-")
        wport = registry_port_for_shard(int(sid) if sid.isdigit() else 0, opts)
        if pidfile_running(path):
            running += 1
            print(f"    worker-{sid}  运行中  WS:{wport}  pid={read_pid_file(path)}")
        else:
            print(f"    worker-{sid}  未运行  WS:{wport}")
    print()
    print(f"  汇总       hub {hub_state} · worker {running}/{workers}")
    print(f"  WebUI      http://127.0.0.1:{hub_port}/pallas/")
    print(f"  日志目录   {LOG_DIR}")
    return 0


def cmd_stop(opts: ShardOptions) -> int:
    if opts.workers_only and opts.hub_only:
        print("  --workers-only 与 --hub-only 不能同时使用", file=sys.stderr)
        return 1
    if opts.hub_only:
        running, total = count_running_production_workers()
        print_title("Pallas-Bot 分片模式 · 停止 hub（保留 worker）")
        if total > 0:
            print(f"  worker     保持运行（{running}/{total}）")
        else:
            print("  worker     未运行")
        print()
        stop_one("hub", "hub  控制台", opts=opts)
        if not opts.dry_run:
            stop_orphan_hub(opts)
        print()
        print("  hub 已处理完毕（生产 worker 与测试 worker-test 未停止）。")
        return 0
    if opts.workers_only:
        print_title("Pallas-Bot 分片模式 · 停止 worker（保留 hub）")
        if pidfile_running(PID_HUB):
            print(f"  hub        保持运行（端口 {resolve_hub_port(opts)}）")
        else:
            print("  hub        未运行")
        print()
        stop_production_workers(opts)
        print()
        print("  生产 worker 已处理完毕（测试 worker-test 未停止）。")
        return 0
    title = "Pallas-Bot 分片模式 · 停止" + ("（强制）" if opts.force else "")
    print_title(title)
    stop_one("worker-test", "测试 worker-test", opts=opts)
    stop_one("worker-test2", "测试 worker-test2", opts=opts)
    stop_production_workers(opts)
    stop_one("hub", "hub  控制台", opts=opts)
    if not opts.dry_run:
        stop_orphan_hub(opts)
        stop_orphan_workers(opts)
    print()
    print("  全部分片进程已处理完毕。")
    return 0


def cmd_start(opts: ShardOptions) -> int:
    if opts.workers_only and opts.hub_only:
        print("  --workers-only 与 --hub-only 不能同时使用", file=sys.stderr)
        return 1
    if require_coord_redis(dry_run=opts.dry_run) != 0:
        return 1

    if opts.hub_only:
        print_title("Pallas-Bot 分片模式 · 启动 hub（不启 worker）")
        print(f"  hub 端口   {resolve_hub_port(opts)}")
        print(f"  {coord_backend_hint()}")
        print()
        print("  正在启动 hub…")
        if start_hub(opts) != 0:
            return 1
        if opts.dry_run:
            print()
            print("  （预览模式，未实际启动进程）")
            return 0
        time.sleep(1)
        ok = pidfile_running(PID_HUB)
        print_title("hub 启动完成")
        print(f"  汇总       hub {'运行中' if ok else '未就绪'}")
        if ok:
            print(f"  WebUI      http://127.0.0.1:{resolve_hub_port(opts)}/pallas/")
        return 0 if ok else 1

    workers = calc_worker_count(opts)
    if opts.workers_only:
        mode = resolve_worker_start_mode(workers)
        if opts.scale_only:
            mode = "scale" if mode != "skip" else "skip"
        elif mode == "scale":
            opts.scale_only = True
        print_title("Pallas-Bot 分片模式 · 启动缺失 worker")
        print_config_summary(opts, workers)
        print(f"  {coord_backend_hint()}")
        print()
        if mode == "skip":
            print(f"  worker     已全部运行（{count_running_production_worker_ids()}/{workers}），跳过")
            return 0
        if mode == "cold" and not opts.scale_only:
            wait_worker_ports_released(opts, workers)
            if prepare_shard_ports(opts, workers) != 0:
                return 1
            workers = calc_worker_count(opts)
        print("  正在启动 worker…")
        return start_workers(opts, missing_only=(mode == "scale" or opts.scale_only))

    mode = resolve_worker_start_mode(workers)
    running_before = count_running_production_worker_ids()
    print_title("Pallas-Bot 分片模式 · 启动")
    print_config_summary(opts, workers)
    if mode == "skip":
        print(f"  worker     已全部运行（{running_before}/{workers}），跳过 worker 启动与端口重分配")
    elif mode == "scale":
        print(f"  worker     部分运行（{running_before}/{workers}），仅启动缺失 worker")
        print("  端口策略   扩容模式（registry 端口，不重分配、不同步协议端）")
        opts.scale_only = True
    else:
        print("  端口策略   自动跳过占用" if opts.skip_occupied_ports else "  端口策略   严格 起点+分片号")
    print(f"  {coord_backend_hint()}")
    print()

    if mode == "cold":
        wait_worker_ports_released(opts, workers)
        print()
        if prepare_shard_ports(opts, workers) != 0:
            return 1
        workers = calc_worker_count(opts)
    print()
    print("  正在启动进程…")
    if start_hub(opts) != 0:
        return 1
    if not opts.dry_run and mode == "cold":
        time.sleep(1)
    if mode == "skip":
        pass
    elif mode == "scale":
        workers = calc_worker_count(opts)
        if start_workers(opts, missing_only=True) != 0:
            return 1
    else:
        if start_workers(opts, missing_only=False) != 0:
            return 1

    if opts.dry_run:
        print()
        print("  （预览模式，未实际启动进程）")
        return 0

    print()
    print("  正在确认进程是否就绪…")
    hub_ok = pidfile_running(PID_HUB)
    if not hub_ok:
        print(f"  · 控制台 hub 未在运行，请查看日志: {LOG_DIR}/hub.log")
    worker_running = 0
    worker_fail = 0
    for path in production_worker_pid_files():
        if pidfile_running(path):
            worker_running += 1
        else:
            worker_fail += 1
            print(f"  · {path.stem} 启动后已退出，请查看: {LOG_DIR}/{path.stem}.log")

    print_title("启动完成")
    print(f"  汇总       hub {'运行中' if hub_ok else '未就绪'} · worker {worker_running}/{workers} 运行")
    if hub_ok:
        hub_url = f"http://127.0.0.1:{resolve_hub_port(opts)}"
        print(f"  WebUI      {hub_url}/pallas/")
        print(f"  协议端     {hub_url}/pallas/protocol/")
    return 0 if hub_ok else 1


def apply_restart_force_default(opts: ShardOptions) -> None:
    """restart 默认 --force（SIGKILL + 短等端口）；--no-force 可改回优雅停。"""
    if opts.no_force:
        opts.force = False
    else:
        opts.force = True


def cmd_restart(opts: ShardOptions) -> int:
    apply_restart_force_default(opts)
    if opts.hub_only:
        if require_coord_redis(dry_run=opts.dry_run) != 0:
            return 1
        print_title("Pallas-Bot 分片模式 · 重启 hub（保留 worker）")
        stop_one("hub", "hub  控制台", opts=opts)
        if not opts.dry_run:
            stop_orphan_hub(opts)
        print()
        print("  正在启动 hub…")
        hub_opts = ShardOptions(
            workers=opts.workers,
            bots_per_shard=opts.bots_per_shard,
            hub_port=opts.hub_port,
            worker_base=opts.worker_base,
            hub_only=True,
            skip_port_sync=opts.skip_port_sync,
            skip_occupied_ports=opts.skip_occupied_ports,
            force=opts.force,
            dry_run=opts.dry_run,
        )
        return cmd_start(hub_opts)
    if opts.workers_only:
        if require_coord_redis(dry_run=opts.dry_run) != 0:
            return 1
        workers = calc_worker_count(opts)
        print_title("Pallas-Bot 分片模式 · 重启 worker（保留 hub）")
        print_config_summary(opts, workers)
        print()
        stop_production_workers(opts)
        print()
        wait_worker_ports_released(opts, workers)
        print()
        if prepare_shard_ports(opts, workers) != 0:
            return 1
        print()
        print("  正在启动 worker…")
        return start_workers(opts, missing_only=False)
    stop_rc = cmd_stop(opts)
    if stop_rc != 0:
        return stop_rc
    start_opts = ShardOptions(
        workers=opts.workers,
        bots_per_shard=opts.bots_per_shard,
        hub_port=opts.hub_port,
        worker_base=opts.worker_base,
        skip_port_sync=opts.skip_port_sync,
        skip_occupied_ports=opts.skip_occupied_ports,
        force=opts.force,
        dry_run=opts.dry_run,
        worker_ports=list(opts.worker_ports),
    )
    return cmd_start(start_opts)


def parse_extra_args(extra: list[str] | None) -> ShardOptions:
    opts = ShardOptions()
    if not extra:
        return opts
    i = 0
    args = list(extra)
    while i < len(args):
        a = args[i]
        if a == "--hub-only":
            opts.hub_only = True
        elif a == "--workers-only":
            opts.workers_only = True
        elif a == "--scale-only":
            opts.scale_only = True
        elif a == "--skip-port-sync":
            opts.skip_port_sync = True
        elif a == "--no-skip-occupied-ports":
            opts.skip_occupied_ports = False
        elif a == "--force":
            opts.force = True
        elif a == "--no-force":
            opts.no_force = True
            opts.force = False
        elif a == "--dry-run":
            opts.dry_run = True
        elif a == "--workers" and i + 1 < len(args):
            i += 1
            opts.workers = int(args[i])
        elif a == "--worker-base" and i + 1 < len(args):
            i += 1
            opts.worker_base = int(args[i])
        elif a == "--bots-per-shard" and i + 1 < len(args):
            i += 1
            opts.bots_per_shard = int(args[i])
        elif a == "--hub-port" and i + 1 < len(args):
            i += 1
            opts.hub_port = int(args[i])
        i += 1
    return opts


def run_shard_action(action: str, *, extra_args: list[str] | None = None) -> int:
    opts = parse_extra_args(extra_args)
    normalized = (action or "status").strip().lower()
    if normalized == "start":
        return cmd_start(opts)
    if normalized == "stop":
        return cmd_stop(opts)
    if normalized == "restart":
        return cmd_restart(opts)
    if normalized == "status":
        return cmd_status(opts)
    print(f"未知动作: {action}（期望 start|stop|restart|status）", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pallas 分片启停（Python）")
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("start", "stop", "restart", "status"),
    )
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--bots-per-shard", type=int, default=None)
    parser.add_argument("--hub-port", type=int, default=None)
    parser.add_argument("--worker-base", type=int, default=None)
    parser.add_argument("--workers-only", action="store_true")
    parser.add_argument("--hub-only", action="store_true")
    parser.add_argument("--scale-only", action="store_true")
    parser.add_argument("--skip-port-sync", action="store_true")
    parser.add_argument("--no-skip-occupied-ports", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="stop 时 SIGKILL 强杀并跳过端口长等待；restart 默认已启用",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="restart 时改用优雅停止（默认 restart 等同 --force）",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    opts = ShardOptions(
        workers=args.workers,
        bots_per_shard=args.bots_per_shard,
        hub_port=args.hub_port,
        worker_base=args.worker_base,
        workers_only=args.workers_only,
        hub_only=args.hub_only,
        scale_only=args.scale_only,
        skip_port_sync=args.skip_port_sync,
        skip_occupied_ports=not args.no_skip_occupied_ports,
        force=bool(args.force) and not bool(args.no_force),
        no_force=bool(args.no_force),
        dry_run=args.dry_run,
    )
    if args.action == "start":
        return cmd_start(opts)
    if args.action == "stop":
        return cmd_stop(opts)
    if args.action == "restart":
        return cmd_restart(opts)
    return cmd_status(opts)


if __name__ == "__main__":
    raise SystemExit(main())
