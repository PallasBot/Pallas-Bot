# 命令权限（cmd_perm）接入说明

本仓库将**部分命令/入口**的鉴权抽象为可配置等级：默认由代码声明，运行中可通过环境变量或 WebUI「通用配置 → 命令权限」覆盖。帮助系统会根据元数据在**二级/三级帮助图**中展示**当前生效**的权限文案。

实现代码位于 `src/common/cmd_perm/`。

## 权限等级

| 配置值 | 含义（简述） |
|--------|----------------|
| `everyone` | 不额外限制（仍受 NoneBot 事件类型、私聊/群等约束） |
| `bot_moderator` | 号主：以 **`admins`** 等为准（见 `satisfies_command_permission`） |
| `group_moderator` | 群管/群主；私聊时回退为与号主侧判定等价 |
| `staff` | 群管/群主 **或** 号主一侧满足即可 |
| `superuser` | 仅超管 |

## 命令 ID 约定

- 形式建议：`{前缀}.{动作}`，例如 `help.help`、`blacklist.add`。
- `前缀` 通常与插件包名一致或为其逻辑简称；**同一命令在鉴权、registry、metadata、帮助里必须使用同一字符串**。
- 若未在任何默认表中登记，WebUI 矩阵可能不列出该命令（仍以运行时 `permission_for_command` 为准）。

## 代码里如何接入

### 命令 / Matcher 权限

```python
from src.common.cmd_perm import permission_for_command

on_command("示例", permission=permission_for_command("my_plugin.do_something"))
```

当前 NoneBot 版本**禁止** `Permission & Permission`（会抛 `RuntimeError`）。若命令必须限定在 **OneBot V11 群消息**或**私聊**上，请使用合并后的 helper，勿写 `permission.GROUP & permission_for_command(...)`：

```python
from src.common.cmd_perm import (
    group_message_permission_for_command,
    private_message_permission_for_command,
)

on_command("群内示例", permission=group_message_permission_for_command("my_plugin.in_group"))
on_command("私聊示例", permission=private_message_permission_for_command("my_plugin.in_private"))
```

### 在消息处理中手动判断

```python
from src.common.cmd_perm import satisfies_command_permission

if not await satisfies_command_permission(bot, event, "my_plugin.do_something"):
    return
```

## 全局默认表 `registry`

- 文件：`src/common/cmd_perm/registry.py` 中 `DEFAULT_COMMAND_PERMISSIONS`。
- 作用：为尚未在插件 metadata 中声明的命令提供**兜底默认等级**；`resolved_level` 会结合覆盖配置算出最终等级。
- 新插件：若希望 WebUI 与帮助一致展示，**至少**在下列之一中给出默认：
  - 本插件 `PluginMetadata.extra["command_permissions"]`（推荐，与展示名写在一起），或
  - `DEFAULT_COMMAND_PERMISSIONS` 增加一条（适合跨插件共用 ID 或历史兼容）。

## 插件 metadata：`extra["command_permissions"]`

在 `PluginMetadata(..., extra={...})` 中增加列表，每项为字典，字段如下：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 命令 ID；兼容别名 `command_id` |
| `label` | 否 | WebUI 与合并逻辑使用的展示名；缺省为 `id` |
| `default` | 否 | 默认等级；兼容 `default_level`；缺省为 `everyone`；非法值按 `everyone` |

与 `DEFAULT_COMMAND_PERMISSIONS` 的合并规则：**以 registry 为底，各插件 metadata 中同 `id` 的 `default` 覆盖底表**。解析结果带进程内缓存；修改 Python 源码后需重启进程（或触发 `clear_cmd_perm_cache` / `clear_merged_defaults_cache` 一类清理逻辑，一般随 Bot 重启即可）。

## 帮助菜单：`menu_data` 与动态权限文案

帮助图展示（用户向）：

| 字段 | 谁看 | 含义 |
|------|------|------|
| **`trigger_condition`** | 用户 | **怎么说**：完整口令或可见操作说明（如 `牛牛长草`、`牛牛决斗 @对手`） |
| **`trigger_scene`** | 用户 | **场景**：`私聊` / `群内` / `自动`（可选；也可写在括号里由程序解析） |
| **`trigger_method`** | 维护者 | 实现方式（`on_cmd`、`on_message` 等），**不出现在帮助图** |
| **`help_audience`** | 维护者 | 默认 `user`；`maintainer` 时不进入帮助图（HTTP、WebUI 等） |
| **`brief_des` / `detail_des`** | 用户 | 简介 / 详情页「怎么用」 |
| **`command_permission(s)`** | 用户 | 映射为帮助表「何人可用」 |

**不要**把 `on_message`、`on_cmd` 写在 `trigger_condition` 里——那是实现细节，不是用户要发的内容。

### 写法约定

1. **`PluginMetadata.usage`**：分步说明**怎么用**；不写部署配置、环境变量、URL 生成方式。帮助图为图片，**勿写**「复制」「粘贴」等。**勿在 `usage` 里写权限脚注**——「何人可用」由帮助图自动展示。
   - 每行：`口令或同义口令 — 说明`（分隔符用中文破折号 `—`，同义口令用 ` / ` 分隔）。
   - 占位：`〈插件名〉`、`〈QQ号〉`；可选参数：`[别名]`、`[@用户]`。
   - **编号**：用 `join_usage(usage_line(...), ...)` 拼接；**2 条及以上自动加** `1.` `2.` …，仅 1 条时不编号；`numbered=False` 可强制无序号。
   - 维护者向 HTTP 插件同样遵循上述规则。
   - 辅助函数：`metadata_text.usage_line`、`metadata_text.join_usage`。
