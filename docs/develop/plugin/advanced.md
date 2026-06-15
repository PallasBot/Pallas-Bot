# 插件进阶能力

在掌握 [入门](getting-started.md) 与 [结构约定](structure.md) 后，按需接入下列横切能力。

## 命令权限（cmd_perm）

将命令鉴权抽象为可配置等级；默认在代码声明，运行中可由环境变量或 WebUI「通用配置 → 命令权限」覆盖。帮助图根据 metadata **动态**展示「何人可用」。

### 接入步骤

1. 在 `PluginMetadata.extra["command_permissions"]` 声明命令 ID 与默认等级
2. Matcher 使用 `permission_for_command("my_plugin.action")`
3. 群消息 / 私聊限定使用合并 helper（**禁止** `Permission & Permission`）：

```python
from src.common.cmd_perm import (
    group_message_permission_for_command,
    private_message_permission_for_command,
)

on_command("群内", permission=group_message_permission_for_command("my_plugin.in_group"))
```

4. 消息流中手动判断：`await satisfies_command_permission(bot, event, "my_plugin.action")`

### 文案禁忌

- `usage`、`trigger_condition` **不写死**「仅群管」「默认群主」等
- 与发送者权限无关的条件（如「本 Bot 须为 QQ 群管」）写在 `detail_des` 或插件 README

完整字段与自检清单：[cmd_perm 接入说明](../../common/cmd_perm/README.md)

## WebUI 配置热重载

控制台通过 `data/pallas_config/webui.json` 统一读写插件配置。

```python
from pydantic import BaseModel, Field
from src.common.webui import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    threshold: int = Field(default=3, description="触发阈值。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

- 业务代码始终 `get_config()`，保存后自动 reload，**无需重启**
- 复杂解析：传入 `parse_env_value`（参考 `draw/config.py`）
- 除 Config 外还有运行时单例：传入 `on_reload`
- 已有自定义缓存逻辑：登记 `plugin_webui_registry`

详见 [WebUI 插件配置](../../common/webui/README.md)

## 消息审查（message_scrub）

复读、做梦等插件的入站消息可先经统一审查过滤（广告、风控等）。插件侧按 [message_scrub](../../common/message_scrub/README.md) 注册 hook，避免在各插件重复实现。

## 跨插件与 common

可复用能力优先沉淀到 `src/common/`：

| 包 | 典型用途 |
| --- | --- |
| `src/common/config/` | 群/用户/Bot 级配置 |
| `src/common/cmd_perm/` | 命令权限 |
| `src/common/webui/` | 控制台配置热重载 |
| `src/common/paths/` | `data/`、`resource/` 路径 |
| `src/common/db/` | 数据库访问 |
| `src/common/shard/` | 分片 presence、协调 |

引入 common 时保持**语义单一**，避免把某一插件的业务泄漏到 common。

## 站点自有插件与覆盖

| 场景 | 做法 |
| --- | --- |
| 私有功能、不提交主仓 | `local/plugins/<name>/` + `extra_plugin_dirs` |
| 整包替换主仓同名插件 | `local/plugins/<原名>/`（加载优先于 `src/plugins/`） |
| 只改主仓少量核心文件 | `local/patches/*.patch` 或提 PR |

见 [站点定制与更新](../../architecture/site-customization-and-updates.md)

## 分片部署注意

- hub / worker 共用 `data/` 卷时，WebUI 配置与各插件 `data/<name>/` 一致
- worker 侧 `get_*_config()` 可按磁盘 mtime 拾取新配置
- 涉及 Bot 连接、presence 时使用 `src/common/shard/` 提供的 API，勿假设单进程内存全局状态

见 [多进程分片](../../architecture/bot_process_sharding.md)

## 日志

使用 NoneBot / loguru 风格 `logger`，占位符用 `{}` 或 f-string：

```python
logger.info(f"bot [{bot_id}] action in group [{group_id}]")
```

## AI 与外部服务

- 对话 / 唱歌 / TTS 等扩展见 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 与文档站「AI 扩展」
- 画画、MAA 等网关字段见 WebUI「服务网关」与 `src/common/webui/service_gateways_section.py`

## 测试与排障

- 单元测试：`tests/plugins/<name>/`，必要时 mock `Bot` / 数据库
- 本地配置：勿提交 `config/pallas.toml`、`data/`
- 部署问题：[FAQ](../../FAQ.md)

## 相关文档

- [插件开发入门](getting-started.md)
- [插件结构与约定](structure.md)
- [贡献与提交流程](../workflow.md)
