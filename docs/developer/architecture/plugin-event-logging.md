# 插件业务事件日志

插件自己的业务日志是排障事实，不受 NoneBot 插件加载或 matcher 生命周期降噪影响。生产 INFO 会隐藏的是框架的 `Succeeded to load plugin`、`handled`、`complete`、`cancelled`、`ignored` 等高频行；插件应显式记录自己的准备、执行和结果。

内置、官方和站点私有插件统一从 `pallas.api.logging` 导入 `format_plugin_event` 与 `register_plugin_startup_ready`。不要导入 `pallas.core`，也不要用全局 matcher 包裹自动推断生命周期。

## 事件

| 事件 | 何时记录 | 级别 | 必填字段 |
| --- | --- | --- | --- |
| `Ready` | 路由、依赖和后台任务已可用时注册；随启动摘要输出，每插件每次启动最多一条 | INFO | plugin、commands |
| 操作开始 | 显式命令真正开始执行时，例如 `Draw`、`Generate`、`SoberUp` | INFO | 业务主体、bot、group、user |
| 操作完成 | 实际副作用成功后，例如消息已经发送 | INFO | 领域结果、耗时 |
| 操作失败 | 命令抛出异常时 | ERROR | 业务主体、异常类型 |
| 异步操作 | 队列、跨进程或延后投递的 `Queue`、`Generate`、`Deliver` 等状态变化 | INFO / ERROR | task、必要的关联 ID |
| `Reply` / `Fanout` / `Reaction` | 无法由具体领域操作表达的实际外发结果 | INFO / ERROR | 目标与结果字段 |
| `Skipped` | 权限、冷却、缓存、去重、背压等未执行原因 | DEBUG | 原因 |

操作标签是插件内部稳定实现名的展示形式，统一转为 `PascalCase`：`arcana.draw` → `Draw`、`sober_up` → `SoberUp`、`clear_session` → `ClearSession`。模块列负责显示插件归属，因此标签不重复插件名。

`Reply`、`Fanout`、`Reaction` 只用于没有更精确领域动词的外发结果。`Draw` 这类完成日志已经表达了实际回复的业务含义，不再额外输出重复的 `Reply`。不为每个 matcher 输出准备、执行、结束日志，避免重新引入框架噪声。

## 格式

标签和标识符使用方括号，正文必须是完整的业务句子，优先写明动作产生的领域结果，避免 `outcome [sent]`、`request [...]` 等流水账式字段罗列。`request` 只在跨进程、回调或需要关联上下游时出现，优先使用原始消息 ID 或上游请求 ID；`task` 使用队列或任务系统中的稳定 ID，不能为日志临时生成 UUID。

```text
{Arcana}  [Ready] Plugin [arcana] registered commands [Draw].
{Arcana}  [Draw] Bot [100000001] began a tarot draw for user [100000003] in group [100000002].
{Arcana}  [Draw] Bot [100000001] drew [The Fool upright] for user [100000003] in group [100000002] in [18ms].
{Arcana}  [Draw] Bot [100000001] failed to draw for user [100000003] in group [100000002]: FileNotFoundError.
{LLMChat} [Generate] Task [chat-01J...] queued to generate a reply in group [100000002] for request [100000004].
{Repeater}[Fanout] Bot [100000001] sent a fanout reply in group [100000002]: ...
{Repeater}[Reaction] Bot [100000001] reacted to message [100000004] in group [100000002] with emoji [66].
```

## 接入方式

在模块加载期登记就绪状态；命令 handler 在开始时记录领域动作，在真实副作用成功后记录领域结果。异常必须保留堆栈，不吞掉异常。

```python
from nonebot import logger

from pallas.api.logging import format_plugin_event, register_plugin_startup_ready

register_plugin_startup_ready("arcana", ["arcana.draw"])

logger.info(
    format_plugin_event(
        "draw",
        f"Bot [{event.self_id}] began a tarot draw for user [{event.user_id}] "
        f"in group [{event.group_id}]",
    )
)

try:
    await bot.send(event, message)
except Exception as exc:
    logger.exception(
        format_plugin_event(
            "draw",
            f"Bot [{event.self_id}] failed to draw for user [{event.user_id}] "
            f"in group [{event.group_id}]: {type(exc).__name__}",
        )
    )
    raise
```

`format_plugin_event` 负责 `PascalCase` 标签和单行格式；调用方负责选择准确的业务边界、领域叙事和日志级别。首个试点是站点插件 Arcana，后续按命令入口、异步任务和外发路径分批覆盖 core 与 bundled play 插件。
