# 元数据

`PluginMetadata` / `extra` 声明帮助、权限、冷却、热载与装包生效；平台按此消费。

## 必填面

| 字段 | 消费者 |
| --- | --- |
| `name` / `description` / `usage` | 帮助图、插件说明 |
| `extra.menu_data` | 帮助结构化入口、治理展示 |
| `extra.command_permissions` | matcher 权限、WebUI 覆盖、「何人可用」 |
| `extra.command_limits` | 冷却默认与展示 |
| `extra.reload_policy` | 热载分级 |
| `extra.activation_policy` | 扩展装包生效（官方 / 社区注册） |

## `usage` 与 `menu_data`

| 字段 | 职责 |
| --- | --- |
| `usage` | 口令展示；用 `usage_line` + `join_usage` |
| `menu_data` | `func` / `trigger_*` / `brief_des` / `detail_des`；权限绑 `command_permission(s)` |

MUST NOT：在 `usage` 或 `trigger_condition` 写死权限角色。细则：[cmd_perm](/common/cmd_perm)。

## `command_permissions`

```python
"command_permissions": [
    {"id": "my_plugin.demo", "label": "牛牛示例", "default": "everyone"},
]
```

同一 `id` 贯穿 matcher、WebUI 覆盖、帮助「何人可用」。

## `command_limits`

```python
"command_limits": [
    {"id": "my_plugin.demo", "cd_sec": 10},
]
```

即使 handler 内自行判断冷却，也 MUST 声明默认值。见 [command_limits](/common/command_limits)。

## `reload_policy`

类型：`Literal["config_only", "metadata", "full"]`（`pallas.core.plugin_reload.metadata.ReloadPolicy`）。默认 `config_only`。

| 值 | 含义 |
| --- | --- |
| `config_only` | WebUI 保存配置即可；无需模块 reload |
| `metadata` | 帮助 / 权限 / ingress 等声明变更需重建索引 |
| `full` | 需完整模块重载或重启 |

## `activation_policy`

类型：`Literal["hot-reloadable", "workers-restart", "full-restart"]`。与 `reload_policy` 正交。

| 值 | 装包 / 升级后 |
| --- | --- |
| `hot-reloadable` | 可热载激活（视部署模式） |
| `workers-restart` | 需重启 worker |
| `full-restart` | 需全进程 / hub+worker 重启 |

官方表：`OFFICIAL_EXTENSION_ACTIVATION_POLICY`（`plugin_matrix.py`）。

## 最小组合

| 插件类型 | MUST |
| --- | --- |
| 纯命令型 | `command_permissions` + `command_limits` + `menu_data` |
| 维护者向 | `help_audience`、`activation_policy`（若扩展）、WebUI/运维说明 |
| 带配置页 | 上列 + `reload_policy` + 热载接入 |

```python
extra={
    "command_permissions": [
        {"id": "my_plugin.demo", "label": "牛牛示例", "default": "everyone"},
    ],
    "command_limits": [
        {"id": "my_plugin.demo", "cd_sec": 10},
    ],
    "reload_policy": "metadata",
    "activation_policy": "hot-reloadable",
}
```

可选增强：`menu_template`、`plugin_storage`、完整 `menu_data`、`knowledge_sources`。

## 检查

- [ ] 命令 ID 全链路一致
- [ ] 权限未写死在文案
- [ ] 帮助仅靠 metadata 可理解
- [ ] 装包生效方式已声明（扩展）

## 相关

- [Golden Plugin](golden-plugin.md)
- [Reload 与 Activation](reload-and-activation.md)
- [cmd_perm](/common/cmd_perm)
