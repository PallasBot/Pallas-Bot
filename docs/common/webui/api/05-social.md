# 好友、群与申请

| 方法 | 路径 | Query | 写 | 说明 |
| --- | --- | --- | --- | --- |
| GET | `/friend-requests` | `self_id?` | | 待处理好友申请 |
| GET | `/friend-list` | `self_id?` | | 好友列表 |
| GET | `/group-list` | `self_id?` | | 群列表 |
| GET | `/request-overview` | `self_id?` | | 申请概览（好友+群） |
| POST | `/request-actions` | | 是 | 单条同意/拒绝 |
| POST | `/request-actions/batch` | | 是 | 批量处理 |

写操作 Body 含 `self_id`、`flag`、`approve` 等字段（与 OneBot v11 申请 API 对齐）；需写 token。

数据来自在线 OneBot v11 Bot 调用 + 本地 pending 缓存（`request_handler` 落盘）。

## 前端对应

- `FriendsGroupsPage`：`fetchFriendList`、`fetchGroupList`、`fetchRequestOverview`、`postRequestActions` 等

实现：`extended_api.py` 内 OneBot 代理与 pending 读写。

用户向说明：[request_handler 插件](../../../plugins/request_handler/README.md)。
