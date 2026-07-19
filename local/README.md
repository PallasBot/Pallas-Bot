# 站点本地扩展（不随主仓 git 更新覆盖）

## 插件目录 `plugins/`

将自有 NoneBot 插件放在 `local/plugins/<name>/`（需含 `__init__.py`）。

**修改主仓已有插件**时，把**整包**复制到同名目录（例如 `local/plugins/draw/`），不要只拷部分 `.py` 指望与 `src/plugins/` 合并——NoneBot 只能整包 override 或继续 patch 主仓文件。

在 `config/pallas.toml` 的 **`[bootstrap]`** 段启用：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

**hub、worker、unified** 均会加载该目录；与 `src/plugins/` 或 hub 内置模块列表**同名时优先 local**（例如 `help`、`callback`）。

Docker 可选挂载见 [`docker-compose.yml`](../docker-compose.yml) 与 [Docker 部署](../docs/DockerDeployment.md)。

## 补丁目录 `patches/`

必须改 `bot.py`、`src/*` 等已跟踪文件时，在此保留 `.patch` 与说明（见 [`patches/README.md`](patches/README.md)）。Bot **不会**自动应用补丁。

完整说明：[站点定制与更新](../docs/maintainer/deploy/upgrade.md)。
