# 默认部署（单进程）

```bash
uv sync
cp config/pallas.example.toml config/pallas.toml
nb run
```

不设置 `PALLAS_SHARD_ENABLED` 时，Bot 以 unified 角色运行全部插件。消息审查 4.0 默认开启，可用 `PALLAS_MESSAGE_SCRUB_ENABLED=false` 关闭。
