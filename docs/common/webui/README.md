# WebUI 配置与热重载

控制台（`pallas_webui`）通过 **`data/pallas_config/webui.json`** 读写插件与通用配置（主配置见 `config/pallas.toml`）。`src/console/webui/` 供插件作者接入「保存后立即生效」。

## 配置落盘

| 入口 | 写入 |
| --- | --- |
| **插件** 页 | `webui.json` → `env`，字段名大写 |
| **通用配置** 各段 | 同上；部分段有专用 payload（语料联邦、联邦控制、服务网关） |
| 合并顺序 | `pallas.toml` → 遗留 `.env` → `webui.json`（**WebUI 最高**） |

命令权限说明见 [cmd_perm](../cmd_perm/README.md)。

**热重载分级**（配置 / 元数据 / 代码）：见 [Reload 与 Activation](../../developer/plugin-development/reload-and-activation.md)。插件可在 `extra["reload_policy"]` 声明期望粒度（默认 `config_only`）。

### 三级与插件作者

| 级别 | 改什么 | 要不要适配 | 生效方式 |
| --- | --- | --- | --- |
| **配置** | `config.py` 字段 | 接 `install_hot_reload_config`（见下） | WebUI 插件页保存后立即 reload |
| **元数据** | `extra` 内 help、ingress、`command_permissions` 等声明 | 可选：设 `reload_policy: metadata` | 同上保存时重建 help/ingress 等索引（不卸载 matcher） |
| **代码** | Python 模块 | 无热载 | 须重启 Bot |

未声明 `reload_policy` 时等价于 `config_only`：只热载 `config.py`，**改 extra 声明后仍须重启**。

```python
extra={
    ...
    "reload_policy": "metadata",  # 频繁改 help/ingress 声明且不想重启时
}
```

`full` 表示期望代码级重载；当前实现仍只做到元数据索引重建，改代码请重启。

## 插件接入热重载

在 `config.py` 末尾：

```python
from pydantic import BaseModel, Field
from src.console.webui import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    my_enable: bool = Field(default=False, description="是否启用某功能。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_my_config = plugin_webui.get
```

业务代码统一 `get_my_config()`，勿缓存 import 时快照。可选 `parse_env_value`、`on_reload`（见 [`draw`](../../plugins/draw/README.md)）。

未使用热重载时仍可用 `get_plugin_config(Config)`，但进程内值需**重启**才与磁盘一致。

## 通用配置段

在 [`env_sections.py`](../../../src/console/webui/env_sections.py) 的 `_registered_sections()` 注册。已 `install_hot_reload_config` 的插件经注册表读当前值；保存时尝试 `reload_plugin_config`。

| 段 ID | 标题 | 说明 |
| --- | --- | --- |
| `cmd_perm` | 命令权限 | 覆盖矩阵 |
| `control_plane` | 联邦控制 | 专用 payload |
| `corpus_federation` | 语料联邦 | 专用 payload |
| `community_stats` | 在线统计与社区主站（插件 `pb_stats`） | 专用 payload |
| `ingress_fanout` | 入站：全员同响口令 | |
| `repeater_learn` | 复读：后台语料学习 | |
| `message_scrub` | 消息审查与入站过滤 | 4.0 默认开启 |
| `service_gateways` | 外部服务地址 | 画画 / MAA / 点歌 + 连通检测 |
| `pallas_webui` / `pallas_protocol` / `help` | 各插件子集 | |

## 包内文件

| 文件 | 职责 |
| --- | --- |
| `plugin_config.py` | `install_hot_reload_config` |
| `registry.py` | 按插件名 get / reload |
| `plugin_api.py` | 插件页 GET/PUT |
| `env_sections.py` | 通用配置段注册 |
| `field_labels.py` / `field_help.py` | WebUI 中文名与说明 |
| `service_gateways_section.py` | 网关聚合与检测 API |

## 参考插件

| 插件 | 说明 |
| --- | --- |
| [sing](../../plugins/sing/README.md) | 标准热重载 |
| [draw](../../plugins/draw/README.md) | 自定义解析 + `on_reload` |
| [pallas_webui](../../plugins/pb_webui/README.md) | HTTP 路由层 |

## 实现

[`src/console/webui/`](../../../src/console/webui/) · 路由薄层 [`extended_api.py`](../../../src/plugins/pb_webui/extended_api.py)

## API 契约（按域）

REST 路径、鉴权、写操作与热重载行为见 [api/README.md](api/README.md)（与 WebUI `consoleApi.ts` / OpenAPI 对齐）。
