# connectivity（牛牛连通）

群内检测画画网关、MAA 端点、唱歌 AI 延迟；WebUI **通用配置 → 服务网关 / 连通性** 可编辑地址并一键检测。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛连通 | 群内 | 并行探测画画 / MAA / 唱歌 |
| 牛牛网关 | 群内 | 同 `牛牛连通`（兼容） |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `connectivity.probe` | everyone |

## 配置

地址写入 `data/pallas_config/webui.json`（画画、MAA、唱歌等键），由 WebUI 通用配置段统一编辑。探测逻辑见 [`service_probe`](../../../src/common/service_probe/)。

## 排障

| 现象 | 处理 |
| --- | --- |
| MAA 超时 | 确认 `maa_public_base_url` 对外可达 |
| 唱歌未测 | `sing_enable=false` 时仅提示未启用 |

## 实现

[`src/plugins/connectivity/`](../../../src/plugins/connectivity/)
