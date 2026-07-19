# 分片部署模板

依赖：

```bash
uv sync --extra deploy-shard
# 或仅文件 claim、不用 Redis：uv sync --extra shard
```

应用 env 片段（写入 `webui.json`）：

```bash
uv run python tools/apply_deploy_profile.py shard
```

启动：

```bash
./scripts/run_sharded_bot.sh start
```

`PALLAS_BOT_ROLE` / `PORT` 由 `run_sharded_bot.sh` 注入，勿在片段里写死。

完整说明：[多进程分片](../../docs/maintainer/deploy/sharded.md)
