# {展示名}（`{包名}`）

{一句话说明插件做什么。句号结尾。}

`PluginMetadata` 文案格式见 [cmd_perm · 写法约定](../common/cmd_perm/README.md) 与 `metadata_text.py`（`usage_line` + `join_usage` 自动编号、`SCENE_*` 等）。

## 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| … | 群内 / 私聊 / 自动 | … |

> 游戏内完整说明与「何人可用」：**牛牛帮助** → 本插件 → 功能详情。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `{包名}.…` | everyone / staff / … |

无独立命令权限的被动功能可删本节。

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| … | … | … |

字段以 [`src/plugins/{包名}/config.py`](../../src/plugins/{包名}/config.py) 为准（**无 `config.py` 的插件删本节**）；可在 WebUI **插件** 或 **通用配置** 中修改，落盘 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| … | … |

## 实现

[`src/plugins/{包名}/`](../../src/plugins/{包名}/)

---

**维护者**：`PluginMetadata` 与 `menu_data` 写法见 [cmd_perm](../../common/cmd_perm/README.md)；勿把部署细节写进 `usage` / `trigger_condition`。