2. **`description`**：一句陈述功能，句号结尾；避免多余感叹号。
3. **`trigger_condition`**：用户可见口令原文；自动功能写「新人入群」等，`trigger_scene` 为 `自动`。
4. **`trigger_scene`**：仅 `群内` / `私聊` / `群内或私聊` / `自动`（常量见 `metadata_text.SCENE_*`）。
5. **`brief_des`**：短句动宾，一般不加句号（约 8～20 字）。
6. **`detail_des`**：一至两句；用户口令用「」；不写权限角色（由帮助表展示）。
7. **`command_permission`** / **`command_permissions`**：与 `permission_for_command` 的 ID 一致。

与 cmd_perm **无关**的业务前提（例如须**本 Bot 账号**为 QQ 群管）：写在 `detail_des` 或 `docs/plugins/<name>/README.md`。

`docs/plugins/*/README.md` 面向维护者，结构见 [插件文档模板](../../plugins/TEMPLATE.md)；可用表格列出**代码默认等级**，并注明实际以 WebUI 为准。

`PluginMetadata` 共用常量：`src/common/cmd_perm/metadata_defaults.py`（`PLUGIN_HOMEPAGE`、`PLUGIN_EXTRA_VERSION`、`PLUGIN_MENU_TEMPLATE`）。

**帮助解析别名**：`牛牛帮助 远控` 等口令除包名、展示名外，还可匹配 `src/plugins/help/plugin_aliases.py` 中的简称；单插件可在 `extra["help_aliases"]` 追加。匹配时会忽略空格与英文大小写。

`trigger_condition_with_effective_perm` 仍导出，行为与 `raw_trigger_condition` 相同（兼容旧代码）。

### 与 `on_command` 对齐

`menu_data` 里填写的命令 ID 必须与 `permission_for_command(...)` / `satisfies_command_permission(..., "...")` 使用的 ID **一致**，否则帮助上的「何人可用」与实际鉴权不一致。

## 运行中覆盖：WebUI 与 webui.json

- WebUI **「通用配置 → 命令权限」** 写入 `data/pallas_config/webui.json`（键 `PALLAS_COMMAND_PERMISSION_OVERRIDES`，JSON：命令 ID → 等级）。
- 亦可通过环境变量或 `pallas.toml` `[env]` 注入同名键；**WebUI 落盘优先级最高**。
- 保存后会清理配置缓存，**覆盖值通常无需重启 Bot 即可生效**。
- 修改 **Python 中的默认等级或 `command_permissions` 列表**：需重新加载插件或重启进程。

## 相关源文件

| 路径 | 职责 |
|------|------|
| `src/common/cmd_perm/check.py` | `permission_for_command`、`group_message_permission_for_command`、`private_message_permission_for_command`、`satisfies_command_permission` |
| `src/common/cmd_perm/config.py` | 从环境读取覆盖、`get_cmd_perm_config`、`clear_cmd_perm_cache` |
| `src/common/cmd_perm/registry.py` | 合法等级、`DEFAULT_COMMAND_PERMISSIONS`、`resolved_level` |
| `src/common/cmd_perm/schema.py` | 合并 metadata 默认、WebUI `command_perm_ui` 数据结构 |
| `src/common/cmd_perm/menu_display.py` | `raw_trigger_condition`、`effective_permission_avail_text`、帮助用权限文案 |
| `src/common/webui/env_sections.py` | `cmd_perm` 配置段与 payload 附加字段 |
| `src/common/cmd_perm/declare.py` | `command_perm_row` / `command_perm_list` 声明辅助 |
| `src/common/cmd_perm/metadata_defaults.py` | `PLUGIN_HOMEPAGE`、`PLUGIN_EXTRA_VERSION`、`PLUGIN_MENU_TEMPLATE` |
| `src/common/cmd_perm/metadata_text.py` | `usage_line`、`join_usage`、`SCENE_*` |
| `src/plugins/help/markdown_generator.py` | 二/三级帮助 Markdown 生成 |

## 自检清单（新插件上线前）

- [ ] 所有需独立配置权限的入口是否都使用**同一套**命令 ID？
- [ ] `extra["command_permissions"]` 是否包含这些 ID 及可读 `label`？
- [ ] `menu_data` 中带权限的条目是否已配置 `command_permission` 或 `command_permissions`，且 `trigger_condition` 无静态权限描述（权限由帮助「何人可用」列展示）？
- [ ] 若命令仍需全局兜底：是否已在 `DEFAULT_COMMAND_PERMISSIONS` 或本插件 metadata 中声明默认等级？
- [ ] `usage` 是否未写死权限角色、且无多余权限脚注？`homepage` 是否为 `PLUGIN_HOMEPAGE`？
- [ ] `extra` 是否含 `menu_template: default`（维护者向 HTTP 功能用 `help_audience: maintainer`）？
