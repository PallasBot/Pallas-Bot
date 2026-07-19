# 配置与 WebUI

插件侧配置接入：热载模型、通用段与仓边界。合并顺序与读取 API 见 [配置存储](/developer/architecture/config-storage)。

## 事实

| 项 | 值 |
| --- | --- |
| 启动层主配置 | `config/pallas.toml` |
| 遗留兼容 | `.env` / `.env.{ENVIRONMENT}`（只读合并，不新增主能力键） |
| 运行态落盘 | `data/pallas_config/webui.json`（最高优先级） |
| 插件页接法 | `pallas.api.config.install_hot_reload_config` |
| 横切段 | 通用配置段（权限、gateway、scrub、ingress…） |

## 插件页（推荐）

```python
from pydantic import BaseModel, Field

from pallas.api.config import install_hot_reload_config


class Config(BaseModel, extra="ignore"):
    enable: bool = Field(default=True, description="是否启用。")


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

```python
cfg = get_config()
if not cfg.enable:
    return
```

UI 字段元数据见 [DynamicConfigPanel](dynamic-config-panel.md)。

## 通用配置段

配置为平台横切项（多插件共享、非单插件私有页）时接到通用段，禁止自造存储点。

## 热载边界

| 变更类型 | 期望 |
| --- | --- |
| 开关 / 文案 / 频率 / 策略枚举 | 应热载 |
| Python 逻辑 / 复杂启动 / 深层结构 | 进程重启；勿伪装成热载 |

## 仓边界

| 改动 | 仓库 |
| --- | --- |
| 表单 UI、路由、样式 | `Pallas-Bot-WebUI` |
| 配置模型、保存、热载、API | 主仓 |

## 新增配置项决策

| 问题 | 选项 |
| --- | --- |
| 启动层还是运行态？ | `pallas.toml` vs 插件页 / 通用段 |
| 是否 WebUI 可改？ | 是 → 热载模型；否 → 启动层 |
| 单插件还是横切？ | 插件页 vs 通用段 |
| 分片下是否全 worker 一致？ | MUST 走统一读取入口 |

## 禁止

| MUST NOT |
| --- |
| 为新主能力新增根目录 `.env` 键 |
| 假设仅改 `pallas.toml` 即运行态终值 |
| 模块 import 时缓存 `get_config()` |
| 插件私有并行配置文件 |

## 相关

- [配置存储](/developer/architecture/config-storage)
- [Golden Plugin](golden-plugin.md)
- [Reload 与 Activation](reload-and-activation.md)
- [WebUI 底层](/common/webui)
