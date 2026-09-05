# 六、message_scrub 入站过滤

实现：`pallas/product/message_scrub/`。细则：[message_scrub/README.md](../../../common/message_scrub/README.md)。

## 6.1 何时需要

| 场景 | 建议 |
| --- | --- |
| 复读学习、做梦采集、大量读用户原文 | **应评估**接入审查链 |
| 纯 `on_command` 只解析命令参数 | 通常不必 |
| 出站生成（Bot 自己发的话） | 不由 message_scrub 管 |

## 6.2 Agent 动作

1. 读 [message_scrub README](../../../common/message_scrub/README.md) 的 hook / API
2. 入库前走统一审查（`pallas.api.safety`）；勿复制词表
3. 运维入口：WebUI **通用配置 → 消息审查与入站过滤**（**非** AI 配置）
4. **V4 默认开启**；内置下流词表（`resource/message_scrub/vulgar.txt`）默认生效；`PALLAS_MESSAGE_SCRUB_ENABLED=false` 可关

分片下配置须各 worker 一致 → [分片部署](../../../maintainer/deploy/sharded.md)。

## 6.3 下一步

- 提交前检查 → [七、测试与文档](./07-tests-and-docs.md)
