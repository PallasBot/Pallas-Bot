# 插件结构与约定

本文是 [插件目录约定](../../architecture/plugin-convention.md) 的**开发向**说明：新建或改动插件时如何组织文件与数据。

## 最小结构

```
my_plugin/
├── __init__.py      # 入口：PluginMetadata、Matcher 注册
└── config.py        # Pydantic 配置 + 可选 WebUI 热重载
```

## 按需扩展

复杂度上升时，**优先按业务能力拆文件**，而非一次性引入多层目录：

| 文件 / 目录 | 何时使用 |
| --- | --- |
| `handlers.py` | 命令 / 消息 handler 较多 |
| `models.py` | 领域数据结构 |
| `services/` | 可复用且持续增长的业务逻辑 |
| `repositories.py` | 持久化访问封装 |
| 语义化模块名 | 如 `speaker.py`、`ban_manager.py`、`renderer.py` |

原则：

1. `__init__.py` 避免堆积大段实现
2. 配置与默认值集中在 `config.py`
3. 单文件过长时按职责拆分，避免「超大单文件」
4. 插件内私有逻辑放插件目录；**跨插件复用**再提取到 `src/common/`

## 路径与持久化

| 类型 | 位置 | 访问方式 |
| --- | --- | --- |
| 运行期数据 | `data/<plugin_name>/...` | `plugin_data_dir("my_plugin")` |
| 静态资源 | `resource/...` | `resource_dir("subdir")` |

使用 `src/common/paths/` 提供的 helper，**不要**硬编码相对路径字符串。

示例（仓库内）：

- `greeting`：`plugin_data_dir("greeting")`、`resource_dir("voices")`
- `help`：`plugin_data_dir("help")`、样式在 `resource/styles/`
- `request_handler`：申请缓存在 `data/request_handler/`

## 命名

- 包名 / 目录：**小写 + 下划线**，与 `src/plugins/<name>` 一致
- 文件名：语义化（`handlers.py`、`ban_manager.py`），避免无意义缩写
- 新增函数：非必要**不要**以下划线 `_` 开头

## WebUI 与命令权限

| 需求 | 做法 |
| --- | --- |
| 控制台可改、保存即生效 | `install_hot_reload_config`（见 [WebUI 插件配置](../../common/webui/README.md)） |
| 可配置命令权限 | `permission_for_command` + `extra["command_permissions"]`（见 [cmd_perm](../../common/cmd_perm/README.md)） |
| 帮助文案 | `usage_line` / `join_usage` / `SCENE_*`；权限不写死在 `usage` 里 |

## 测试

- 位置：`tests/plugins/<plugin_name>/`
- 新增行为优先附带最小测试；可参考 `tests/plugins/blacklist/`、`tests/plugins/repeater/`
- 运行：`uv run pytest tests/plugins/<name>/`

## 文档

- 用户向：`docs/plugins/<name>/README.md`
- 开发者默认权限可在文档表格列出，并注明以 WebUI / cmd_perm 为准
- 模板：[TEMPLATE.md](../../plugins/TEMPLATE.md)

## 迁移策略

历史插件不要求一次性重构。约定对**新增插件**与**正在修改的插件**即时生效；每次 PR 只做一类整理（拆文件 / 补文档 / 补测试）。

## 下一步

[插件进阶能力](advanced.md) · [插件开发入门](getting-started.md)
