# maa（MAA 远控）

[MAA 远程控制协议](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)：`getTask` / `reportStatus` + QQ 绑定、口令排队、结果回传。

## 用户命令

| 类型 | 口令示例 |
| --- | --- |
| 绑定 | `牛牛绑定MAA`、`牛牛MAA状态`、`牛牛切换MAA设备`、`牛牛MAA设备名`、`牛牛清空MAA队列` |
| 任务 | `牛牛长草`、`牛牛作战`、`牛牛公招`、`牛牛基建`、`牛牛截图`、`牛牛停止` 等 |
| 高级 | `牛牛MAA任务 <type> [params]` |

**上手**：配置 `maa_public_base_url` → MAA 填帮助页 URL（用户标识符 = QQ）→ 私聊绑定设备 → 群聊发口令。完整表见 **牛牛帮助 → MAA 远控**。

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

一般只需 **`maa_public_base_url`**（WebUI **服务网关 / 连通性** 亦可编辑）。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `maa_public_base_url` | 空 | 对外 HTTP 基址 |
| `maa_attach_screenshot` | true | 指令后附加截图 |
| `maa_combat_auto_prepare` | true | 作战前自动排队关卡设置 |

完整键见 [`config.py`](../../../src/plugins/maa/config.py)。改 `maa_get_task_path` 等会重挂路由并清帮助缓存。

## 排障

| 现象 | 处理 |
| --- | --- |
| 未检测到轮询 | MAA 端点不可达或 URL 错误 |
| 下发后无任务 | 未绑定或用户标识符非 QQ；查 `牛牛MAA状态` |
| 队列有、MAA 无 | 设备 id 与「当前选用」不一致；可清空队列重试 |
| 截图失败 | 调大反代 `client_max_body_size` |

## 实现

[`src/plugins/maa/`](../../../src/plugins/maa/)

## 维护者说明

以下内容勿写入 `PluginMetadata.usage` / `menu_data.detail_des` / 帮助用户文案。

### 任务分类

| 分类 | type 示例 | MAA 行为 |
| --- | --- | --- |
| 顺序任务 | `LinkStart`、`CaptureImage`、`Settings-*` | 按队列顺序执行 |
| 立即任务 | `CaptureImageNow`、`StopTask`、`HeartBeat` | 可插队 |

### 唤醒与子项

- `LinkStart`（牛牛长草）：含唤醒 + 按勾选跑子模块
- `LinkStart-WakeUp`：仅唤醒
- 其它 `LinkStart-*`：不含唤醒；游戏需已在主界面
- 牛牛作战当前临时下发 `LinkStart`（`COMBAT_COMMAND_TASK_TYPE`），上游修复后改回 `LinkStart-Combat`

### 作战与关卡

- `牛牛设置关卡`：最多 4 候选，仅下发 `Settings-Stage1`
- `maa_combat_auto_prepare`：作战前可自动排队已保存主关卡

### 多 Bot 同群

群内远控口令与 `牛牛MAA状态` 等命令经 `claim_group_handler("maa", …)`（`src.common.multi_bot_group`），同一条群消息仅一只牛响应。私聊绑定/切换设备不受影响。

### 代码索引

| 逻辑 | 位置 |
| --- | --- |
| 口令 → type | `tasks.py` |
| HTTP | `http_api.py`、`http_routes.py` |
| 队列/绑定 | `store.py` |
