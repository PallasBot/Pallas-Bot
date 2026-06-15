# 实例与账号配置

## 实例 / 协议

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/instances` | Bot 进程、协议端快照（NapCat/Snowluma）、分片角色 |

响应合并 `pallas_protocol` 状态与控制台元信息；WebUI 对 `/instances` 有 45s 内存缓存，写操作后应 `invalidateInstancesCache`。

协议账号的启停/二维码等走 **协议子服务** HTTP（非本 API），见 WebUI `protocolApi.ts`。

## Bot / 群 / 用户配置表

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/bot-configs` | | 列表 |
| GET | `/bot-configs/{account}` | | 单账号 |
| PUT | `/bot-configs/{account}` | 是 | 更新 |
| GET | `/group-configs` | `q?` 搜索 | 群列表（可分页） |
| GET | `/group-configs/{group_id}` | | 单群 |
| PUT | `/group-configs/{group_id}` | 是 | 更新 |
| GET | `/user-configs` | `q?` | 用户列表 |
| GET | `/user-configs/{user_id}` | | 单用户 |
| PUT | `/user-configs/{user_id}` | 是 | 更新 |

配置存数据库（PostgreSQL 或 Mongo，依 `pallas.toml` 后端）；与 `src.foundation.config` 的 `BotConfig` / `GroupConfig` 同源。

## 前端对应

- `InstancesPage`、`ProtocolManagePage`：`fetchInstances`
- 社交配置弹窗：`fetchGroupConfigById`、`putGroupConfig`

实现：`extended_api.py`；持久化 `src/foundation/db/`。
