# 站点定制与在线更新

> 导航：[`标准部署`](../Deployment.md) · [`Docker 部署`](../DockerDeployment.md) · [`配置存储`](settings-storage.md) · [`FAQ`](../FAQ.md)

## 原则

| 内容 | 放哪里 | 更新主仓时 |
|------|--------|------------|
| 监听、数据库、超管 | `config/pallas.toml` `[bootstrap]` | 不动 |
| 插件/通用配置 | `data/pallas_config/webui.json` | 不动 |
| 运行数据、协议实例 | `data/` | 不动 |
| **站点自有插件** | `local/plugins/` + `extra_plugin_dirs` | 不动 |
| 上游功能与修复 | `src/`（官方树） | 随 tag / pull 更新 |

**避免**直接改 `src/`、`bot.py` 等已纳入主仓跟踪的文件；否则控制台「应用 Bot 更新」需要 stash / 手动合并。

## 站点自有插件

1. 在仓库根创建 `local/plugins/<插件名>/__init__.py`（标准 NoneBot 插件结构）。
2. 在 **`config/pallas.toml`**（非 `pyproject.toml`）启用：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

3. 重启 Bot（分片需重启 **hub 与对应 worker**）。  
   - **hub / worker / unified** 均会加载 `extra_plugin_dirs`；与 `src/plugins/` 或 hub 内置模块**同名时优先 local**（如 `help`、`callback`）。
4. **覆盖主仓同名插件**：若 `local/plugins/draw/` 与 `src/plugins/draw/` 同名，会**先加载 local**，再跳过 `src` 中同名项。适合「整包 fork 式定制」；只改少量核心文件见下文「改动主仓已有插件」。

4.0 起官方玩法将迁入独立扩展仓，站点仍可通过 `extra_plugin_dirs` 或包管理器安装；见 [Pallas 4.0 路线图](architecture/pallas-4.0-roadmap.md)。

也可在 `pyproject.toml` 的 `[tool.nonebot] plugin_dirs` 追加目录，但改 `pyproject.toml` 本身会被 git 跟踪；**推荐只用 `pallas.toml`**。

4.0 起另支持 **WebUI 官方插件商店一键安装**（与本文手工投放并存；同名时仍以 local 为准）。见 [4.0 本体瘦身](pallas-4.0-slim.md#扩展安装路径并存)。

## 部署形态与更新方式

控制台 **「版本与更新 → Bot 本体」** 会检测 `deployment_mode`：

| 模式 | 含义 | 推荐更新方式 |
|------|------|----------------|
| `docker` | 运行目录不是 git 工作副本（典型 Docker 镜像） | `docker compose pull` + `up -d` |
| `release_tag` | 当前 HEAD 恰好在 Release tag，工作区干净 | WebUI「应用 Bot 更新」或 `git fetch --tags && git checkout --detach vX.Y.Z` |
| `release_tag_dirty` | 在 tag 上但有本地改动 | 优先把定制迁到 `local/`；更新时会 **自动 stash → checkout → stash pop**（冲突需手动 `git stash pop`） |
| `dev_clone` | 非精确 tag（如在 `main` 上开发） | WebUI 更新走 `git pull --ff-only --autostash` |

## Docker + 外挂插件卷

[`docker-compose.yml`](../../docker-compose.yml) 可选挂载：

```yaml
- ./pallas-bot/local/plugins:/app/local/plugins
```

宿主机 `pallas-bot/config/pallas.toml` 中设置 `extra_plugin_dirs = ["local/plugins"]`。  
镜像更新（`compose pull`）只替换 `/app` 内代码，**挂载的插件与 `data/`、`config/` 均保留**。

## 改动主仓已有插件（非整包复制）

| 方式 | 适用 | 更新后 |
|------|------|--------|
| **整包放入 `local/plugins/<原名>/`** | 改动多、行为差分大 | hub/worker 优先用 local；主仓 `src/plugins/<原名>/` 保持上游干净 |
| **`local/patches/*.patch` 记录 diff** | 只改少量核心文件（`src/*`、`bot.py`） | 更新后 `git apply` 或手工合并；见 `local/patches/README.md` |
| **提 PR / 维护 fork** | 希望长期与上游合并 | 从 fork 拉取 |

NoneBot **不能**两个目录各加载一半同名插件；要么整包 override，要么 patch 主仓文件。

## 相关实现

- `read_bootstrap_extra_plugin_dirs()`：`src/foundation/config/repo_settings.py`
- 插件加载：`src/bot_runtime/plugin_loader.py`
- 更新与部署检测：`src/plugins/pb_webui/manager.py`（`apply_bot_repository_update` / `inspect_bot_deployment`）
