# 六、message_scrub 入站过滤

实现：`src/features/message_scrub/`。用户向说明：[message_scrub/README.md](../../common/message_scrub/README.md)。

## 6.1 何时需要

| 场景 | 建议 |
| --- | --- |
| 复读学习、做梦采集、大量读用户原文 | **应评估**接入审查链 |
| 纯 `on_command` 只解析命令参数 | 通常不必 |
| 出站生成（Bot 自己发的话） | 不由 message_scrub 管 |

## 6.2 插件侧

复读、做梦等已在内核路径调用审查；**新插件**若自建「学用户说话」逻辑，应：

1. 读 [message_scrub README](../../common/message_scrub/README.md) 的 hook 登记方式
2. 在入库前调用统一审查 API，勿复制一份关键词列表

## 6.3 运维配置

WebUI：**通用配置 → 消息审查与入站过滤**。**4.0 默认开启**；设 `PALLAS_MESSAGE_SCRUB_ENABLED=false` 可关闭。

保存后 hub 热重载；分片 worker 按 mtime 重读。

## 6.4 与 ingress / 分片

多进程部署时审查配置需在各 worker 一致；见 [分片部署](../../maintainer/deploy/sharded.md)。

## 6.5 下一步

- 提交前检查 → [七、测试与文档](./07-tests-and-docs.md)
