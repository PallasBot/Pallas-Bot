# Pallas 统一 CLI（架构路线）

> 4.0 合流前规划。**插件商店「安装后重启」、WebUI Bot 更新与扩展安装** 均应先收敛到本 CLI，再让控制台调用同一套能力。

## 动机

当前 Bot 的**安装、更新、启停**分散在多条路径，运维与 WebUI 难以共用：

| 场景 | 现状入口 | 问题 |
| --- | --- | --- |
| 开发前台跑 | `uv run nb run` | 与生产 `bot.py` 入口不一致 |
| 单进程生产 | `./scripts/run_unified_bot.sh` → `uv run python bot.py` | Bash + 自有 pid/log 目录 |
| 分片生产 | `./scripts/run_sharded_bot.sh` | 另一套 Bash；hub/worker/测试子命令 |
| Docker | `CMD ["nb", "run"]` | 与上述脚本行为不完全对齐 |
| 进程守护 | `tools/scripts/bot_watchdog.py` | 自定义 `--start`，与分片 `--no-spawn` 易配错 |
| 本体 git 更新 | WebUI `POST …/update/bot/apply` → `manager.apply_bot_repository_update` | 与 CLI 无共用 |
| 官方扩展 pip | WebUI `POST …/official-extensions/install` → `extension_install` | 仅 `uv sync`；重启靠人工 |
| 部署模板 | `uv run python tools/apply_deploy_profile.py` | 独立工具 |
| 依赖 / extras | 手写 `uv sync --extra …` | 与商店、Docker `PALLAS_UV_EXTRAS` 三套说法 |

**目标**：单一命令面 `pallas`（建议 `pyproject` 注册 `pallas` 或 `uv run python -m pallas_cli`），覆盖 **下载依赖、更新本体/扩展、单进程/分片启停与状态**；WebUI 与 CI 文档只描述「调 CLI 或等价 Python API」，不再各自拼 subprocess。

## 目标命令面（草案）

```text
pallas doctor              # 配置、uv、Redis（分片）、端口、协议端 accounts 只读检查
pallas sync [--extra …]    # 包装 uv sync；对齐 deploy-full / deploy-all 别名

pallas ext list|install|uninstall <package>   # 官方扩展；内部复用 extension_install
pallas ext install … --restart              # 安装后按角色优雅重启（依赖 run 子命令）

pallas update bot [--tag …]   # git / 发布标签；复用 apply_bot_repository_update 逻辑
pallas update webui           # WebUI dist；复用 extended_api 更新链

pallas run unified [--foreground] [--port …]
pallas run shard [--hub-only|--workers-only] [--workers N] [--worker-base …]
pallas stop|status|restart …  # 对齐 run_unified_bot / run_sharded_bot 语义

pallas deploy apply <profile> # default | shard；包装 apply_deploy_profile

pallas maintenance run [--sync-extra …] [--update-bot] [--no-restart]
                       # 组合：sync → update bot（默认带 restart）
```

**进程模型**：

- `run unified`：单进程，`PALLAS_BOT_ROLE=unified`，可选协议端端口同步（现 `sync_unified_protocol_ports.py`）。
- `run shard`：hub + N worker，Redis 探测、注册表与协议端端口同步（现 `run_sharded_bot.sh` 编排）。
- `restart`：先 `stop` 再 `start`；扩展安装后的「生效」默认走 **角色级 restart**（unified 一整进程；分片可 **workers-only** 或全栈，待实现时定默认）。

## 与 WebUI 插件商店（S6）的关系

| 能力 | 当前 | CLI 落地后 |
| --- | --- | --- |
| 浏览官方扩展 | API + WebUI 面板 | 不变 |
| 安装 / 卸载 | API 直接调 `extension_install` | WebUI 改调 **`pallas ext`** 同一 Python 模块 |
| 安装后重启 | 文案提示人工重启 | **`pallas ext install --restart`** 或商店按钮调 `pallas restart` |
| Bot 仓库更新 | WebUI 独立 git 流程 | 收敛到 **`pallas update bot`** |

**当前策略（已落地）**：WebUI 商店与 Bot 更新页通过 `extension_ops` / `update_ops` 调用与 CLI 相同的 Python 模块；启停推荐 `pallas`，底层仍包装 `run_*_bot.sh`。

## 实现分期

| 期 | 交付 | 说明 |
| --- | --- | --- |
| **A** | `docs` + `src/console/cli/` 骨架 | 已完成 |
| **B** | `ext` / `sync` | 已完成（复用 `extension_install`） |
| **C** | `run` / `stop` / `status` / `restart` | 已完成（包装 `scripts/run_*_bot.sh`） |
| **D** | `update bot` / `update webui` | 已完成（`update_ops`；WebUI API 已改调库） |
| **E** | WebUI 商店与 Bot 更新对接 | 已完成（`restart` 参数、「安装/更新并重启」） |
| **F** | 运维收尾 | 已完成：`maintenance run`、doctor 分片 Redis、`run_*_bot.sh` 标注兼容入口 |

`run_unified_bot.sh` / `run_sharded_bot.sh` 仍为底层实现；**推荐** `./scripts/pallas run|stop|status|restart`，Bash 脚本作兼容别名。

## 非目标（4.0 slim 内不做）

- NoneBot 单插件运行时热载（见 [pallas-4.0-slim.md](pallas-4.0-slim.md) 与 Amiya/真寻对比）；CLI 只做 **进程级** 重启。
- 第三方插件开放市场（仍走 `local/plugins`）。
- 替换 `nb run` 作为 NoneBot 插件开发热重载（开发机可继续 `uv run nb run`）。

## 相关文档

- [pallas-4.0-slim.md](pallas-4.0-slim.md) — 4.0 阶段表
- [bot_process_sharding.md](bot_process_sharding.md) — 分片语义
- [scripts/README.md](../../scripts/README.md) — 现有 Bash 索引
