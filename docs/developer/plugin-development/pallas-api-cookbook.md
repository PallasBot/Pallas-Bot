# pallas.api Cookbook

本页速查扩展作者稳定入口。实现在 `pallas.core` / `pallas.product`。社区扩展只允许 import `pallas.api.*`（及模板约定的包内模块）；官方插件可用 `pallas.api.platform`（见 [Platform API](/developer/reference/platform-api)）。

先按 [Pallas API 总览](/developer/reference/pallas-api) 判断依赖边界；手把手最小插件见 [写第一个插件](first-plugin.md)。这里按主题找 import，不展开教程。

## 安装 pallas-core

| 场景 | 做法 |
| --- | --- |
| 主仓全仓开发 | 根目录 `uv sync`；无需单独装包 |
| 独立扩展仓（wheel） | `./scripts/build_core.sh` 后 `uv pip install build/pallas-core/dist/pallas_core-*.whl` |
| PyPI | `uv add "pallas-core>=4.0.0,<5.0.0"`（随主仓 `v*` tag 发布，见 [pallas-core 发版](../extension-pypi-publish.md#pallas-core主仓)） |

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

## 精确命令与统一运行时

`pallas.api.runtime` 为适合的声明式命令提供 `direct` 路径。它不是 matcher 的替代品，也不要求整个插件一次迁移。

| 命令形态 | 推荐路径 |
| --- | --- |
| 精确文本、单次处理、权限和副作用边界清晰 | `pallas.api.runtime` direct |
| 固定前缀、参数由 callback 继续解析 | `register_prefix_command_handler()` direct |
| 状态 matcher、复杂规则、`@` 语义、多步会话 | NoneBot matcher |
| 同一插件同时包含两类命令 | 按命令混合接入 |

最小注册示例：

```python
from pallas.api.runtime import (
    DirectCommandContext,
    DirectCommandResult,
    register_exact_command_handler,
    reply,
)


async def handle_ping(context: DirectCommandContext) -> DirectCommandResult:
    return reply(f"pong: {context.command_text}")


PING_DECLARATION = register_exact_command_handler(
    handler_id="example.ping.direct",
    module="example",
    commands=("牛牛 ping",),
    command_id="example.ping",
    execute=handle_ping,
)
```

固定前缀命令使用 `register_prefix_command_handler()`，callback 收到的 `context.command_text` 仍是完整文本：

```python
from pallas.api.runtime import register_prefix_command_handler

SING_DECLARATION = register_prefix_command_handler(
    handler_id="example.sing.direct",
    module="example",
    prefixes=("牛牛唱歌", "帕拉斯唱歌"),
    command_id="example.sing",
    execute=handle_sing,
)
```

前缀只做框架内置的 `startswith` 匹配，不支持自定义 predicate。同一模块的精确文本与前缀、两个互相包含的前缀不能分属不同 handler；有歧义的后注册声明会被跳过并保留 matcher 路径。

`command_id` 继续使用插件已有的权限 ID；运行时会按同一 ID 检查命令权限。声明应在插件加载时注册，代码热载卸载时由运行时按 `module` 清理。

### 处理结果

| API | 用途 |
| --- | --- |
| `reply(message)` | 返回一条由运行时统一发送的回复。 |
| `DirectWorkJob(...)` | 提交可持久化、带幂等键的后台任务。 |
| `completion_effect(name, run, wait_for_completion=True)` | 在统一提交阶段执行异步效果；默认等待完成。 |
| `matcher_fallback(reason)` | 当前 direct handler 不适用且尚未产生副作用时，交回 matcher。 |
| `continue_matcher=True` | direct 已处理后仍允许 matcher 继续，用于确实需要两条路径协作的命令。 |

`matcher_fallback()` 的结果不能同时携带回复、任务或完成效果。副作用提交一旦开始，发送或任务可能已经被下游接受；此后即使发生错误也不会回落 matcher 重试，以免产生重复操作。

`continue_matcher` 可以在 `register_exact_command_handler()` 声明上设置，也可以由 `reply(..., continue_matcher=True)` 或 `DirectCommandResult` 针对单次结果设置。除非命令明确需要两套处理共同执行，否则保持默认 `False`。

对已完成状态更新和用户提示、但后续动作可延后的场景，使用 `completion_effect(..., wait_for_completion=False)`。运行时会统一创建后台任务；不要在插件 handler 内自行 `asyncio.create_task()`。后台效果不保证与后续同群消息严格串行，不能用于依赖该顺序的状态变更、重复敏感操作或必须向用户同步报告失败的流程；这些情况应保持等待，或改为 `DirectWorkJob`。

### 外置 durable work handler

扩展可以通过 Python entry point 向 work auxiliary 注册任务 handler：

```toml
[project.entry-points."pallas.work_handlers"]
example = "pallas_plugin_example.work:work_handlers"
```

provider 返回 `kind -> async handler` 映射；handler 接收 `DirectWorkJob.payload`，成功时返回 `None`，或返回需要投递 Bot 动作的 `DirectWorkResult`：

```python
from pallas.api.runtime import DirectBotAction, DirectWorkResult


async def generate(payload: dict) -> DirectWorkResult:
    message = await build_message(payload)
    return DirectWorkResult(
        actions=(
            DirectBotAction(
                action="send_group_msg",
                target_bot_id=int(payload["bot_id"]),
                payload={"group_id": int(payload["group_id"]), "message_text": message},
            ),
        )
    )


def work_handlers():
    return {"example.generate": generate}
```

内置 handler 优先于外置 entry point；重复 kind 与无效 provider 会被隔离并记录。handler 在返回结果前抛错按队列策略重试；`DirectWorkResult` 开始提交后若失败则直接进入 dead letter，避免重跑造成重复发送。因此耗时计算应在 handler 内完成，可见动作只放进返回结果，不要由 handler 自己调用 Bot API。

公共契约止于 `pallas.api.runtime`。插件不要导入 `pallas.core.platform.message_runtime`；内部 planner、registry 和 committer 可以独立演进。维护者可继续阅读[统一消息入口架构](/developer/architecture/message-runtime)。

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

插件侧对**媒体**能力的熔断 / 降级应读 AI `/health` 缓存，勿自建 parallel circuit。普通聊天走 Bot Provider，不依赖该健康面。

```python
from pallas.api.ai_runtime_health import image_runtime_circuit_is_open
```

## LLM Provider（按需调用）

插件若确需调用已配置 Provider 的兼容 API，可只解析对应 Provider 的已配置线路；普通聊天仍应交给 Bot 的 Agent / Provider 路径，不要在插件内重建聊天管线。

```python
from pallas.api.llm import (
    find_provider,
    resolve_provider_api_key,
    resolve_provider_base_url,
)

provider = find_provider("my-provider")
if provider:
    api_key = resolve_provider_api_key(provider)
    base_url = resolve_provider_base_url(provider)
```

`find_provider()` 默认不返回已禁用 Provider；需要检查已配置但禁用的线路时传 `include_disabled=True`。密钥只用于实际求，勿写入日志或插件存储。

## 多 Bot 在线态

分片或多 Bot 插件在选择发送 Bot 前可查询集群连接态：

```python
from pallas.api.presence import bot_has_cluster_connection

if bot_has_cluster_connection(bot_id):
    await send_with_bot(bot_id)
```

健康隔离中的 Bot 会视为未在线；多 Bot 发送、claim 和代发等平台协作仍仅限 [Platform API](/developer/reference/platform-api)。

## 通用工具（按需）

`pallas.api.utils` 提供共享 HTTP 客户端、流式下载、私聊发送、GitHub Release 与邮件工具。只有工具与需求准确匹配时才 import，避免把它作为通用依赖桶：

```python
from pathlib import Path

from pallas.api.utils import HTTPXClient, sync_stream_download_to_file

response = await HTTPXClient.get("https://example.com/metadata.json")

# 仅在 work handler 或线程中运行同步下载，勿阻塞消息 matcher。
sync_stream_download_to_file("https://example.com/model.bin", Path("model.bin"))
```

需要给用户发私聊时使用 `send_private_msg_compat()` 或 `reply_private_message()`；下载进度可配合 `StreamDownloadProgress`，大小展示使用 `format_download_byte_size()`。

## 平台协作（官方插件 / 内置）

`pallas.api.platform`：多 Bot、分片、callback。社区插件默认禁止。导出表见 [Platform API](/developer/reference/platform-api)。

## 禁止 import

| 区域 | 原因 |
| --- | --- |
| `pallas.core.*`（除 api re-export） | 内部实现 |
| `pallas.product.*` | 产品域 |
| `pallas.console.*` | WebUI 维护者向 |
| `pallas.product.llm.client` 直调 | 普通聊天由内核 Agent / Provider 负责；插件勿旁路 |

CI：`tools/check_plugin_imports.py` 与 `community_plugin_author check` 会对齐上述边界。

## 后续阅读

- [插件开发入门](getting-started.md)
- [Golden Plugin](golden-plugin.md)
- [仓库布局与公开 API](/developer/reference/repo-layout)
- [Platform API](/developer/reference/platform-api)（官方 / 内置）
