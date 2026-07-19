# 热重载 pre-reload 清理清单

> 配合 [Reload 与 Activation](/developer/plugin-development/reload-and-activation) 与官方插件 `activation_policy`。WebUI 保存插件配置或 `POST /plugins/{name}/reload` 前按本清单自检。

## 1. 配置级（`reload_policy: config_only`，默认）

| 检查项 | 说明 |
| --- | --- |
| APScheduler job | 插件是否注册定时任务；改 cron 后旧 job 是否仍触发 |
| HTTP 路由 | `startup.py` 是否 `mount` 新路径；重复 mount 会 404/冲突 |
| 协调状态 | 分片 Redis 键、hub-only 注册表是否需手动失效 |
| 后台 worker | 如 repeater learn queue，配置键变更后是否需 `schedule_*_reload()` |

**WebUI 提示**：`activation_policy=hot-reloadable` 时显示「保存后多数配置可热载」。

## 2. 元数据级（`reload_policy: metadata`）

| 检查项 | 说明 |
| --- | --- |
| help 索引 | `reload_metadata_after_plugin_config_save` 是否成功 |
| ingress 路由声明 | `extra["ingress_routes"]` 变更是否需进程级重建索引 |
| cmd_perm 声明 | 新命令是否出现在治理面板 |

**不做**：卸载 matcher；仍走配置保存触发的元数据重建。

## 3. 代码级（`reload_policy: full` 或 pip 安装扩展）

| 检查项 | 说明 |
| --- | --- |
| import 副作用 | 模块级全局单例、缓存、订阅者 |
| 子进程 / MCP | `mcp_bootstrap` 已注册工具是否残留 |
| 协议端连接 | `pb_protocol` 类扩展通常需 `full-restart` |
| hub 挂载 | 仅 hub 注册的 API/静态资源需全栈重启 |

**WebUI 提示**：按 `activation_policy` 展示：

| activation_policy | 用户文案 |
| --- | --- |
| `hot-reloadable` | 安装后尝试热加载；失败再重启 |
| `workers-restart` | 分片环境重启 Worker；单进程重启 Bot |
| `full-restart` | 需全栈重启（含 hub / 协议端） |

## 4. 官方插件安装后

`extension_install` / 商店安装返回 `needs_restart` 与 `activation_action` 时：

1. 读返回 `message` 与 `stdout_tail`
2. 若 SSE 进度流 `phase=failed`，勿假定已安装成功
3. 按 activation_policy 选择牛牛重启或全栈重启

## 5. 社区插件安装/更新/卸载后

`community_plugin_ops` / 商店安装返回 `activation_action` 时：

1. **首次安装** + `hot-reload`：无需重启；确认插件页已出现且命令可用
2. **更新**（无论是否勾重启）：NoneBot 无法卸载旧 matcher；未重启前仍运行旧代码
3. **分片**：社区插件在 worker 加载；重启优先 **workers-only**（WebUI「立即重启」在分片下亦如此）
4. `extra_plugin_dirs` 未含 `local/plugins` 时，安装后无法热加载，须先改配置再重启

## 相关

- [Reload 与 Activation](/developer/plugin-development/reload-and-activation)
- [Golden Plugin](/developer/plugin-development/golden-plugin)
