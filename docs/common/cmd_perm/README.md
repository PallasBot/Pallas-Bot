# 命令权限（cmd_perm）

部分口令与入口的「谁可用」可在运行中配置：代码声明默认等级，WebUI 可覆盖；**牛牛帮助**二/三级图自动展示当前生效的「何人可用」。

实现：`src/features/cmd_perm/`。

## 权限等级

| 配置值 | 含义 |
| --- | --- |
| `everyone` | 不额外限制（仍受私聊/群等事件约束） |
| `bot_moderator` | 号主（`admins` 等） |
| `group_moderator` | 群管/群主；私聊时等价号主侧判定 |
| `staff` | 群管/群主 **或** 号主 |
| `superuser` | 仅超管 |

## 配置

| 项 | 说明 |
| --- | --- |
| WebUI | **通用配置 → 命令权限** |
| 落盘 | `data/pallas_config/webui.json` 键 `PALLAS_COMMAND_PERMISSION_OVERRIDES`（JSON：命令 ID → 等级） |
| 优先级 | `pallas.toml` / 环境变量可被 WebUI 覆盖；**WebUI 最高** |
| 生效 | 改覆盖值后清缓存，**通常无需重启**；改 Python 默认等级需重启或重载插件 |

命令 ID 形式：`{插件}.{动作}`（如 `help.help`）。同一 ID 须在鉴权、registry、metadata、帮助里保持一致。

## 插件接入（维护者）

### Matcher 权限

```python
from src.features.cmd_perm import permission_for_command

on_command("示例", permission=permission_for_command("my_plugin.do_something"))
```

限定群/私聊时用合并 helper，勿写 `Permission & permission_for_command(...)`：

```python
from src.features.cmd_perm import (
    group_message_permission_for_command,
    private_message_permission_for_command,
)
```

### 默认等级声明

在 `PluginMetadata.extra["command_permissions"]` 中声明（推荐），或写入 `registry.DEFAULT_COMMAND_PERMISSIONS` 兜底。每项字段：`id`、`label`（WebUI 展示名）、`default`。

### 帮助菜单 `menu_data`

| 字段 | 面向 | 要点 |
| --- | --- | --- |
| `trigger_condition` | 用户 | 可见口令原文，不写权限角色 |
| `trigger_scene` | 用户 | `群内` / `私聊` / `自动` |
| `brief_des` / `detail_des` | 用户 | 简介与详情；权限由帮助表展示 |
| `command_permission(s)` | 用户 | 与鉴权 ID 一致 |

**`usage` 写法**：`usage_line` + `join_usage`（≥2 条自动编号）；一句 `description`；**勿在 usage 写权限脚注**。与 cmd_perm 无关的业务前提（如须本 Bot 为 QQ 群管）写在 `detail_des` 或插件 README。

插件 README 可用表格列代码默认等级，并注明以 WebUI 为准。完整约定见下文「维护者细则」。

## 排障

| 现象 | 处理 |
| --- | --- |
| 帮助「何人可用」与实鉴权不一致 | 核对 `menu_data` 与 `permission_for_command` 是否同一命令 ID |
| WebUI 矩阵缺某命令 | 在 metadata 或 registry 补 `command_permissions` |
| 覆盖不生效 | 确认已保存 webui.json；检查是否被更高优先级配置覆盖 |

## 实现

[`src/features/cmd_perm/`](../../../src/features/cmd_perm/)

---

## 维护者细则

<details>
<summary>展开：命令 ID、registry 合并、源文件索引、上线自检</summary>

### 命令 ID

- 前缀通常与插件包名一致；未登记 ID 可能不出现在 WebUI 矩阵，但 `permission_for_command` 仍生效。

### registry 合并

`DEFAULT_COMMAND_PERMISSIONS` 为底表，各插件 metadata 同 ID 的 `default` 覆盖底表。修改 Python 后需重启（或触发 `clear_cmd_perm_cache`）。

### 帮助解析别名

`牛牛帮助 远控` 等可匹配 `plugin_aliases.py` 或 `extra["help_aliases"]`；匹配时忽略空格与英文大小写。

### 相关源文件

| 路径 | 职责 |
| --- | --- |
| `check.py` | `permission_for_command`、`satisfies_command_permission` |
| `config.py` | 读取覆盖、`clear_cmd_perm_cache` |
| `registry.py` | 合法等级、默认表 |
| `schema.py` | 合并 metadata、WebUI 矩阵数据 |
| `menu_display.py` | 帮助用权限文案 |
| `metadata_text.py` | `usage_line`、`join_usage`、`SCENE_*` |
| `declare.py` | `command_perm_row` / `command_perm_list` |

### 上线自检

- [ ] 需独立鉴权的入口是否共用同一命令 ID？
- [ ] `command_permissions` 是否含可读 `label`？
- [ ] `menu_data` 是否已绑 `command_permission`，且 `trigger_condition` 无静态权限描述？
- [ ] `usage` 是否未写死权限角色？

</details>
