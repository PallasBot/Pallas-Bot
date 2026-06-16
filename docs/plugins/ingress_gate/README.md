# ingress_gate（入站网关）

> **4.0 起已收进内核**：[`src/platform/ingress/gate.py`](../../../src/platform/ingress/gate.py)。本目录插件已移除。

群消息预处理：牛牛舰队识别、@ 定向、联邦与跨 Bot claim；分片 worker 另含跨片 claim 与 fanout。

## 实现

- 预处理器与启动日志：`platform/ingress/gate.py`
- claim / fanout / 主持牛 gate：`platform/ingress/*`
- 启动注册：`platform/bot_runtime/kernel_runtime.py`（worker / unified）
