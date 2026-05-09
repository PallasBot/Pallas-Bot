# block（其他牛牛消息拦截）

高优先级 **吞掉** 两类事件，避免后续插件处理：

1. **其他已连接牛牛账号** 在本群发送的群消息（`user_id` 落在插件维护的 `bots` 集合中，集合在 Bot 连接/断开时更新）。
2. 当前群牛牛处于 **睡眠**（`BotConfig.is_sleep()`）时的群消息与部分群通知。

## 配置

[`src/plugins/block/config.py`](../../../src/plugins/block/config.py) 中 `bots` 由运行时自动维护，一般无需手写。

## 说明

- 本插件默认被 **help** 列入 `ignored_plugins`，不出现在帮助菜单、也不参与「全部开启/关闭」。
- 若多实例共群，用于减少牛牛排挤与循环触发。

实现见 [`src/plugins/block/__init__.py`](../../../src/plugins/block/__init__.py)。
