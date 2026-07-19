# 命令权限

运维视角：谁能用某条命令。开发接入见 [cmd_perm](/common/cmd_perm)。

## 三层值

| 层 | 来源 | 说明 |
| --- | --- | --- |
| 代码默认 | `PluginMetadata.extra["command_permissions"]` | 插件作者声明 |
| 配置覆盖 | `pallas.toml` / 环境变量 | 可被 WebUI 覆盖 |
| WebUI 覆盖 | 通用配置 → **命令权限** → `webui.json` 键 `PALLAS_COMMAND_PERMISSION_OVERRIDES` | **最高优先级** |

帮助图「何人可用」展示**当前生效值**，不是写死在 `usage` 里的文案。

## 等级

| 值 | 含义 |
| --- | --- |
| `everyone` | 不额外限制（仍受群/私聊事件约束） |
| `bot_moderator` | 号主（`admins` 等） |
| `group_moderator` | 群管 / 群主；私聊时按号主侧判定 |
| `staff` | 群管/群主 **或** 号主 |
| `superuser` | 仅超管 |

## 边界

| 能力 | 文档 |
| --- | --- |
| 冷却（多久再用） | [command_limits](/common/command_limits) |
| 插件安装 / 全局禁用 | [插件治理](plugin-governance.md) |

## 常用操作

| 操作 | 做法 |
| --- | --- |
| 改运行时门槛 | WebUI **命令权限**矩阵 → 保存（通常无需重启） |
| 核对生效值 | 以 WebUI / 帮助为准，不要只看源码默认 |
| 矩阵缺命令 | 插件未声明 `command_permissions` 或命令 ID 未进 registry |

## 排障

| 现象 | 检查 |
| --- | --- |
| 谁都不能用 | WebUI 是否调高；插件是否禁用；是否另有业务前提 |
| 帮助与实鉴权不一致 | `menu_data.command_permission` 与 matcher 是否同一命令 ID |
| 刚用过又失败 | 查冷却（非权限） |

## 相关

- [cmd_perm 接入](/common/cmd_perm)
- [command_limits](/common/command_limits)
- [插件治理](plugin-governance.md)
