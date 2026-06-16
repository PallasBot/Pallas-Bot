# maa（MAA 远控）

> **官方扩展**：`pallas-plugin-maa`（`uv sync --extra plugins-maa`）

在 QQ 里给已绑定的 [MAA](https://maa.plus/) 下发远控任务并接收结果（长草、作战、公招、基建、截图等）。

## 用户命令

| 类型 | 口令示例 |
| --- | --- |
| 绑定 | `牛牛绑定MAA`、`牛牛MAA状态`、`牛牛切换MAA设备`、`牛牛MAA设备名`、`牛牛清空MAA队列` |
| 任务 | `牛牛长草`、`牛牛作战`、`牛牛公招`、`牛牛基建`、`牛牛截图`、`牛牛停止` 等 |
| 高级 | `牛牛MAA任务 <type> [params]` |

**上手**：配置对外访问地址 → MAA 填帮助页 URL（用户标识符 = QQ）→ 私聊绑定设备 → 群聊发口令。完整表见 **牛牛帮助 → MAA 远控**。

### 多台设备

| 口令 | 说明 |
| --- | --- |
| `牛牛MAA状态` | 列表与当前选用 |
| `牛牛切换MAA设备` | 改远控目标 |
| `牛牛MAA设备名` | 设置别名 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `maa.bind` | everyone |
| `maa.control` | everyone |
| `maa.status` | everyone |

## 配置

一般只需 **对外访问地址**（WebUI **通用配置 → 外部服务地址** 或插件配置）。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `maa_public_base_url` | 空 | 对外 HTTP 基址 |
| `maa_attach_screenshot` | true | 指令后附加截图 |
| `maa_combat_auto_prepare` | true | 作战前自动排队关卡设置 |

完整键见 [`config.py`](../../../src/plugins/maa/config.py)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 未检测到轮询 | MAA 端点不可达或 URL 错误；多机部署须各实例共用 `data/` |
| 下发后无任务 | 未绑定或用户标识符非 QQ；查 `牛牛MAA状态` |
| 队列有、MAA 无 | 设备 id 与「当前选用」不一致；可清空队列重试 |
| 截图失败 | 调大反代上传大小限制 |

## 实现

[`src/plugins/maa/`](../../../src/plugins/maa/)

## 维护者说明

以下内容勿写入 `PluginMetadata.usage` / `menu_data.detail_des` / 帮助用户文案。

### 协议与任务

- HTTP 接口遵循 [MAA 远程控制协议](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)（`getTask` / `reportStatus`）。
- 顺序任务（`LinkStart`、`CaptureImage`、`Settings-*`）按队列执行；立即任务（`CaptureImageNow`、`StopTask`、`HeartBeat`）可插队。
- `LinkStart`（牛牛长草）：含唤醒 + 按勾选跑子模块；其它 `LinkStart-*` 不含唤醒。
- 牛牛作战当前临时下发 `LinkStart`（`COMBAT_COMMAND_TASK_TYPE`），上游修复后改回 `LinkStart-Combat`。

### 多 Bot 同群

群内远控口令与 `牛牛MAA状态` 等命令经 `claim_group_handler("maa", …)`，同一条群消息仅一只牛响应。私聊绑定/切换设备不受影响。

### 代码索引

| 逻辑 | 位置 |
| --- | --- |
| 口令 → type | `tasks.py` |
| HTTP | `http_api.py`、`http_routes.py` |
| 队列/绑定 | `store.py` |
