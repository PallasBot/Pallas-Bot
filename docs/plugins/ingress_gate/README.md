# ingress_gate（入站网关）

> **4.0 起已收进内核**：[`src/platform/ingress/gate.py`](../../../src/platform/ingress/gate.py)。本目录插件已移除。

群消息预处理：多牛同群识别、@ 定向、多机协同与跨牛接话；分片 worker 另含跨片协调。

## 实现

- 预处理器与启动日志：`platform/ingress/gate.py`
- 主持牛选择与多只牛一起接话：`platform/ingress/*`
- 启动注册：`platform/bot_runtime/kernel_runtime.py`（worker / unified）
