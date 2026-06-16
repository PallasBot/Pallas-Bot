# src 内核分层

`src/` 下除 `plugins/` 外按职责分为六层，插件与脚本应优先从各层包的公开 API 导入，避免深层 `import` 内部实现文件。

| 层 | 路径 | 内容 |
| --- | --- | --- |
| foundation | `src/foundation/` | `config`、`paths`、`logging`、`db`；`bot_version`、`command_prefix`、`apscheduler_runtime` |
| platform | `src/platform/` | `shard`、`multi_bot`（含 **bot_filter** / connected_roster）、`ingress`（含 **gate** 预处理器、dispatch、route_index）、`bot_runtime`（含 `kernel_runtime`）、`coord`、`federate`、`ai_callback` |
| features | `src/features/` | `cmd_perm`、`command_limits`、`message_scrub`、`community_stats`、`corpus`、`control_plane`、`ban_gate`、`persona`、`llm`、`service_gateways`（连通探测 +「牛牛连通」口令） |
| console | `src/console/` | `webui`、`web`、`cli` |
| domain | `src/domain/` | `arknights` 等域共享（游戏数据见 [arknights-knowledge-mcp.md](arknights-knowledge-mcp.md)） |
| shared | `src/shared/` | `utils`、`adapters`、`service_probe` |

## 依赖方向（建议）

- `shared`、`foundation`：不依赖 `platform` / `features`
- `platform`：可依赖 `foundation`、`shared`
- `features`：可依赖 `foundation`、`shared`、`platform`（尽量少）
- `console`：可依赖各层（面向 WebUI 聚合配置）
- `domain`：尽量只依赖 `foundation`、`shared`

## 导入示例

```python
from src.foundation.config.repo_settings import repo_env_raw_value
from src.platform.bot_runtime import register_ingress_dispatch_runtime
from src.platform.multi_bot.dedup import should_skip_group_message
from src.features.cmd_perm import check_command_permission
```

旧路径 `src.common.*` 已移除，请使用上表中的分层路径。
