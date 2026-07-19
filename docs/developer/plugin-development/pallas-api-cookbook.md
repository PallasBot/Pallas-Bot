# pallas.api Cookbook

扩展作者稳定入口。实现在 `pallas.core` / `pallas.product`。社区扩展只允许 import `pallas.api.*`（及模板约定的包内模块）；官方插件可用 `pallas.api.platform`（见 [Platform API](/developer/reference/platform-api)）。

## 安装 pallas-core

| 场景 | 做法 |
| --- | --- |
| 主仓全仓开发 | 根目录 `uv sync`；无需单独装包 |
| 独立扩展仓（wheel） | `./scripts/build_core.sh` 后 `uv pip install build/pallas-core/dist/pallas_core-*.whl` |
| PyPI | `uv add "pallas-core>=4.0.0,<5.0.0"`（随主仓 `v*` tag 发布，见 [pallas-core 发版](../../develop/extension-pypi-publish.md#pallas-core主仓)） |

模板：`templates/pallas-plugin-extension/pyproject.toml`。

## 命令与 handler

```python
from pallas.api.commands import (
    PluginCommand,
    PluginHandlerContext,
    bind_alias_handlers,
    group_command,
    message_command,
    private_command,
)
```

## 配置与 WebUI 热载

```python
from pallas.api.config import install_hot_reload_config
```

## 权限与冷却

```python
from pallas.api.perm import (
    DEFAULT_COMMAND_PERMISSIONS,
    VALID_LEVELS,
    group_message_permission_for_command,
    satisfies_command_permission,
)
from pallas.api.limits import is_command_cooldown_ready, refresh_command_cooldown
```

## 帮助元数据

```python
from pallas.api.metadata import join_usage, usage_line, SCENE_GROUP
```

## 路径与存储

```python
from pallas.api.paths import plugin_data_dir, resource_dir
from pallas.api.storage import get_plugin_storage, set_plugin_storage
```

## 用户可见错误（脱敏）

```python
from pallas.api.messages import sanitize_user_visible_message, user_failure_reply
```

## 连通探测（WebUI 健康）

```python
from pallas.api.probe import ServiceProbeResult, format_probe_lines
```

## 参考图 / 媒体（画图类）

```python
from pallas.api.media import resolve_reference_inline_urls, bytes_from_reference_token
```

## 消息审查

```python
from pallas.api.safety import is_message_scrub_blocked_async
```

## AI 运行时健康（只读）

插件侧熔断/降级应读 AI `/health` 缓存，勿自建 parallel circuit：

```python
from pallas.api.ai_runtime_health import image_runtime_circuit_is_open
```

## 平台协作（官方插件 / 内置）

`pallas.api.platform`：多 Bot、分片、callback。社区插件默认禁止。导出表见 [Platform API](/developer/reference/platform-api)。

## 禁止 import

| 区域 | 原因 |
| --- | --- |
| `pallas.core.*`（除 api re-export） | 内部实现 |
| `pallas.product.*` | 产品域 |
| `pallas.console.*` | WebUI 维护者向 |
| `pallas.product.llm.client` 直调 | 应走 capability 信封 / AI 仓 |

CI：`tools/check_plugin_imports.py` 与 `community_plugin_author check` 会对齐上述边界。

## 相关

- [插件开发入门](getting-started.md)
- [Golden Plugin](golden-plugin.md)
- [仓库布局与公开 API](/developer/reference/repo-layout)
