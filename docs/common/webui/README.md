# WebUI 插件配置与热重载

控制台（`pallas_webui`）通过统一 `data/pallas_config/webui.json` 读写插件配置（主配置见 `config/pallas.toml`）。本包 `src/common/webui/` 供**插件作者**接入「保存后立即生效」，无需再改 `extended_api.py`。

## 目录结构

| 文件 | 职责 |
|------|------|
| `plugin_config.py` | `install_hot_reload_config`：缓存 + 从磁盘配置重读 + 注册热重载钩子 |
| `registry.py` | 按插件模块名查找 `get` / `reload` |
| `plugin_api.py` | `GET/PUT /plugins/{name}/config` 的合并、落盘与 reload |
| `env_sections.py` | 「通用配置」分段（`message_scrub`、`cmd_perm`、部分插件、`service_gateways`） |
| `service_gateways_section.py` | 画画 / MAA / 唱歌网关集中编辑与连通检测 API |
| `gateway_fields.py` | 服务网关段字段名常量 |

命令权限声明见 [`cmd_perm`](../cmd_perm/README.md) 与 `src/common/cmd_perm/declare.py`。

## 快速接入（推荐）

在插件 `config.py` 末尾增加：

```python
from pydantic import BaseModel, Field
from src.common.webui import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    my_enable: bool = Field(default=False, description="是否启用某功能。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_my_config = plugin_webui.get
reload_my_config = plugin_webui.reload
```

业务代码统一使用 `get_my_config()`，不要缓存模块 import 时的配置快照。

WebUI 在控制台「插件」页保存该插件配置后，会写入 `webui.json` 并自动调用 `reload`，**无需重启 Bot**。分片部署时 hub 与 worker 共用 `data/` 卷即可；worker 在下次 `get_*_config()` 时按磁盘 mtime 自动拾取新配置。

### 自定义环境值解析

列表 / 字典 / 嵌套模型等若需特殊解析，传入 `parse_env_value`：

```python
def parse_my_env_value(name: str, raw: str, ann: Any) -> Any:
    ...

plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    parse_env_value=parse_my_env_value,
)
```

可参考 [`src/plugins/pallas_image/config.py`](../../../src/plugins/pallas_image/config.py)。

### 热重载后刷新运行时单例

若除 `Config` 外还有内存中的运行时对象（如画图并发限制），传入 `on_reload`：

```python
def on_my_config_reload(cfg: Config) -> None:
    my_runtime.reload(cfg)

plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_my_config_reload,
)
```

可参考 [`src/plugins/pallas_image/config.py`](../../../src/plugins/pallas_image/config.py) 中的 `on_pallas_image_config_reload`。

## 命令权限（与配置分开）

在 `PluginMetadata.extra` 中声明可配置权限，matcher 使用 `permission_for_command`：

```python
from src.common.cmd_perm import (
    command_perm_list,
    command_perm_row,
    permission_for_command,
)

__plugin_meta__ = PluginMetadata(
    ...
    extra={
        "command_permissions": command_perm_list(
            command_perm_row("my_plugin.action", "执行某操作", "staff"),
        ),
    },
)

my_cmd = on_command("某命令", permission=permission_for_command("my_plugin.action"))
```

覆盖值写在环境变量 `PALLAS_COMMAND_PERMISSION_OVERRIDES`（JSON），由 WebUI「通用配置 → 命令权限」编辑；保存后调用 `clear_cmd_perm_cache()`，通常无需重启。

## 环境变量命名

- 控制台「插件」页 PUT：字段名 **大写** 写入 `webui.json` 的 `env`（如 `my_enable` → `MY_ENABLE`）。
- 与 NoneBot 插件配置习惯一致；`install_hot_reload_config` 通过 `merged_repo_settings_upper()` 读盘。

## 不需要热重载时

仍可使用 `get_plugin_config(Config)`。WebUI 仍能改 `webui.json`，但进程内值需**重启 Bot** 后才与磁盘一致。

## 出现在「通用配置」页

若希望插件配置出现在「通用配置」列表（而非仅「插件」页），在 [`env_sections.py`](../../../src/common/webui/env_sections.py) 的 `_registered_sections()` 中增加 `_plugin_env_section_from_module(...)`。已 `install_hot_reload_config` 的插件会通过注册表读取当前值；保存段配置时会尝试 `reload_plugin_config`。

### 服务网关 / 连通性（`service_gateways`）

[`service_gateways_section.py`](../../../src/common/webui/service_gateways_section.py) 聚合 **牛牛画画** 网关字段、**MAA** 对外端点、**点歌** 主机与开关，对应键写入 `webui.json` 的 `env`（按插件分组到 `sections`）。WebUI 提供网关列表编辑器与 `POST /common-config/service_gateways/connectivity-check`（可按表单草稿探测，无需先保存）。各插件 **插件配置** 页保留完整参数与专用入口（如画画仅测画画网关）。

## 实现参考

| 插件 | 说明 |
|------|------|
| [`sing`](../../plugins/sing/README.md) | 标准 `install_hot_reload_config` |
| [`pallas_image`](../../plugins/pallas_image/README.md) | 自定义解析 + `on_reload` |
| [`pallas_webui`](../../plugins/pallas_webui/README.md) | 调用 `plugin_api` / `env_sections` 的 HTTP 层 |

## 相关源文件

- `src/common/webui/` — 本包
- `src/plugins/pallas_webui/extended_api.py` — 路由注册（宜保持薄，逻辑放在 `webui` 包内）
- `src/common/config/repo_settings.py` — `pallas.toml` + `webui.json` 合并读写
