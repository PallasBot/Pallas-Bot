# block（其它牛牛拦截）

> **4.0 起已收进内核**：[`src/platform/multi_bot/bot_filter.py`](../../../src/platform/multi_bot/bot_filter.py) 与 [`connected_roster.py`](../../../src/platform/multi_bot/connected_roster.py)。本目录插件已移除。

拦截**其它牛牛账号**在本群的群消息与部分通知，避免多 Bot 互相触发逻辑（类似真寻 `bot_filter`）。

## 用户命令

无（维护者向能力）。

## 实现

- 连接名册：`platform/multi_bot/connected_roster.py`
- 互聊过滤与 sleep 拦截：`platform/multi_bot/bot_filter.py`
- 启动注册：`platform/bot_runtime/kernel_runtime.py`
