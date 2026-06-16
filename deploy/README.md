# 可选部署模板

默认部署为**单进程**（`bot.py` / `nb run`），**消息审查默认开启**（WebUI「通用配置 → 消息审查」配置即可）；分片需另用 `shard` 模板。

| 模板 | uv 依赖 | 应用配置 | 说明 |
| --- | --- | --- | --- |
| `default` | `uv sync` | — | 单进程 |
| `shard` | `uv sync --extra deploy-shard` | `uv run python tools/apply_deploy_profile.py shard` | hub + worker；见 [分片架构](docs/architecture/bot_process_sharding.md) |

`deploy-shard` 与既有 `coord-redis` 均安装 `redis`；分片仅文件 claim 时可 `uv sync --extra shard`（无额外包）。

## 快速开始

```bash
# 分片
uv sync --extra deploy-shard
cp config/pallas.example.toml config/pallas.toml   # 若尚未创建
uv run python tools/apply_deploy_profile.py shard
./scripts/run_sharded_bot.sh start
```

应用模板会在 `data/pallas_config/webui.json` 合并 env 键，并写入 `data/pallas_config/deploy_profiles.json` 标记。

## 目录

- [`default/`](default/README.md) — 默认单进程说明
- [`shard/`](shard/README.md) — 分片 env 片段

详细步骤见 [`docs/Deployment.md`](docs/Deployment.md#可选部署模板)。
