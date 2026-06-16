# connectivity（牛牛连通）

探测框架与「牛牛连通 / 牛牛网关」口令已内核化至 [`features/service_gateways`](../../../src/features/service_gateways/)；本目录仅保留文档索引。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛连通 | 群内或私聊 | 并行探测智能对话 / 画画 / MAA / 唱歌 |
| 牛牛网关 | 群内或私聊 | 同 `牛牛连通`（兼容） |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `connectivity.probe` | everyone |

## 配置

地址在 WebUI **通用配置 → 外部服务地址** 或 **智能对话与 AI 服务** 中填写，落盘 `data/pallas_config/webui.json`。

## 实现

- 探测注册表：[`src/features/service_gateways/`](../../../src/features/service_gateways/)
- 口令与元数据：[`connectivity.py`](../../../src/features/service_gateways/connectivity.py)
- 由 `kernel_runtime` 在 worker/unified 加载（hub 不挂 QQ 口令）
