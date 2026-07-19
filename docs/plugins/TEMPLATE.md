<p align="center">
  <img src="assets/brand-avatar.png" width="220" height="220" alt="{展示名}">
</p>

<h1 align="center">{展示名} {包名}</h1>

<p align="center">{一句话说明插件做什么。句号结尾。}</p>

<p align="center">
  <img alt="{插件类型}" src="https://img.shields.io/badge/{插件类型}-FE7D37">
  <img alt="WebUI 插件商店" src="https://img.shields.io/badge/WebUI-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/{安装命令}-586069">
</p>

`PluginMetadata` 文案格式见 [cmd_perm · 写法约定](../common/cmd_perm/README.md) 与 `metadata_text.py`（`usage_line` + `join_usage` 自动编号、`SCENE_*` 等）。

## 安装方式

{核心插件可写“默认加载，无需单独安装。”；官方插件统一写“控制台插件商店”与 `uv run pallas ext install pallas-plugin-...`；已内核化能力写“随主仓提供，无独立安装步骤。”}

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| … | 群内 / 私聊 / 自动 | … |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `{包名}.…` | 所有人 / 群管或号主 / … |

无独立命令权限的被动功能可删本节。

## 配置项

> 可在控制台对应插件页中修改。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| … | … | … |

字段以 [`packages/{包名}/config.py`](../../packages/{包名}/config.py) 为准（**无 `config.py` 的插件删本节**）；配置保存后会落盘到 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| … | … |

## 实现

源码位置：[`packages/{包名}/`](../../packages/{包名}/)

> 官方插件可改写为扩展仓对应目录，例如 `src/pallas_plugin_xxx/`。

关键文件：

- [`__init__.py`](../../packages/{包名}/__init__.py)：{注册插件与命令入口。}
- [`commands.py`](../../packages/{包名}/commands.py) / [`handlers.py`](../../packages/{包名}/handlers.py)：{处理用户触发与主要流程。}
- [`config.py`](../../packages/{包名}/config.py)：{定义插件配置。无则删。}

实现要点：

- {用 2 到 4 条说明功能是怎么组织的。}
- {解释用户看不见但会影响行为的关键边界。}

可按需补充简短代码片段或说明，但不要把大段实现细节堆进 README。

## 相关链接

- [插件文档索引](../README.md)
- [命令权限说明](../common/cmd_perm/README.md)
- {相关通用能力文档 / 相关插件文档（按需保留）}
