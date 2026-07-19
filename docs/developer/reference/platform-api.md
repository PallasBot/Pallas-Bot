# Platform API

`pallas.api.platform`：官方插件与内置插件的平台协作钩子。稳定面高于随意 `pallas.core.*` import，次于面向社区的 `pallas.api.*` 其它子包。

模块文档串：`pallas/api/platform/__init__.py`。

## 依赖分层

| 层 | 对象 | 社区插件 |
| --- | --- | --- |
| L1 | `pallas.api.commands` / `config` / `perm` / … | MUST |
| L2 | `pallas.api.platform` | 默认禁止；仅当确需舰队 / 分片 / callback |
| L3 | `pallas.core.*` / `console.*` / 深层 `product.*` | 禁止 |

社区插件若大量依赖 L2，通常边界过深，应提缺口升级为 L1 或改设计。

## 导出分组（现行 `__all__`）

| 分组 | 代表符号 |
| --- | --- |
| AI callback | `register_media_task_hooks`、`DRAW_IMAGE_TASK_TYPE` |
| Bot 角色 | `bot_role`、`is_sharded_hub`、`is_sharded_worker`、`is_sharding_active` |
| 发送不可用 | `is_bot_send_unavailable`、`log_bot_send_unavailable` |
| Ingress | `text_matches_plugin_fanout`、`dream_session_ingress_passes` |
| 多 Bot / claim | `try_claim_group_message_once`、`begin_group_exclusive_activity`、`claim_group_handler` |
| 舰队 | `get_fleet_bot_ids`、`connected_bot_ids`、`list_local_fleet_bots_in_group` |
| 分片在线 / 代发 | `get_cluster_online_bot_ids`、`send_group_message_as_bot`、`invoke_bot_action` |
| LLM（平台协作） | `get_llm_config`、`llm_server_base_url`、`llm_command_tool_row` |

完整列表以模块 `__all__` 为准；新增导出需同步本表。

## 准入（进入本页的平台边界）

- 被多个模块长期依赖
- 预期跨小版本保留
- 可用语义描述，不暴露当前文件布局
- 调用方无需理解大量内部实现

## 禁止场景

- 普通命令型插件仅为少写包装而跳过 L1
- 把 Platform 当随意内部捷径

## 相关

- [Internal API](internal-api.md)
- [pallas.api Cookbook](/developer/plugin-development/pallas-api-cookbook)
- [分片运行时](/developer/architecture/shard-runtime)
- [包布局](/developer/reference/repo-layout)
