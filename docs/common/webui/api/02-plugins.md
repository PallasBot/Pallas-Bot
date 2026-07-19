# 插件与插件配置

## 插件列表与治理

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/plugins` | | 已加载插件 metadata 列表 |
| GET | `/plugins/help-menu-visibility` | | 帮助图隐藏/忽略集合 |
| PUT | `/plugins/help-menu-visibility` | 是 | 更新帮助可见性 |
| GET | `/plugins/global-disable` | | 全局禁用插件名集合 |
| PUT | `/plugins/global-disable` | 是 | 批量禁用/启用（保护核心插件） |
| GET | `/plugins/capabilities` | | 插件能力聚合（命令权限/CD、LLM tools、storage keys、`reload_policy`、`activation_policy`） |
| GET | `/plugins/group-fleet-whitelist` | | 群舰队白名单插件 |
| PUT | `/plugins/group-fleet-whitelist` | 是 | 更新舰队白名单 |

## 单插件配置（WebUI 插件页）

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/plugins/{plugin_name}/config` | | 字段 schema + 当前值（无 config 时 `fields: []`） |
| PUT | `/plugins/{plugin_name}/config` | 是 | Body `{"values": {"KEY": "value", ...}}` |
| POST | `/plugins/{plugin_name}/config-check` | 是 | 连通性检测（当前主要为 `draw` 网关） |

### GET config `data` 结构（要点）

```json
{
  "plugin": "sing",
  "module": "src.plugins.sing.config",
  "fields": [
    {
      "key": "SING_ENABLE",
      "value": "true",
      "default": "true",
      "type": "bool",
      "title": "...",
      "description": "..."
    }
  ]
}
```

PUT 成功后：

- 写入 `data/pallas_config/webui.json` 的 `env`（键为大写）
- 已注册 `install_hot_reload_config` 的插件会 **立即 reload**，无需重启

校验失败：400 + Pydantic 格式化 `detail`。

## 前端对应

- `fetchPlugins`、`fetchPluginConfig`、`putPluginConfig`
- `fetchPluginCapabilities`（插件页「能力总览」与卡片预览）
- `fetchHelpMenuVisibility`、`putHelpMenuVisibility`
- `fetchGlobalPluginDisable`、`putGlobalPluginDisable`
- `fetchGroupFleetWhitelist`、`putGroupFleetWhitelist`

实现：`extended_api.py`；配置读写 `src/console/webui/plugin_api.py`。

插件作者接入： [WebUI 插件配置](../README.md)。

### 单插件治理

现行说明以开发文档与当前接口行为为准：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/plugins/{plugin_name}/governance` | 单插件：指令表、capabilities、运行状态摘要（含 `activation_policy`） |
| PUT | `/plugins/{plugin_name}/governance` | 本插件 perm/CD 覆盖 + 全实例禁用 + 帮助可见（P1） |

### `activation_policy`

| 值 | 含义 |
| --- | --- |
| `hot-reloadable` | 目标形态可直接热加载；首版商店可优先尝试运行时加载 |
| `workers-restart` | 分片优先 `workers-only` 重启；单进程则整进程优雅重启 |
| `full-restart` | 需全栈重启（如 hub 路由 / 协议端 / 跨角色副作用） |

安装 / 更新官方插件时，返回体还会带：

| 字段 | 含义 |
| --- | --- |
| `activation_action` | `none` / `hot-reload` / `workers-restart` / `full-restart` |
| `restart_scheduled` | 是否已安排后台优雅重启 |
